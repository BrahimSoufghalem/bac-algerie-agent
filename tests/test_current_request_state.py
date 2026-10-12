"""Offline regressions for the observed failure paths, not live model-quality scores."""

import json
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from bac.agent.engine import AgentEngine
from bac.agent.full_index import (
    FullIndexCoordinator,
    build_catalog,
    call_router_llm,
    ROUTE_SYSTEM,
)
from bac.agent.provider import ModelError, OpenAIChat
from bac.agent.anthropic import AnthropicChat
from bac.agent.provider_errors import (
    provider_diagnostic,
    safe_provider_diagnostic,
    request_topology,
)
from bac.agent.session_state import (
    session_summary,
    available_attachments,
    missing_student_attachment,
    MAX_SUMMARY_CHARS,
)
from bac.agent.tools import Tools
from bac.core.auth import create_user
from bac.core.config import Settings
from bac.core.db import js, uid
from bac.core.services import Services
from bac.learning.private import PrivateFiles


@pytest.fixture
def state_services(tmp_path):
    s = Services(
        replace(Settings(), data_dir=tmp_path / "data", max_daily_requests=100)
    )
    yield s
    s.close()


def setup(s, email="student-state@example.com"):
    id_ = create_user(s.db, email, "Strong-password-123", "Student")
    s.db.execute(
        "UPDATE users SET study_track='experimental_sciences' WHERE id=?", (id_,)
    )
    chat, cfg = uid("chat"), uid("cfg")
    s.db.execute(
        "INSERT INTO conversations(id,user_id,title,created_at,updated_at,study_subject) VALUES(?,?,?,?,?,?)",
        (chat, id_, "State", time.time(), time.time(), "mathematics"),
    )
    s.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            cfg,
            "agent",
            js(
                {
                    "base_url": "https://example.org/v1",
                    "model": "offline",
                    "max_context_chars": 60000,
                }
            ),
            s.vault.encrypt("NOT-A-REAL-API-KEY"),
            time.time(),
        ),
    )
    s.db.execute("INSERT OR REPLACE INTO active_models VALUES(?,?)", ("agent", cfg))
    return s.db.one("SELECT * FROM users WHERE id=?", (id_,)), chat


def publish(s, user, text, parent=None, version=None):
    if not version:
        doc, version = uid("doc"), uid("version")
        s.db.execute(
            "INSERT INTO documents(id,title,kind,subject,track,source,status,published_version,owner_id,created_at,metadata) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                doc,
                "Offline mathematics",
                "book",
                "mathematics",
                "experimental_sciences",
                "owner",
                "ACTIVE",
                version,
                user["id"],
                time.time(),
                js({"content_type": "textbook", "tracks": ["experimental_sciences"]}),
            ),
        )
        s.db.execute(
            "INSERT INTO versions(id,document_id,sequence,bookforge_id,status,created_at) VALUES(?,?,?,?,?,?)",
            (version, doc, 1, "offline", "PUBLISHED", time.time()),
        )
    else:
        doc = s.db.one("SELECT document_id FROM versions WHERE id=?", (version,))[
            "document_id"
        ]
    node, path = uid("node"), "controlled/" + uid("body") + ".md"
    s.store.write(path, text.encode())
    s.db.execute(
        "INSERT INTO published_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            node,
            version,
            doc,
            parent,
            "lesson",
            "Controlled reference",
            1,
            100,
            1,
            1,
            path,
            js(
                {
                    "summary": "current sufficient goal",
                    "covers": ["current sufficient goal"],
                    "content_chars": len(text),
                }
            ),
        ),
    )
    return node, version


def call(name, args):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": uid("call"),
                "type": "function",
                "function": {"name": name, "arguments": js(args)},
            }
        ],
    }


class Clarify:
    def __init__(self, capture=None):
        self.capture = capture

    async def stream(self, messages, tools):
        if self.capture:
            self.capture(messages)
        yield {
            "type": "result",
            "message": call(
                "render_answer",
                {
                    "response_kind": "clarification",
                    "blocks": [
                        {"type": "text", "text": "ما المعطيات التي تريد استعمالها؟"}
                    ],
                    "source_ids": [],
                },
            ),
        }


def native_response(name, ids):
    return httpx.Response(
        200,
        json={
            "candidates": [
                {
                    "finishReason": "STOP",
                    "content": {
                        "parts": [
                            {
                                "functionCall": {
                                    "name": name,
                                    "args": {
                                        "status": "read",
                                        "goals": [
                                            {
                                                "goal": "current sufficient goal",
                                                "ids": ids,
                                            }
                                        ],
                                        "question": "",
                                    },
                                }
                            }
                        ]
                    },
                }
            ],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 10},
        },
    )


