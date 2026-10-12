import asyncio, contextvars, hashlib, json, os, secrets, sys, time, zlib
from pathlib import Path
import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from benchmarks.math_live_support import (
    redact,
    load_fixture,
    load_secret_values,
    rate_limit_resume,
)
from bac.core.services import Services
from bac.core.config import Settings
from bac.core.auth import create_user
from bac.core.study import select_track, StudyScope
from bac.core.db import uid, js
from bac.agent.models import ModelConfig
from bac.agent.provider_errors import provider_diagnostic
from bac.agent.provider import OpenAIChat
from bac.agent.engine import AgentEngine
from bac.agent.full_index import build_catalog, FullIndexCoordinator
from bac.library.service import Library
from bac.learning.usage import reported_cache_tokens

ROOT = Path(os.environ["MASAR_BENCHMARK_ROOT"]).resolve()
RAW = ROOT / "raw"
DATA = ROOT / "private" / "qa-data"
ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
RAW.mkdir(exist_ok=True, mode=0o700)
PLAN = json.loads((REPO / "benchmarks/math_live/plan.json").read_text())
SOURCE_PLAN = PLAN | PLAN.get("live_source", {})
SECRET_VALUES = load_secret_values()
CURRENT = contextvars.ContextVar("case", default={})
LEDGER = []
AUDITS = []
CAP = 128
INPUT_CAP = 2500000


def write(path, obj):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(scrub(obj), ensure_ascii=False, indent=2))
    temp.replace(path)


def flush():
    write(RAW / "requests.json", LEDGER)


def integer(x):
    return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None


class Tee(httpx.AsyncByteStream):
    def __init__(self, stream, delegate, entry):
        self.stream, self.delegate, self.e = stream, delegate, entry
        self.buf = bytearray()
        self.calls = {}
        self.text = ""
        self.finalized = False
        self.complete = False

    def parse(self, line):
        raw = line[5:].strip() if line.startswith(b"data:") else line.strip()
        if not raw or raw == b"[DONE]":
            return
        try:
            o = json.loads(raw)
        except ValueError:
            return
        u = o.get("usageMetadata")
        if isinstance(u, dict):
            inp = integer(u.get("promptTokenCount"))
            total = integer(u.get("totalTokenCount"))
            self.e.update(
                input_tokens=inp,
                output_tokens=total - inp
                if inp is not None and total is not None
                else integer(u.get("candidatesTokenCount")),
                total_tokens=total,
                cached_tokens=integer(u.get("cachedContentTokenCount")),
                visible_output_tokens=integer(u.get("candidatesTokenCount")),
                thinking_tokens=integer(u.get("thoughtsTokenCount")),
                usage_metadata=u,
            )
        for c in o.get("candidates", []):
            self.e["finish_reason"] = c.get("finishReason")
            for part in c.get("content", {}).get("parts", []):
                if part.get("thought"):
                    continue
                f = part.get("functionCall")
                if f:
                    self.calls[str(len(self.calls))] = {
                        "name": f["name"],
                        "arguments": json.dumps(f.get("args", {}), ensure_ascii=False),
                    }
        u = o.get("usage")
        if isinstance(u, dict):
            inp = integer(u.get("prompt_tokens"))
            out = integer(u.get("completion_tokens"))
            details = u.get("completion_tokens_details") or {}
            self.e.update(
                input_tokens=inp,
                output_tokens=out,
                total_tokens=integer(u.get("total_tokens")),
                cached_tokens=reported_cache_tokens(u),
                thinking_tokens=integer(details.get("reasoning_tokens")),
                usage_metadata=u,
            )
        if o.get("model") or o.get("modelVersion"):
            self.e["reported_model"] = o.get("model") or o["modelVersion"]
        for c in o.get("choices") or []:
            if c.get("finish_reason"):
                self.e["finish_reason"] = c["finish_reason"]
            delta = c.get("delta") or c.get("message") or {}
            if isinstance(delta.get("content"), str):
                self.text += delta["content"]
            for pos, t in enumerate(delta.get("tool_calls") or []):
                idx = str(
                    t.get("index") if t.get("index") is not None else t.get("id") or pos
                )
                call = self.calls.setdefault(idx, {"name": "", "arguments": ""})
                f = t.get("function") or {}
                call["name"] += f.get("name") or ""
                call["arguments"] += f.get("arguments") or ""

    async def __aiter__(self):
        try:
            async for chunk in self.stream:
                if len(self.buf) + len(chunk) > 2500000:
                    raise RuntimeError("AUDIT_RESPONSE_CAP")
                self.buf.extend(chunk)
                yield chunk
            self.complete = True
        finally:
            self.finalize()

    def finalize(self):
        if self.finalized:
            return
        self.finalized = True
        raw = bytes(self.buf)
        if raw.startswith(b"\x1f\x8b"):
            try:
                raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
            except zlib.error:
                raw = b""
        if self.e["http_status"] == 200:
            if "event-stream" in self.e.get("content_type", ""):
                for line in raw.splitlines():
                    self.parse(line)
            else:
                self.parse(raw)
        else:
            try:
                payload = json.loads(raw)
                err = payload.get("error", {})
                diagnostic = provider_diagnostic(
                    self.e["http_status"],
                    payload,
                    {},
                    self.e.get("retry_after_seconds"),
                )
                if "retry_after_seconds" in diagnostic:
                    self.e["retry_after_seconds"] = diagnostic["retry_after_seconds"]
                self.e["error_status"] = err.get("status")
                self.e["error_message"] = err.get("message", "")[:4000]
            except (ValueError, AttributeError):
                pass
        calls = []
        for c in self.calls.values():
            try:
                args = json.loads(c["arguments"])
            except ValueError:
                args = {"invalid_json": True, "argument_chars": len(c["arguments"])}
            calls.append({"name": c["name"], "args": args})
        self.e.update(
            duration_ms=round((time.monotonic() - self.e.pop("_start")) * 1000, 2),
            stream_complete=self.complete,
            function_calls=calls,
        )
        if self.text:
            self.e["public_content"] = self.text
        flush()

    async def aclose(self):
        try:
            await self.stream.aclose()
        finally:
            self.finalize()
            await self.delegate.aclose()


