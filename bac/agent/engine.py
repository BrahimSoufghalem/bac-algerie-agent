import asyncio, json, time, uuid
from collections import Counter
from pathlib import Path
import yaml
from fastapi import HTTPException
from bac.core.db import uid, js
from bac.agent.provider import OpenAIChat, ModelError
from bac.agent.tools import Tools


class AgentEngine:
    def __init__(self, s):
        self.s = s
        self.db = s.db
        self.stop = asyncio.Event()

    def enqueue(self, chat, user, text, edit_id=None, retry=False):
        if len(text) > 8000 or not text.strip():
            raise HTTPException(422, "Message must contain 1–8000 characters")
        cfg = self.db.one("SELECT config_id FROM active_models WHERE slot='agent'")
        if not cfg:
            raise HTTPException(409, "The owner must configure the teaching model")
        with self.db.tx() as c:
            if not c.execute(
                "SELECT 1 FROM conversations WHERE id=? AND user_id=?",
                (chat, user["id"]),
            ).fetchone():
                raise HTTPException(404, "Conversation not found")
            if c.execute(
                "SELECT 1 FROM agent_runs WHERE conversation_id=? AND status IN ('QUEUED','RUNNING')",
                (chat,),
            ).fetchone():
                raise HTTPException(409, "A run is already active")
            limit = user.get("daily_limit") or self.s.settings.max_daily_requests
            used = c.execute(
                "SELECT count(*) FROM agent_runs WHERE user_id=? AND created_at>?",
                (user["id"], time.time() - 86400),
            ).fetchone()[0]
            if used >= limit:
                raise HTTPException(429, "Daily run allowance reached")
            if edit_id:
                original = c.execute(
                    "SELECT * FROM messages WHERE id=? AND conversation_id=? AND role='user' AND active=1",
                    (edit_id, chat),
                ).fetchone()
                if not original:
                    raise HTTPException(404, "Original user message not found")
                c.execute(
                    "UPDATE messages SET active=0 WHERE conversation_id=? AND created_at>=?",
                    (chat, original["created_at"]),
                )
                c.execute("DELETE FROM loaded_context WHERE conversation_id=?", (chat,))
            run = uid("run")
            now = time.time()
            if retry:
                original = c.execute(
                    "SELECT * FROM messages WHERE conversation_id=? AND role='user' AND active=1 ORDER BY created_at DESC LIMIT 1",
                    (chat,),
                ).fetchone()
                if not original:
                    raise HTTPException(409, "There is no user message to retry")
                msg = original["id"]
                c.execute(
                    "UPDATE messages SET active=0 WHERE conversation_id=? AND created_at>?",
                    (chat, original["created_at"]),
                )
                c.execute("DELETE FROM loaded_context WHERE conversation_id=?", (chat,))
            else:
                msg = uid("msg")
                c.execute(
                    "INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,?,?,?)",
                    (msg, chat, "user", text, now),
                )
            c.execute(
                "INSERT INTO agent_runs(id,conversation_id,user_id,message_id,config_id,created_at) VALUES(?,?,?,?,?,?)",
                (run, chat, user["id"], msg, cfg["config_id"], now),
            )
            c.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, chat))
        self.db.event(run, "queued", {"label": "في انتظار التنفيذ"})
        return run

    def claim(self):
        with self.db.tx() as c:
            stale = c.execute(
                "SELECT id FROM agent_runs WHERE status='RUNNING' AND lease_until<?",
                (time.time(),),
            ).fetchall()
            for r in stale:
                c.execute(
                    "UPDATE agent_runs SET status='INTERRUPTED',error='WORKER_INTERRUPTED',finished_at=? WHERE id=?",
                    (time.time(), r["id"]),
                )
                c.execute(
                    "INSERT INTO run_events(run_id,type,payload,created_at) VALUES(?,?,?,?)",
                    (
                        r["id"],
                        "error",
                        js(
                            {
                                "code": "WORKER_INTERRUPTED",
                                "label": "انقطع التنفيذ؛ يمكنك إعادة المحاولة. لا توجد إعادة مدفوعة تلقائية.",
                            }
                        ),
                        time.time(),
                    ),
                )
            if (
                c.execute(
                    "SELECT count(*) FROM agent_runs WHERE status='RUNNING'"
                ).fetchone()[0]
                >= self.s.settings.agent_workers
            ):
                return None
            r = c.execute(
                "SELECT * FROM agent_runs WHERE status='QUEUED' ORDER BY created_at LIMIT 1"
            ).fetchone()
            if not r:
                return None
            token = uuid.uuid4().hex
            c.execute(
                "UPDATE agent_runs SET status='RUNNING',attempts=attempts+1,lease_token=?,lease_until=? WHERE id=?",
                (token, time.time() + 20, r["id"]),
            )
            return dict(
                c.execute("SELECT * FROM agent_runs WHERE id=?", (r["id"],)).fetchone()
            )

    def emit(self, run, type, payload):
        self.db.event(run["id"], type, payload, run["lease_token"])

    async def monitor(self, run, task):
        while True:
            await asyncio.sleep(0.25)
            r = self.db.one(
                "SELECT status,cancel_requested,lease_token FROM agent_runs WHERE id=?",
                (run["id"],),
            )
            if (
                not r
                or r["cancel_requested"]
                or r["lease_token"] != run["lease_token"]
                or r["status"] != "RUNNING"
            ):
                task.cancel()
                return
            self.db.execute(
                "UPDATE agent_runs SET lease_until=? WHERE id=? AND lease_token=?",
                (time.time() + 20, run["id"], run["lease_token"]),
            )

    def context(self, run, tools, user):
        cfg = yaml.safe_load(
            (Path(__file__).resolve().parents[2] / "config/agent.yaml").read_text()
        )
        chat = self.db.one(
            "SELECT overrides FROM conversations WHERE id=?", (run["conversation_id"],)
        )
        pref = {**json.loads(user["preferences"]), **json.loads(chat["overrides"])}
        system = cfg["system"] + "\nRole=" + user["role"] + "; preferences=" + js(pref)
        messages = [{"role": "system", "content": system}]
        remaining = self.s.settings.max_context_chars - len(system)
        loaded = self.db.rows(
            "SELECT * FROM loaded_context WHERE conversation_id=? ORDER BY loaded_at DESC LIMIT 2",
            (run["conversation_id"],),
        )
        for row in loaded:
            try:
                scope = row.get("scope", "full")
                payload = tools.load(
                    row.get("scope_id") or row["node_id"], remember=False, scope=scope
                )
            except (HTTPException, ValueError):
                continue
            text = js(payload)
            if "error" not in payload and len(text) < remaining // 2:
                tools.remember(payload, scope, row.get("scope_id") or row["node_id"])
                messages.append(
                    {
                        "role": "user",
                        "content": "Previously loaded untrusted source data:\n" + text,
                    }
                )
                remaining -= len(text)
        history = self.db.rows(
            "SELECT role,content FROM messages WHERE conversation_id=? AND active=1 ORDER BY created_at DESC LIMIT 12",
            (run["conversation_id"],),
        )
        chosen = []
        for h in history:
            if len(h["content"]) > remaining:
                break
            chosen.append(h)
            remaining -= len(h["content"])
        messages.extend(reversed(chosen))
        return messages

    def usage(self, run, cfg, record, duration):
        inp = record.get("prompt_tokens")
        out = record.get("completion_tokens")
        cached = (
            record.get("prompt_tokens_details", {}).get("cached_tokens")
            if isinstance(record.get("prompt_tokens_details", {}), dict)
            else None
        )
        cost = None
        if (
            isinstance(inp, int)
            and isinstance(out, int)
            and cfg.get("input_price_per_million") is not None
            and cfg.get("output_price_per_million") is not None
        ):
            cost = (
                inp * cfg["input_price_per_million"]
                + out * cfg["output_price_per_million"]
            ) / 1e6
            if (
                isinstance(cached, int)
                and cfg.get("cached_price_per_million") is not None
            ):
                cost += (
                    cached
                    * (cfg["cached_price_per_million"] - cfg["input_price_per_million"])
                    / 1e6
                )
        self.db.execute(
            "INSERT INTO model_usage(run_id,user_id,config_id,model,input_tokens,output_tokens,cached_tokens,estimated_cost,duration_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                run["id"],
                run["user_id"],
                run["config_id"],
                cfg["model"],
                inp if isinstance(inp, int) else None,
                out if isinstance(out, int) else None,
                cached if isinstance(cached, int) else None,
                cost,
                duration,
                time.time(),
            ),
        )

    async def body(self, run):
        row = self.db.one("SELECT * FROM model_configs WHERE id=?", (run["config_id"],))
        cfg = json.loads(row["config"])
        user = self.db.one("SELECT * FROM users WHERE id=?", (run["user_id"],))
        tools = Tools(self.s, user, run["conversation_id"], run["id"])
        if not user or not user["active"]:
            raise ModelError("ACCOUNT_DISABLED")
        provider = (
            self.s.chat_factory(cfg, self.s.vault.decrypt(row["encrypted_key"]))
            if self.s.chat_factory
            else OpenAIChat(
                cfg,
                self.s.vault.decrypt(row["encrypted_key"]),
                self.s.settings.allow_private_model_urls,
            )
        )
        messages = self.context(run, tools, user)
        signatures = Counter()
        tool_count = 0
        for step in range(self.s.settings.max_run_steps):
            self.emit(
                run, "model_start", {"label": "جارٍ إعداد الإجابة", "step": step + 1}
            )
            self.db.execute(
                "UPDATE agent_runs SET steps=? WHERE id=?", (step + 1, run["id"])
            )
            started = time.monotonic()
            message = None
            usage = {}
            try:
                async for item in provider.stream(messages, tools.definitions()):
                    if item["type"] == "delta":
                        self.emit(run, "delta", {"text": item["text"]})
                    elif item["type"] == "usage":
                        usage = item["data"]
                    elif item["type"] == "result":
                        message = item["message"]
            finally:
                self.usage(run, cfg, usage, (time.monotonic() - started) * 1000)
            if not message:
                raise ModelError("EMPTY_MODEL_RESPONSE")
            calls = message.get("tool_calls") or []
            if len(calls) > 6:
                raise ModelError("TOO_MANY_TOOLS")
            if not calls:
                content = message.get("content") or ""
                answer, sources = tools.answer(
                    {
                        "blocks": [{"type": "text", "text": content}],
                        "source_ids": list(tools.sources),
                    }
                )
                return self.finish(run, answer, sources)
            messages.append(
                {
                    "role": "assistant",
                    "content": message.get("content"),
                    "tool_calls": calls,
                }
            )
            for call in calls:
                name = call["function"]["name"]
                signature = name + ":" + call["function"]["arguments"]
                signatures[signature] += 1
                if signatures[signature] > 2:
                    raise ModelError("REPEATED_TOOL_LOOP")
                try:
                    args = json.loads(call["function"]["arguments"])
                    if name == "render_answer":
                        answer, sources = tools.answer(args)
                        return self.finish(run, answer, sources)
                    tool_count += 1
                    if tool_count > 20:
                        raise ModelError("TOOL_BUDGET_EXCEEDED")
                    self.emit(
                        run,
                        "tool_start",
                        {
                            "name": name,
                            "label": {
                                "search_library": "البحث في المكتبة المنشورة",
                                "get_table_of_contents": "قراءة الفهرس",
                                "get_lesson_full": "قراءة الدرس كاملًا",
                                "get_section": "قراءة قسم من المصدر",
                                "calculate": "حساب التعبير العددي",
                                "verify_calculation": "التحقق من الناتج العددي",
                                "verify_equation": "فحص التعويض وشروط المسألة",
                                "symbolic_math": "إجراء حساب رمزي",
                                "convert_units": "تحويل الوحدات",
                                "verify_dimensions": "فحص الأبعاد والوحدات",
                                "run_scientific_code": "تنفيذ حساب علمي مقيّد",
                                "plot_function": "حساب نقاط المنحنى",
                                "plot_data": "فحص بيانات الرسم",
                                "draw_diagram": "إنشاء مخطط هندسي مقيّد",
                                "plot_from_result": "رسم المخرجات المحسوبة فعليًا",
                            }.get(name, "تنفيذ أداة " + name),
                        },
                    )
                    result = await asyncio.to_thread(tools.execute, name, args)
                    self.emit(
                        run,
                        "tool_end",
                        {
                            "name": name,
                            "success": "error" not in result
                            and result.get("output", {}).get("status")
                            not in ("failed", "inconclusive"),
                            "label": (
                                "تعذر تأكيد الفحص؛ راجع المعطيات والشروط"
                                if result.get("output", {}).get("status")
                                in ("failed", "inconclusive")
                                else "نجح الفحص المحدد، لا كل الشرح"
                                if result.get("output", {}).get("status") == "passed"
                                else "تم تنفيذ الأداة"
                            )
                            if "error" not in result
                            else "تعذر تنفيذ الأداة ضمن حدودها",
                        },
                    )
                except ModelError:
                    raise
                except (ValueError, HTTPException, KeyError) as exc:
                    result = {
                        "error": "TOOL_INPUT_OR_SOURCE_ERROR",
                        "message": getattr(exc, "detail", str(exc))[:300],
                    }
                    self.emit(
                        run,
                        "tool_end",
                        {
                            "name": name,
                            "success": False,
                            "label": "تعذر تنفيذ الأداة أو تأكيد المصدر",
                        },
                    )
                serialized = js(result)
                if len(serialized) > self.s.settings.max_tool_chars:
                    serialized = js(
                        {
                            "error": "TOOL_RESULT_EXCEEDS_BUDGET",
                            "instruction": "Request a smaller structural section.",
                        }
                    )
                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": serialized}
                )
                self.db.execute(
                    "UPDATE agent_runs SET tool_calls=? WHERE id=?",
                    (tool_count, run["id"]),
                )
                if (
                    sum(len(js(m)) for m in messages)
                    > self.s.settings.max_context_chars
                ):
                    raise ModelError("CONTEXT_BUDGET_EXCEEDED")
        raise ModelError("STEP_BUDGET_EXCEEDED")

    def finish(self, run, answer, sources):
        id = uid("msg")
        content = "\n\n".join(b.text for b in answer.blocks if b.type == "text")
        payload = {
            "message_id": id,
            "blocks": [b.model_dump() for b in answer.blocks],
            "sources": sources,
            "warnings": answer.warnings,
        }
        with self.db.tx() as c:
            r = c.execute(
                "SELECT 1 FROM agent_runs WHERE id=? AND status='RUNNING' AND lease_token=? AND lease_until>? AND cancel_requested=0",
                (run["id"], run["lease_token"], time.time()),
            ).fetchone()
            if not r:
                raise ModelError("LEASE_LOST_OR_CANCELLED")
            c.execute(
                "INSERT INTO messages(id,conversation_id,role,content,blocks,sources,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    id,
                    run["conversation_id"],
                    "assistant",
                    content,
                    js(payload["blocks"]),
                    js(sources),
                    time.time(),
                ),
            )
            c.execute(
                "INSERT INTO run_events(run_id,type,payload,created_at) VALUES(?,?,?,?)",
                (run["id"], "answer", js(payload), time.time()),
            )
            c.execute(
                "UPDATE agent_runs SET status='COMPLETED',finished_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",
                (time.time(), run["id"]),
            )
        return payload

    async def process(self, run):
        task = asyncio.create_task(self.body(run))
        monitor = asyncio.create_task(self.monitor(run, task))
        try:
            await asyncio.wait_for(task, timeout=self.s.settings.max_run_seconds)
        except (Exception, asyncio.CancelledError) as exc:
            row = self.db.one(
                "SELECT cancel_requested FROM agent_runs WHERE id=?", (run["id"],)
            )
            status = "CANCELLED" if row and row["cancel_requested"] else "FAILED"
            code = (
                "CANCELLED"
                if status == "CANCELLED"
                else "RUN_TIMEOUT"
                if isinstance(exc, asyncio.TimeoutError)
                else str(exc)
                if isinstance(exc, ModelError)
                else "AGENT_EXECUTION_ERROR"
            )
            with self.db.tx() as c:
                if c.execute(
                    "SELECT 1 FROM agent_runs WHERE id=? AND lease_token=? AND status='RUNNING'",
                    (run["id"], run["lease_token"]),
                ).fetchone():
                    c.execute(
                        "UPDATE agent_runs SET status=?,error=?,finished_at=?,lease_token=NULL,lease_until=NULL WHERE id=?",
                        (status, code, time.time(), run["id"]),
                    )
                    c.execute(
                        "INSERT INTO run_events(run_id,type,payload,created_at) VALUES(?,?,?,?)",
                        (
                            run["id"],
                            "error",
                            js(
                                {
                                    "code": code,
                                    "label": "توقف التنفيذ؛ يمكنك تعديل الرسالة أو إعادة المحاولة.",
                                }
                            ),
                            time.time(),
                        ),
                    )
        finally:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)

    async def worker(self):
        while not self.stop.is_set():
            run = await asyncio.to_thread(self.claim)
            if run:
                await self.process(run)
            else:
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    pass

    async def run(self):
        await asyncio.gather(
            *(self.worker() for _ in range(self.s.settings.agent_workers))
        )