def selector(s):
    id_ = uid("selector")
    cfg = {
        "provider": "google",
        "protocol": "google",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-3.5-flash-lite",
        "selector_enabled": True,
    }
    s.db.execute(
        "INSERT INTO context_selectors VALUES(?,?,?,?)",
        (id_, js(cfg), s.vault.encrypt("NOT-A-REAL-KEY"), time.time()),
    )
    s.db.execute("INSERT OR REPLACE INTO active_selector VALUES(1,?)", (id_,))
    return s.db.one("SELECT * FROM context_selectors WHERE id=?", (id_,))


def test_legacy_env_character_cap_is_retired_not_replaced(monkeypatch):
    monkeypatch.setenv("MAX_CONTEXT_CHARS", "60000")
    assert Settings.from_env().max_context_chars == 0


def test_selected_full_reference_above_60000_is_lossless(state_services):
    s = state_services
    user, chat = setup(s)
    body = "Actual controlled mathematical prose. " * 2200
    node, _ = publish(s, user, body)
    s.settings = replace(s.settings, max_context_chars=60000)
    tools = Tools(s, user, chat)
    result = tools.load(node, full_context=True)
    assert (
        len(js(result)) > 60000 and result["content"] == body and "error" not in result
    )
    # Separate per-tool payload limits (including Python outputs) remain explicit.
    assert "error" in Tools(s, user, chat).load(node)


@pytest.mark.asyncio
@pytest.mark.parametrize("small", [False, True])
async def test_router_prefers_sufficient_part_and_can_deliver_large_selected_source(
    state_services, small
):
    s = state_services
    user, chat = setup(s)
    parent, version = publish(s, user, "Actual controlled prose. " * 3100)
    child, _ = publish(
        s, user, "Complete narrow current goal with all conditions.", parent, version
    )
    row = selector(s)
    _, mapping = build_catalog(s)
    target = child if small else parent
    alias = next(a for a, n in mapping.items() if n["id"] == target)

    def route(req):
        data = json.loads(req.content)
        assert "SMALLEST SUFFICIENT" in data["systemInstruction"]["parts"][0]["text"]
        return native_response("route_sections", [alias])

    s.selector_transport = httpx.MockTransport(route)
    engine = AgentEngine(s)
    rid = engine.enqueue(chat, user, "Explain the current sufficient goal")
    run = s.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    tools = Tools(s, user, chat, rid)
    result = await FullIndexCoordinator(s, row).prepare(
        run, tools, "Explain the current sufficient goal"
    )
    assert result["node"]["id"] == target and "error" not in result
    assert len(s.db.rows("SELECT * FROM loaded_context")) == 1
    if not small:
        assert len(js(result)) > 60000
    # This is a scripted route/policy regression, not proof of live semantic selection.


@pytest.mark.asyncio
async def test_failed_old_goal_is_labeled_history_and_current_goal_is_separate(
    state_services,
):
    s = state_services
    user, chat = setup(s)
    engine = AgentEngine(s)

    class Fail:
        async def stream(self, *args):
            raise ModelError("OFFLINE_FAILURE")
            yield

    s.chat_factory = lambda cfg, key: Fail()
    old = engine.enqueue(chat, user, "اشرح اشتقاق الدالة السابقة")
    await engine.process(engine.claim())
    seen = []
    s.chat_factory = lambda cfg, key: Clarify(seen.append)
    now = engine.enqueue(chat, user, "ننتقل الآن إلى الاحتمالات فقط")
    await engine.process(engine.claim())
    assert (
        s.db.one("SELECT status FROM agent_runs WHERE id=?", (now,))["status"]
        == "COMPLETED"
    )
    text = js(seen[0])
    assert "HISTORICAL user; attempt=FAILED" in text
    assert (
        seen[0][-1]["content"]
        == "[CURRENT STUDENT REQUEST]\nننتقل الآن إلى الاحتمالات فقط"
    )
    snapshot = json.loads(
        s.db.one(
            "SELECT payload FROM conversation_summaries WHERE conversation_id=?",
            (chat,),
        )["payload"]
    )
    entries = snapshot["summary"]["entries"]
    assert entries[0]["run_id"] == old and entries[0]["status"] == "FAILED"
    assert entries[-1]["run_id"] == now and entries[-1]["answer_message_id"]
    assert snapshot["message_provenance"][0]["question_sha256"]