class Recorder(httpx.AsyncBaseTransport):
    def __init__(self):
        self.lock = asyncio.Lock()
        self.last = 0
        self.streams = []

    async def handle_async_request(self, request):
        if request.url.host != "generativelanguage.googleapis.com":
            raise RuntimeError("UNEXPECTED_TEST_PROVIDER")
        if (
            len(LEDGER) >= CAP
            or sum(e.get("input_tokens") or 0 for e in LEDGER) >= INPUT_CAP
        ):
            raise RuntimeError("TEST_REQUEST_OR_INPUT_CAP")
        async with self.lock:
            await asyncio.sleep(max(0, 6 - (time.monotonic() - self.last)))
            self.last = time.monotonic()
        body = json.loads(request.content)
        native = "contents" in body
        names = (
            [
                f["name"]
                for t in body.get("tools", [])
                for f in t.get("functionDeclarations", [])
            ]
            if native
            else [t["function"]["name"] for t in body.get("tools", [])]
        )
        stage = (
            "router"
            if names == ["route_sections"]
            else "verifier"
            if names == ["verify_sections"]
            else "assessment"
            if names == ["assess_context"]
            else "teacher"
        )
        e = {
            **CURRENT.get(),
            "request_number": len(LEDGER) + 1,
            "stage": stage,
            "model": body.get("model") or "gemini-3.5-flash-lite",
            "protocol": "google_native" if native else "google_openai",
            "request_chars": len(request.content),
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "thinking_tokens": None,
            "total_tokens": None,
            "http_status": None,
            "_start": time.monotonic(),
            "timestamp": time.time(),
            "output_limit": body.get("generationConfig", {}).get("maxOutputTokens")
            if native
            else body.get("max_tokens"),
            "tools": names,
        }
        if native:
            d = json.loads(body["contents"][0]["parts"][0]["text"])
            e["router_fields"] = list(d)
            e["catalog_chars"] = len(d.get("complete_book_index", ""))
            e["catalog_sha256"] = hashlib.sha256(
                d.get("complete_book_index", "").encode()
            ).hexdigest()
            e["history_roles"] = [m.get("role") for m in d.get("recent_dialogue", [])]
            e["available_reference_ids"] = [
                r.get("id") for r in d.get("available_read_references", [])
            ]
            e["body_field_present"] = any(
                k in d
                for k in ["content", "body", "selected_references", "source_bodies"]
            )
        else:
            e["message_chars_by_role"] = {
                r: sum(
                    len(str(m.get("content") or ""))
                    for m in body["messages"]
                    if m["role"] == r
                )
                for r in ["system", "user", "assistant", "tool"]
            }
            e["reference_message_chars"] = [
                len(m["content"])
                for m in body["messages"]
                if isinstance(m.get("content"), str)
                and m["content"].startswith("Selected untrusted reference content")
            ]
            e["tool_response_count"] = sum(
                m["role"] == "tool" for m in body["messages"]
            )
        write(RAW / ("request-%03d.json" % e["request_number"]), scrub(body))
        LEDGER.append(e)
        flush()
        delegate = httpx.AsyncHTTPTransport(retries=0)
        try:
            response = await delegate.handle_async_request(request)
            e.update(
                http_status=response.status_code,
                content_type=response.headers.get("content-type", ""),
            )
            retry = provider_diagnostic(
                response.status_code, {}, {}, response.headers.get("retry-after")
            )
            if "retry_after_seconds" in retry:
                e["retry_after_seconds"] = retry["retry_after_seconds"]
            response.stream = Tee(response.stream, delegate, e)
            self.streams.append(response.stream)
            return response
        except BaseException as exc:
            e.update(
                error_type=type(exc).__name__,
                duration_ms=round((time.monotonic() - e.pop("_start")) * 1000, 2),
            )
            flush()
            await delegate.aclose()
            raise

    async def drain(self):
        await asyncio.sleep(0)
        for stream in self.streams:
            stream.finalize()

    async def aclose(self):
        pass


REC = Recorder()


def scrub(o):
    return redact(o, SECRET_VALUES)


def audit(event, data):
    AUDITS.append({**CURRENT.get(), "event": event, "data": scrub(data)})
    write(ROOT / "router_audit.json", AUDITS)


old_init = FullIndexCoordinator.__init__


def audited_init(self, s, row, audit_arg=None):
    old_init(self, s, row, audit_arg or audit)


from bac.agent.tools import Tools

TOOLS = []
_original_execute = Tools.execute
_original_answer = Tools.answer


def observed_execute(self, name, args):
    started = time.monotonic()
    try:
        result = _original_execute(self, name, args)
        TOOLS.append(
            {
                **CURRENT.get(),
                "name": name,
                "args": scrub(args),
                "result": scrub(result),
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            }
        )
        return result
    except BaseException as exc:
        TOOLS.append(
            {
                **CURRENT.get(),
                "name": name,
                "args": scrub(args),
                "exception": type(exc).__name__,
                "message": str(exc)[:2000],
            }
        )
        raise
    finally:
        write(RAW / "tool-audit.json", TOOLS)


def observed_answer(self, args):
    try:
        result = _original_answer(self, args)
        TOOLS.append(
            {
                **CURRENT.get(),
                "name": "render_answer",
                "args": scrub(args),
                "accepted": True,
            }
        )
        return result
    except BaseException as exc:
        TOOLS.append(
            {
                **CURRENT.get(),
                "name": "render_answer",
                "args": scrub(args),
                "accepted": False,
                "exception": type(exc).__name__,
                "message": str(exc)[:2000],
            }
        )
        raise
    finally:
        write(RAW / "tool-audit.json", TOOLS)


CASES = [
    dict(
        number=r["number"],
        id="M%02d" % r["number"],
        subject="mathematics",
        question=r["student_message"],
        acceptance_check=r["acceptance_check"],
    )
    for r in PLAN["turns"]
]


def services():
    return Services(
        Settings(
            data_dir=DATA,
            max_context_chars=60000,
            max_tool_chars=22000,
            max_daily_requests=50,
            max_run_seconds=180,
            python_sandbox_url=os.environ["PYTHON_SANDBOX_URL"],
            python_sandbox_token_file=Path(os.environ["PYTHON_SANDBOX_TOKEN_FILE"]),
        ),
        chat_factory=lambda cfg, key: OpenAIChat(cfg, key, transport=REC),
    )