@pytest.mark.parametrize(
    "question,expected",
    [
        ("صحح حلي في الصورة المرفقة", True),
        ("Explain this image", True),
        ("Corrige cette photo", True),
        ("ارسم صورة توضيحية للدالة", False),
        ("اشرح صورة من الكتاب", False),
        ("ارسم منحنى الدالة", False),
        ("لخص هذا الملف", True),
        ("Review this file", True),
        ("Lis le fichier joint", True),
        ("صحح حلي في الصورة المرفقة من الكتاب", True),
    ],
)
def test_attachment_gate_targets_student_input_not_book_images(question, expected):
    assert missing_student_attachment(question, []) is expected
    assert missing_student_attachment(question, [{"kind": "image"}]) is False


@pytest.mark.asyncio
async def test_missing_attachment_asks_without_router_or_model_call(state_services):
    s = state_services
    user, chat = setup(s)
    selector(s)

    def never(*args):
        raise AssertionError("No provider request for a known missing upload")

    s.selector_transport = httpx.MockTransport(never)
    s.chat_factory = never
    engine = AgentEngine(s)
    rid = engine.enqueue(chat, user, "صحح الحل في الصورة المرفقة")
    await engine.process(engine.claim())
    assert (
        s.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert not s.db.rows("SELECT * FROM model_usage")
    assert (
        "هل ترفقه"
        in s.db.one("SELECT content FROM messages WHERE role='assistant'")["content"]
    )


@pytest.mark.asyncio
async def test_available_own_attachment_is_inventory_only_and_revalidated(
    state_services,
):
    import io
    from PIL import Image

    s = state_services
    user, chat = setup(s)
    buf = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buf, format="PNG")
    upload = PrivateFiles(s).add(user, chat, "PRIVATE-IMAGE.png", buf.getvalue())
    seen = []
    s.chat_factory = lambda cfg, key: Clarify(seen.append)
    engine = AgentEngine(s)
    rid = engine.enqueue(chat, user, "صحح الحل في الصورة المرفقة")
    await engine.process(engine.claim())
    state = available_attachments(s, user, chat, rid)
    assert state == [{"id": upload["id"], "kind": "image", "pages": 1, "read": False}]
    assert "data:image" not in js(seen) and "PRIVATE-IMAGE" not in js(seen)
    other, _ = setup(s, "other-state@example.com")
    assert available_attachments(s, other, chat, rid) == []
    s.db.execute("UPDATE private_uploads SET expires_at=0 WHERE id=?", (upload["id"],))
    assert available_attachments(s, user, chat, rid) == []


@pytest.mark.asyncio
async def test_summary_is_bounded_traceable_and_scrubs_inactive_foreign_or_deleted_chat(
    state_services,
):
    s = state_services
    user, chat = setup(s)
    s.chat_factory = lambda cfg, key: Clarify()
    engine = AgentEngine(s)
    for i in range(16):
        engine.enqueue(chat, user, "طلب رقم " + str(i) + " " + "تفصيل " * 60)
        await engine.process(engine.claim())
    summary = session_summary(s.db, user["id"], chat)
    assert len(summary["entries"]) <= 12 and len(js(summary)) <= MAX_SUMMARY_CHARS
    entry = summary["entries"][-1]
    s.db.execute(
        "UPDATE messages SET active=0 WHERE id IN (?,?)",
        (entry["question_message_id"], entry["answer_message_id"]),
    )
    assert entry["question_message_id"] not in js(
        session_summary(s.db, user["id"], chat)
    )
    other, _ = setup(s, "foreign-memory@example.com")
    assert session_summary(s.db, other["id"], chat) == {}
    s.db.execute("DELETE FROM conversations WHERE id=?", (chat,))
    assert not s.db.one(
        "SELECT * FROM conversation_summaries WHERE conversation_id=?", (chat,)
    )