def init():
    assert not DATA.exists(), "Never overwrite a prior benchmark dataset"
    RAW.mkdir(parents=True, exist_ok=True)
    s = services()
    lib = Library(s)
    owner = create_user(
        s.db,
        "qa-owner@masar.invalid",
        secrets.token_urlsafe(32),
        "مالك اختبار",
        "owner",
    )
    filename = (
        "transcription_livre_sciences_math_3AS_v2.md"
        if SOURCE_PLAN.get("source_fixture") == "book-v2.md.gz.b64"
        else "transcription_livre_sciences_math_3AS.md"
    )
    p = ROOT / "private" / filename
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    p.write_bytes(load_fixture(REPO, SOURCE_PLAN))
    r = lib.upload(
        p,
        p.name,
        {
            "title": p.stem,
            "kind": "book",
            "subject": "mathematics",
            "tracks": ["technical_mathematics"],
            "content_type": "textbook",
        },
        owner,
    )
    lib.review(
        r["version_id"],
        owner,
        True,
        "Owner-approved isolated diagnostic test; selected source bytes unchanged.",
    )
    lib.publish(r["version_id"], owner)
    key = Path(os.environ["GEMINI_API_KEY_FILE"]).read_text().strip()
    assert 20 <= len(key) <= 256, "Missing/invalid secret file"
    common = {
        "provider": "google",
        "model": "gemini-3.5-flash-lite",
        "max_tokens": 6000,
        "max_context_chars": 60000,
        "temperature": 0.2,
        "timeout": 90,
    }
    teacher = ModelConfig.model_validate(
        common
        | {
            "protocol": "openai",
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "main_max_rounds": 4,
        }
    ).model_dump()
    router = ModelConfig.model_validate(
        common
        | {
            "protocol": "google",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "temperature": 0,
            "selector_enabled": True,
            "selector_max_sources": 3,
        }
    ).model_dump()
    tid, sid = uid("gemini_teacher"), uid("gemini_router")
    s.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (tid, "agent", js(teacher), s.vault.encrypt(key), time.time()),
    )
    s.db.execute("INSERT INTO active_models VALUES('agent',?)", (tid,))
    s.db.execute(
        "INSERT INTO context_selectors VALUES(?,?,?,?)",
        (sid, js(router), s.vault.encrypt(key), time.time()),
    )
    s.db.execute("INSERT INTO active_selector VALUES(1,?)", (sid,))
    user_id = create_user(
        s.db, "qa-student@masar.invalid", secrets.token_urlsafe(32), "طالب اختبار"
    )
    user = select_track(
        s.db,
        s.db.one("SELECT * FROM users WHERE id=?", (user_id,)),
        "technical_mathematics",
    )
    cid = uid("qa_chat")
    now = time.time()
    s.db.execute(
        "INSERT INTO conversations(id,user_id,title,created_at,updated_at,study_subject) VALUES(?,?,?,?,?,?)",
        (cid, user_id, "محادثة رياضيات مطولة", now, now, "mathematics"),
    )
    index, mapping = build_catalog(s, study_scope=StudyScope(s.db, user, cid))
    write(ROOT / "mathematics-catalog.json", {"index": index, "mapping": mapping})
    config = {
        "tested_commit": os.environ.get("GITHUB_SHA", "local-offline-test"),
        "isolation": "fresh disposable GitHub runner database; production authenticated Docker broker; no deployment or application fixes",
        "user_id": user_id,
        "owner_id": owner,
        "chat_id": cid,
        "document": r,
        "catalog": {
            "entries": len(mapping),
            "chars": len(index),
            "sha256": hashlib.sha256(index.encode()).hexdigest(),
        },
        "teacher": teacher,
        "router": router,
        "max_run_seconds": 180,
        "request_cap": CAP,
        "reported_input_soft_stop": INPUT_CAP,
        "python_runtime": "production Docker broker; fresh no-network container per call",
        "source_preparation": SOURCE_PLAN.get(
            "source_preparation", "Original math Markdown byte-for-byte unchanged"
        ),
        "source_fixture": SOURCE_PLAN.get("source_fixture", "book.md.gz.b64"),
        "source_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
    }
    write(ROOT / "configuration.json", config)
    write(RAW / "cases.json", CASES)
    flush()
    s.close()
    print(
        js(
            {
                "initialized": True,
                "catalog": config["catalog"],
                "questions": len(CASES),
                "source_warnings": r.get("warnings"),
            }
        ),
        flush=True,
    )


async def run(limit, resume_429=False):
    cfg = json.loads((ROOT / "configuration.json").read_text())
    LEDGER.extend(json.loads((RAW / "requests.json").read_text()))
    AUDITS.extend(
        json.loads((ROOT / "router_audit.json").read_text())
        if (ROOT / "router_audit.json").exists()
        else []
    )
    TOOLS.extend(
        json.loads((RAW / "tool-audit.json").read_text())
        if (RAW / "tool-audit.json").exists()
        else []
    )
    results = (
        json.loads((RAW / "results.json").read_text())
        if (RAW / "results.json").exists()
        else []
    )
    resumed_case, previous = None, None
    if resume_429:
        resumed_case, delay = rate_limit_resume(results, LEDGER)
        if resumed_case > limit:
            raise ValueError("Resume case exceeds requested limit")
        previous = results[-1]
        # Explicit command authorizes exactly one retry, not an automatic provider retry.
        # Keep earlier request ledger/unknown usage; the 128/2.5M total guards remain.
        await asyncio.sleep(delay)
    s = services()
    s.selector_transport = REC
    engine = AgentEngine(s)
    user = s.db.one("SELECT * FROM users WHERE id=?", (cfg["user_id"],))
    try:
        for case in CASES:
            if (
                case["number"] <= len(results) and case["number"] != resumed_case
            ) or case["number"] > limit:
                continue
            if (
                len(LEDGER) >= CAP
                or sum(e.get("input_tokens") or 0 for e in LEDGER) >= INPUT_CAP
            ):
                break
            retry = case["number"] == resumed_case
            if retry:
                latest = s.db.one(
                    "SELECT id,content FROM messages WHERE conversation_id=? AND role='user' AND active=1 ORDER BY created_at DESC LIMIT 1",
                    (cfg["chat_id"],),
                )
                failed = s.db.one(
                    "SELECT message_id FROM agent_runs WHERE id=? AND user_id=? AND conversation_id=?",
                    (previous["run_id"], user["id"], cfg["chat_id"]),
                )
                if (
                    not latest
                    or not failed
                    or latest["id"] != failed["message_id"]
                    or latest["content"] != case["question"]
                ):
                    raise ValueError(
                        "Resume requires the original latest active student request"
                    )
            rid = engine.enqueue(cfg["chat_id"], user, case["question"], retry=retry)
            job = engine.claim()
            assert job["id"] == rid
            CURRENT.set(
                {
                    "case_number": case["number"],
                    "case_id": case["id"],
                    "subject": case["subject"],
                    "run_id": rid,
                }
            )
            started = time.monotonic()
            print(js(scrub({"start": case["id"]})), flush=True)
            await engine.process(job)
            await REC.drain()
            state = s.db.one(
                "SELECT status,error,steps,tool_calls FROM agent_runs WHERE id=?",
                (rid,),
            )
            reply = s.db.one(
                "SELECT id,content,blocks,sources FROM messages WHERE conversation_id=? AND role='assistant' AND active=1 AND created_at>=? ORDER BY created_at DESC LIMIT 1",
                (job["conversation_id"], job["created_at"]),
            )
            science = s.db.rows(
                "SELECT id,tool,inputs,output FROM scientific_results WHERE run_id=?",
                (rid,),
            )
            usage = s.db.rows(
                "SELECT feature,model,input_tokens,output_tokens,cached_tokens,status FROM model_usage WHERE run_id=? ORDER BY id",
                (rid,),
            )
            events = s.db.rows(
                "SELECT type,payload FROM run_events WHERE run_id=? ORDER BY id", (rid,)
            )
            notes = s.db.rows(
                "SELECT category,content,status,origin,message_id FROM learning_notes WHERE user_id=? ORDER BY created_at",
                (user["id"],),
            )
            out = {
                **case,
                "run_id": rid,
                **state,
                "duration_seconds": round(time.monotonic() - started, 2),
                "reply": reply,
                "science": science,
                "platform_usage": usage,
                "events": events,
                "notes": notes,
            }
            if retry:
                out["previous_attempts"] = [previous]
                results[-1] = out
            else:
                results.append(out)
            write(RAW / "results.json", results)
            requests = [e for e in LEDGER if e["run_id"] == rid]
            per_stage = {
                stage: {
                    "calls": sum(e["stage"] == stage for e in requests),
                    "input": sum(
                        e.get("input_tokens") or 0
                        for e in requests
                        if e["stage"] == stage
                    ),
                    "output": sum(
                        e.get("output_tokens") or 0
                        for e in requests
                        if e["stage"] == stage
                    ),
                    "usage_unknown": sum(
                        e.get("input_tokens") is None or e.get("output_tokens") is None
                        for e in requests
                        if e["stage"] == stage
                    ),
                }
                for stage in sorted({e["stage"] for e in requests})
            }
            print(
                js(
                    scrub(
                        {
                            "done": case["id"],
                            **state,
                            "tokens": per_stage,
                            "api_calls": [
                                {
                                    "n": e["request_number"],
                                    "s": e["stage"],
                                    "i": e.get("input_tokens"),
                                    "o": e.get("output_tokens"),
                                    "cache": e.get("cached_tokens"),
                                    "think": e.get("thinking_tokens"),
                                    "http": e.get("http_status"),
                                }
                                for e in requests
                            ],
                        }
                    )
                ),
                flush=True,
            )
            if (
                any(e.get("http_status") in (401, 403, 429) for e in requests)
                or sum(
                    e.get("http_status") == 200
                    and (
                        e.get("input_tokens") is None or e.get("output_tokens") is None
                    )
                    for e in LEDGER
                )
                >= 2
            ):
                print(
                    js(
                        {
                            "stopped": "provider_authorization_quota_or_unknown_usage",
                            "case": case["id"],
                        }
                    ),
                    flush=True,
                )
                break
            if len(results) >= 2 and all(
                x["error"] and str(x["error"]).startswith("NETWORK")
                for x in results[-2:]
            ):
                break
    finally:
        await REC.drain()
        s.close()