def test_diagnostics_keep_safe_vocabulary_paths_and_shape_not_secrets_or_arguments():
    body = {
        "messages": [
            {"role": "user", "content": "UNIQUE_PRIVATE_LESSON"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "PRIVATE-CALL",
                        "function": {"name": "run_python", "arguments": "PRIVATE-CODE"},
                        "extra_content": {
                            "google": {"thought_signature": "PRIVATE-SIGNATURE"}
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "PRIVATE-CALL",
                "content": "PRIVATE-RESULT",
            },
        ],
        "tools": [
            {
                "function": {
                    "name": "run_python",
                    "parameters": {
                        "type": "object",
                        "properties": {"code": {"type": "string"}},
                        "required": ["code"],
                    },
                }
            }
        ],
        "tool_choice": {"function": {"name": "render_answer"}},
        "max_tokens": 6000,
    }
    payload = {
        "error": {
            "status": "INVALID_ARGUMENT",
            "message": "Invalid function response PRIVATE-KEY UNIQUE_PRIVATE_LESSON https://private.invalid",
            "details": [
                {
                    "fieldViolations": [
                        {
                            "field": "contents[2].parts[0].functionResponse.name",
                            "description": "PRIVATE-TEXT",
                        }
                    ]
                }
            ],
        }
    }
    diagnostic = provider_diagnostic(400, payload, request_topology(body))
    assert diagnostic["error_message"] and "[redacted]" in diagnostic["error_message"]
    assert diagnostic["error_fields"] == ["contents[2].parts[0].functionResponse.name"]
    assert diagnostic["request_shape"]["message_count"] == 3
    assert diagnostic["request_shape"]["unpaired_tool_reply_count"] == 0
    assert "PRIVATE" not in js(diagnostic) and "private.invalid" not in js(diagnostic)
    assert safe_provider_diagnostic(diagnostic) == diagnostic
    assert (
        safe_provider_diagnostic(
            {
                "request_shape": {"protocol": []},
                "error_message": "PRIVATE",
                "error_fields": ["PRIVATE"],
            }
        )["error_message"]
        == "[redacted]"
    )
    for details in [None, "PRIVATE", {}, [None, {"fieldViolations": None}]]:
        assert "PRIVATE" not in js(
            provider_diagnostic(400, {"error": {"details": details}}, {})
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "anthropic", "google"])
async def test_each_provider_400_carries_bounded_redacted_shape_without_retry(protocol):
    requests = []

    def handler(req):
        requests.append(req)
        return httpx.Response(
            400,
            json={
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "Invalid message role PRIVATE-KEY",
                }
            },
        )

    transport = httpx.MockTransport(handler)
    with pytest.raises(ModelError) as caught:
        if protocol == "google":
            await call_router_llm(
                {
                    "protocol": "google",
                    "base_url": "https://generativelanguage.googleapis.com/v1beta",
                    "model": "gemini-3.5-flash-lite",
                },
                "PRIVATE-KEY",
                "policy",
                {"student_request": "PRIVATE-QUESTION"},
                {
                    "name": "route_sections",
                    "parameters": {"type": "object", "properties": {}},
                },
                transport=transport,
            )
        else:
            provider = (OpenAIChat if protocol == "openai" else AnthropicChat)(
                {"base_url": "https://example.org/v1", "model": "offline"},
                "PRIVATE-KEY",
                transport=transport,
            )
            async for _ in provider.stream(
                [{"role": "user", "content": "PRIVATE-QUESTION"}], []
            ):
                pass
    assert str(caught.value) == "HTTP_400" and len(requests) == 1
    assert caught.value.diagnostic["request_shape"]["protocol"] == protocol
    assert "PRIVATE" not in js(caught.value.diagnostic)


@pytest.mark.asyncio
async def test_minimal_unstructured_answer_repair_then_400_is_diagnosed_not_blindly_retried(
    state_services,
):
    s = state_services
    user, chat = setup(s)
    requests = []

    def handler(req):
        body = json.loads(req.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": "شرح غير معتمد دون قراءة",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                },
            )
        assert body["tool_choice"]["function"]["name"] == "render_answer"
        return httpx.Response(
            400,
            json={
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "Invalid message role PRIVATE-KEY",
                }
            },
        )

    s.chat_factory = lambda cfg, key: OpenAIChat(
        cfg, key, transport=httpx.MockTransport(handler)
    )

    class FinalSecond(AgentEngine):
        turn = 0

        def remaining_time(self, deadline):
            self.turn += 1
            return 100 if self.turn == 1 else 1

    engine = FinalSecond(s)
    rid = engine.enqueue(chat, user, "اشرح درس الاحتمالات UNIQUE_PRIVATE_QUESTION")
    await engine.process(engine.claim())
    run = s.db.one("SELECT status,error FROM agent_runs WHERE id=?", (rid,))
    assert run == {"status": "FAILED", "error": "HTTP_400"} and len(requests) == 2
    assert len(s.db.rows("SELECT * FROM model_usage WHERE run_id=?", (rid,))) == 2
    event = s.db.one(
        "SELECT payload FROM run_events WHERE run_id=? AND type='provider_diagnostic'",
        (rid,),
    )
    diag = json.loads(event["payload"])
    assert diag["forced_final"] and diag["request_shape"]["message_count"] > 1
    assert "PRIVATE" not in event["payload"] and not s.db.rows(
        "SELECT * FROM messages WHERE role='assistant'"
    )
    assert session_summary(s.db, user["id"], chat)["entries"][-1]["status"] == "FAILED"