def preflight():
    from bac.science.python_runner import PythonRunner

    settings = Settings(
        python_sandbox_url=os.environ["PYTHON_SANDBOX_URL"],
        python_sandbox_token_file=Path(os.environ["PYTHON_SANDBOX_TOKEN_FILE"]),
    )
    result = PythonRunner(settings).execute(
        {
            "code": 'import sympy as sp\nx=sp.symbols("x")\nemit("derivative",str(sp.diff(x**3-3*x,x)))\ncheck("identity",bool(sp.diff(x**3-3*x,x)==3*x**2-3))',
            "inputs": {},
        }
    )
    write(ROOT / "runtime-preflight.json", result)
    assert (
        result.get("status") == "computed"
        and result.get("outputs", {}).get("derivative") == "3*x**2 - 3"
        and result.get("checks", [{}])[0].get("status") == "passed"
    ), "REAL_DOCKER_SANDBOX_PREFLIGHT_FAILED"
    assert (
        result.get("limits", {}).get("isolation")
        == "fresh_container_no_network_no_host_mounts"
    )
    print(
        "Authenticated Docker Python preflight passed; zero provider requests",
        flush=True,
    )


def install_audit_hooks():
    # CLI-only: importing this module in the normal test suite must not mutate bac.
    FullIndexCoordinator.__init__ = audited_init
    Tools.execute = observed_execute
    Tools.answer = observed_answer


if __name__ == "__main__":
    install_audit_hooks()
    command = sys.argv[1]
    if command == "preflight":
        preflight()
    elif command == "init":
        init()
    elif command in {"run", "resume-429"}:
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 24
        assert 1 <= limit <= 24
        asyncio.run(run(limit, resume_429=command == "resume-429"))
        results = (
            json.loads((RAW / "results.json").read_text())
            if (RAW / "results.json").exists()
            else []
        )
        if len(results) < limit:
            raise SystemExit(2)
    else:
        raise SystemExit(
            "Use preflight, init, run [1..24], or explicit one-time resume-429 [1..24]"
        )