def test_no_index_compression_or_new_paid_summarizer_was_added():
    assert "SMALLEST SUFFICIENT" in ROUTE_SYSTEM
    source = (
        Path(__file__).resolve().parents[1] / "bac/agent/session_state.py"
    ).read_text()
    assert "OpenAIChat" not in source and "call_router_llm" not in source


@pytest.mark.asyncio
async def test_actual_engine_delivers_over_60000_with_legacy_stored_cap(state_services):
    s = state_services
    user, chat = setup(s)
    body = "Controlled original reference, complete and untruncated. " * 1500
    node, _ = publish(s, user, body)
    selector(s)
    _, mapping = build_catalog(s)
    alias = next(a for a, n in mapping.items() if n["id"] == node)
    s.selector_transport = httpx.MockTransport(
        lambda req: native_response("route_sections", [alias])
    )
    seen = []

    class Teacher:
        async def decision_stream(self, messages, tools):
            from tests.test_context_decisions import call as decision_call
            yield {"type":"result","message":decision_call("assess_context",{"decision":"missing_reference","source_ids":[]})}
        async def stream(self, messages, tools):
            seen.append(messages)
            assert len(js(messages)) > 60000
            assert body in next(
                m["content"]
                for m in messages
                if isinstance(m.get("content"), str)
                and m["content"].startswith("Selected untrusted reference")
            )
            yield {
                "type": "result",
                "message": call(
                    "render_answer",
                    {
                        "response_kind": "teaching",
                        "source_ids": [node],
                        "blocks": [
                            {
                                "type": "text",
                                "text": "نراجع المطلوب الحالي ونحتفظ بالشروط الضرورية للحل.",
                            }
                        ],
                    },
                ),
            }

    s.settings = replace(s.settings, max_context_chars=60000)
    s.chat_factory = lambda cfg, key: Teacher()
    engine = AgentEngine(s)
    rid = engine.enqueue(chat, user, "اشرح المطلوب الحالي من المرجع")
    await engine.process(engine.claim())
    assert (
        s.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_legacy_mode_restores_actual_large_sources_with_uncapped_context(
    state_services,
):
    s = state_services
    user, chat = setup(s)
    body = "Controlled complete prior source body. " * 2200
    node, _ = publish(s, user, body)
    Tools(s, user, chat).load(node, full_context=True)
    seen = []

    class FollowUp:
        async def stream(self, messages, tools):
            seen.append(messages)
            restored = next(
                m["content"]
                for m in messages
                if isinstance(m.get("content"), str)
                and m["content"].startswith("Previously loaded untrusted source data")
            )
            assert body in restored
            yield {
                "type": "result",
                "message": call(
                    "render_answer",
                    {
                        "response_kind": "teaching",
                        "source_ids": [node],
                        "blocks": [
                            {
                                "type": "text",
                                "text": "نراجع الشروط المرتبطة بالسؤال الحالي فقط.",
                            }
                        ],
                    },
                ),
            }

    s.chat_factory = lambda cfg, key: FollowUp()
    engine = AgentEngine(s)
    rid = engine.enqueue(chat, user, "اشرح لي النقطة السابقة")
    await engine.process(engine.claim())
    assert (
        s.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert len(seen) == 1 and s.db.one(
        "SELECT 1 FROM run_events WHERE run_id=? AND type='source_reloaded'", (rid,)
    )


def test_legacy_assistant_trace_is_sanitized_before_summary_and_personal_export(
    state_services,
):
    s = state_services
    user, chat = setup(s)
    q, a = uid("msg"), uid("msg")
    hidden = "node_" + "a" * 32
    science = "science_" + "b" * 32
    s.db.execute(
        "INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,?,?,?)",
        (q, chat, "user", "Explain the prior equation", 1),
    )
    s.db.execute(
        "INSERT INTO messages(id,conversation_id,role,content,blocks,created_at) VALUES(?,?,?,?,?,?)",
        (
            a,
            chat,
            "assistant",
            "شرح. get_section /api/library/nodes/" + hidden,
            js(
                [
                    {"type": "equation", "latex": "x=1", "result_ids": [science]},
                    {
                        "type": "verification",
                        "result_id": science,
                        "result": {"tool": "calculate", "inputs": {}},
                    },
                ]
            ),
            2,
        ),
    )
    summary = session_summary(s.db, user["id"], chat)
    assert "x=1" in js(summary)
    assert (
        hidden not in js(summary)
        and science not in js(summary)
        and "get_section" not in js(summary)
    )
