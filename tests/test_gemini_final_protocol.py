"""Explicit offline wire-protocol regressions; NOT live Gemini acceptance."""

import json
from dataclasses import replace
import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from bac.agent.engine import AgentEngine
from bac.agent.provider import OpenAIChat
from bac.agent.provider_errors import provider_diagnostic, safe_provider_diagnostic
from bac.agent.feedback import tool_feedback
from bac.agent.tools import Tools
from bac.core.activity import run_activity, PUBLIC_EVENTS
from bac.core.db import js
from bac.api.main import create_app
from bac.ops.diagnostics import diagnose_run, safe_diagnostic
from tests.test_agent import chat_and_config
from tests.test_api import login
from tests.test_gemini_compat import BASE, MODEL, SIGNATURE, call, response, sse
from tests.grounding_fixture import publish_reference
from tests.test_grounding_recovery import reply


def set_google(s):
    s.db.execute(
        "UPDATE model_configs SET config=? WHERE id=(SELECT config_id FROM active_models WHERE slot='agent')",
        (js({"base_url": BASE, "model": MODEL}),),
    )


def batch(*calls):
    return sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": i, **c} for i, c in enumerate(calls)]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        }
    )


def install(s, handler):
    s.chat_factory = lambda cfg, key: OpenAIChat(
        cfg, key, transport=httpx.MockTransport(handler)
    )


def status(s, rid):
    return s.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]


class LastRound(AgentEngine):
    round = 0

    def remaining_time(self, deadline):
        self.round += 1
        return 19 if self.round == 1 else 1


@pytest.mark.asyncio
@pytest.mark.parametrize("google", [True, False])
async def test_final_manifest_is_stable_only_for_google_with_force_and_execution_policy_preserved(
    services, google
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    if google:
        set_google(services)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        names = {x["function"]["name"] for x in body["tools"]}
        assert "save_teaching_material" not in names  # original student role scope
        if len(requests) == 1:
            return response("get_section", {"node_id": node})
        assert body["tool_choice"] == {
            "type": "function",
            "function": {"name": "render_answer"},
        }
        assert (
            "FINAL ROUND: only render_answer is allowed"
            in body["messages"][1]["content"]
        )
        assert any(
            m["role"] == "tool" and node in m["content"] for m in body["messages"]
        )
        if google:
            assert body["tools"] == requests[0]["tools"]
            # Fake Gemini explicitly rejects the old missing-history declaration layout.
            history = [c for m in body["messages"] for c in m.get("tool_calls", [])]
            if any(c["function"]["name"] not in names for c in history):
                return httpx.Response(
                    400,
                    json={
                        "error": {
                            "message": "Missing function declaration for prior call"
                        }
                    },
                )
            assert (
                history[0]["extra_content"]["google"]["thought_signature"] == SIGNATURE
            )
        else:
            assert names == {"render_answer"}
        return response("render_answer", reply(node))

    install(services, handler)
    engine = LastRound(services)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    assert status(services, rid) == "COMPLETED" and len(requests) == 2


@pytest.mark.asyncio
async def test_google_full_final_manifest_does_not_authorize_additional_execution(
    services,
):
    user, chat = chat_and_config(services)
    set_google(services)
    requests = []
    engine = LastRound(services)
    engine.round = 1  # final from the first round

    def handler(request):
        requests.append(request)
        assert "search_library" in {
            x["function"]["name"] for x in json.loads(request.content)["tools"]
        }
        return response("search_library", {"query": "القذف"})

    install(services, handler)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    report = diagnose_run(services.db)
    assert status(services, rid) == "FAILED"
    assert report["error"] == "FINAL_ANSWER_REQUIRED" and report["tool_calls"] == 0
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_read_and_terminal_render_same_batch_requires_another_model_turn(
    services,
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    set_google(services)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return batch(
                call("get_section", {"node_id": node}, "read"),
                call("render_answer", reply(node), "finish"),
            )
        replies = [m for m in body["messages"] if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in replies] == ["read", "finish"]
        assert "Render the answer alone" in replies[-1]["content"]
        return response("render_answer", reply(node))

    install(services, handler)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    assert status(services, rid) == "COMPLETED" and len(requests) == 2
    assert services.db.one(
        "SELECT 1 FROM run_events WHERE run_id=? AND type='answer_rejected'", (rid,)
    )


@pytest.mark.asyncio
async def test_same_batch_source_read_cannot_credit_teacher_material_before_model_sees_it(
    services,
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    services.db.execute("UPDATE users SET role='teacher' WHERE id=?", (user["id"],))
    user = services.db.one("SELECT * FROM users WHERE id=?", (user["id"],))
    set_google(services)
    material = {
        "kind": "lesson_plan",
        "title": "مسودة توضيح الحركة",
        "answer": reply(node),
    }
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return batch(
                call("get_section", {"node_id": node}, "read"),
                call("save_teaching_material", material, "save"),
            )
        if len(requests) == 2:
            assert (
                services.db.one("SELECT count(*) AS n FROM teaching_materials")["n"]
                == 0
            )
            assert "REFERENCE_READ_REQUIRED" in body["messages"][-1]["content"]
            return response("save_teaching_material", material)
        return response("render_answer", reply(node))

    install(services, handler)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "حضّر درس القذف")
    await engine.process(engine.claim())
    assert status(services, rid) == "COMPLETED" and len(requests) == 3
    assert services.db.one("SELECT count(*) AS n FROM teaching_materials")["n"] == 1


@pytest.mark.asyncio
async def test_private_image_user_message_follows_all_parallel_tool_replies(
    services, monkeypatch
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    set_google(services)
    original = Tools.execute

    def execute(self, name, args):
        result = original(self, name, args)
        if name == "get_section" and "error" not in result:
            # Offline pixel transport fixture; real read and actual provenance remain required.
            self.pending_source = ("synthetic-model-only-pixels", b"synthetic-JPEG")
        return result

    monkeypatch.setattr(Tools, "execute", execute)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return batch(
                call("get_section", {"node_id": node}, "read"),
                call("list_my_notes", {}, "notes"),
            )
        index = next(i for i, m in enumerate(body["messages"]) if m.get("tool_calls"))
        assert [m["role"] for m in body["messages"][index + 1 :]] == [
            "tool",
            "tool",
            "user",
        ]
        assert body["messages"][-1]["content"][1]["type"] == "image_url"
        return response("render_answer", reply(node))

    install(services, handler)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    assert status(services, rid) == "COMPLETED" and len(requests) == 2
    stored = js(services.db.rows("SELECT * FROM run_events"))
    assert "synthetic-model-only-pixels" not in stored and "data:image" not in stored


@pytest.mark.asyncio
async def test_paused_google_search_keeps_manifest_but_has_paired_unavailable_event_and_no_execution(
    services,
):
    user, chat = chat_and_config(services)
    set_google(services)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        step = len(requests)
        assert "search_library" in {x["function"]["name"] for x in body["tools"]}
        if step < 4:
            return response("search_library", {"query": "missing topic " + str(step)})
        assert (
            json.loads(body["messages"][-1]["content"])["error"] == "RETRIEVAL_STOPPED"
        )
        return response(
            "render_answer",
            {
                "response_kind": "clarification",
                "blocks": [{"type": "text", "text": "ما الفقرة التي تريد فهمها؟"}],
            },
        )

    install(services, handler)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح الدرس")
    await engine.process(engine.claim())
    assert status(services, rid) == "COMPLETED" and len(requests) == 4
    assert (
        services.db.one("SELECT tool_calls FROM agent_runs WHERE id=?", (rid,))[
            "tool_calls"
        ]
        == 2
    )
    ends = [
        json.loads(e["payload"])["success"]
        for e in services.db.rows(
            "SELECT payload FROM run_events WHERE run_id=? AND type='tool_end' ORDER BY id",
            (rid,),
        )
    ]
    assert ends == [True, True, False]
    assert not any(
        i["state"] == "running"
        for i in run_activity(
            services.db, services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
        )["items"]
    )


@pytest.mark.parametrize(
    "message,hint",
    [
        ("Function call is missing thought_signature", "THOUGHT_SIGNATURE_MISSING"),
        ("Invalid thought signature", "THOUGHT_SIGNATURE_REJECTED"),
        ("Function declaration not found for call", "TOOL_DECLARATION_MISMATCH"),
        (
            "Function response must match the previous function call",
            "TOOL_HISTORY_REJECTED",
        ),
        ("Invalid tool_choice.allowed_function_names", "TOOL_CHOICE_REJECTED"),
        ("Invalid parameters schema in tool", "TOOL_SCHEMA_REJECTED"),
        ("Invalid message role", "MESSAGE_ROLE_REJECTED"),
        ("Input token count too high", "PROVIDER_CONTEXT_REJECTED"),
        ("Unsupported image MIME type", "MEDIA_INPUT_REJECTED"),
        ("Unrecognized private reason", "REQUEST_INVALID_UNKNOWN"),
    ],
)
def test_error_hints_are_fixed_classifications_never_raw_provider_text(message, hint):
    payload = {
        "error": {
            "status": "INVALID_ARGUMENT",
            "message": message + " PRIVATE KEY / PRIVATE BOOK",
        }
    }
    d = provider_diagnostic(400, payload, {})
    assert d["hint"] == hint and d["status"] == "INVALID_ARGUMENT"
    assert "PRIVATE" not in js(d) and message not in js(d)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["http", "sse", "json", "oversize", "non-json"])
async def test_provider_error_storage_cli_activity_and_exports_never_reveal_error_body(
    services, mode
):
    user, chat = chat_and_config(services)
    set_google(services)
    requests = []
    error = {
        "error": {
            "code": 400,
            "status": "INVALID_ARGUMENT",
            "message": "Function declaration not found for PRIVATE BOOK with PRIVATE KEY",
            "details": [{"private": SIGNATURE}],
        }
    }

    def handler(request):
        requests.append(request)
        if mode == "sse":
            return sse(error)
        if mode == "json":
            return httpx.Response(200, json=error)
        if mode == "oversize":
            return httpx.Response(400, content=js(error).encode() + b" " * 20000)
        if mode == "non-json":
            return httpx.Response(400, text="PRIVATE KEY in HTML")
        return httpx.Response(400, json=error)

    install(services, handler)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    report = diagnose_run(services.db)
    assert status(services, rid) == "FAILED" and report["error"] == "HTTP_400"
    assert (
        len(requests) == 1 and len(services.db.rows("SELECT * FROM model_usage")) == 1
    )
    diag = report["provider_diagnostics"][0]
    assert diag["hint"] == (
        "REQUEST_INVALID_UNKNOWN"
        if mode in {"oversize", "non-json"}
        else "TOOL_DECLARATION_MISMATCH"
    )
    assert diag["declared_tool_count"] > 0 and diag["prior_tool_calls"] == 0
    assert "provider_diagnostic" not in PUBLIC_EVENTS
    stored = js(services.db.rows("SELECT * FROM run_events"))
    assert "PRIVATE" not in stored and SIGNATURE not in stored
    assert "PRIVATE" not in js(report) and SIGNATURE not in js(report)
    client = TestClient(create_app(services))
    login(client, "student@example.com")
    public = [
        client.get("/api/conversations/" + chat).json(),
        client.get("/api/conversations/" + chat + "/export").json(),
        client.get("/api/privacy/export").json(),
        client.get("/api/runs/" + rid + "/events").text,
    ]
    for item in public:
        text = js(item)
        assert "PRIVATE" not in text and SIGNATURE not in text
        assert "provider_diagnostics" not in text and diag["hint"] not in text


def test_operator_report_resanitizes_even_tampered_stored_provider_payload(services):
    user, chat = chat_and_config(services)
    rid = AgentEngine(services).enqueue(chat, user, "question")
    services.db.execute(
        "UPDATE agent_runs SET status='FAILED',error='HTTP_400' WHERE id=?", (rid,)
    )
    services.db.execute(
        "INSERT INTO run_events(run_id,type,payload,created_at) VALUES(?,?,?,0)",
        (
            rid,
            "provider_diagnostic",
            js(
                {
                    "status": "PRIVATE",
                    "hint": "PRIVATE",
                    "forced_final": "PRIVATE",
                    "http_status": "PRIVATE",
                    "prior_tool_calls": "PRIVATE",
                    "signed_prior_tool_calls": True,
                    "declared_tool_count": -1,
                    "missing_declaration_count": 10001,
                    "raw": "PRIVATE",
                }
            ),
        ),
    )
    report = diagnose_run(services.db)
    assert "PRIVATE" not in js(report)
    assert report["provider_diagnostics"][0] == safe_provider_diagnostic({})


@pytest.mark.parametrize(
    "code,expected",
    [
        (404, "SOURCE_UNAVAILABLE"),
        (403, "SOURCE_PERMISSION_DENIED"),
        (409, "SOURCE_NOT_READY"),
    ],
)
def test_source_failures_have_fixed_diagnostic_category_without_details(code, expected):
    d = safe_diagnostic(
        "get_section",
        tool_feedback("get_section", HTTPException(code, "PRIVATE source data")),
    )
    assert d["code"] == expected and d["stage"] == "review" and "PRIVATE" not in js(d)


@pytest.mark.asyncio
async def test_oversized_read_is_not_credited_and_has_actionable_safe_diagnostic(
    services,
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    set_google(services)
    services.settings = replace(services.settings, max_tool_chars=1000)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        step = len(requests)
        if step == 1:
            return response("get_section", {"node_id": node})
        if step == 2:
            assert (
                json.loads(body["messages"][-1]["content"])["error"]
                == "TOOL_RESULT_EXCEEDS_BUDGET"
            )
            return response("render_answer", reply(node))
        assert "Citation was not actually loaded" in body["messages"][-1]["content"]
        return response(
            "render_answer",
            {
                "response_kind": "clarification",
                "blocks": [{"type": "text", "text": "ما الفقرة التي تريد فهمها؟"}],
            },
        )

    install(services, handler)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    assert status(services, rid) == "COMPLETED" and len(requests) == 3
    diagnostics = diagnose_run(services.db, rid)["diagnostics"]
    assert any(d["code"] == "TOOL_RESULT_EXCEEDS_BUDGET" for d in diagnostics)
    assert any(d["code"] == "TOOL_RESULT_EXCEEDS_BUDGET" for d in diagnostics)
    assert not services.db.rows("SELECT * FROM loaded_context")
    end = services.db.one(
        "SELECT payload FROM run_events WHERE run_id=? AND type='tool_end'", (rid,)
    )
    assert json.loads(end["payload"])["success"] is False


@pytest.mark.asyncio
async def test_provider_diagnostic_captures_only_final_request_topology_after_real_read(
    services,
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    set_google(services)
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return response("get_section", {"node_id": node})
        return httpx.Response(
            400,
            json={
                "error": {
                    "status": "INVALID_ARGUMENT",
                    "message": "Function response rejected PRIVATE BOOK / PRIVATE KEY "
                    + SIGNATURE,
                }
            },
        )

    install(services, handler)
    engine = LastRound(services)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    report = diagnose_run(services.db)
    assert status(services, rid) == "FAILED" and report["model_requests"] == 2
    diag = report["provider_diagnostics"][0]
    assert diag["hint"] == "TOOL_HISTORY_REJECTED" and diag["forced_final"] is True
    assert diag["prior_tool_calls"] == diag["signed_prior_tool_calls"] == 1
    assert diag["missing_declaration_count"] == 0 and diag["declared_tool_count"] > 1
    assert (
        node not in js(report)
        and SIGNATURE not in js(report)
        and "PRIVATE" not in js(report)
    )
    stored = js(services.db.rows("SELECT * FROM run_events"))
    assert "PRIVATE" not in stored and SIGNATURE not in stored


@pytest.mark.parametrize(
    "code",
    [
        "SOURCE_EXCEEDS_TOOL_BUDGET",
        "ATOMIC_BUNDLE_EXCEEDS_TOOL_BUDGET",
        "ATOMIC_BUNDLE_REQUIRED",
        "RETRIEVAL_STOPPED",
    ],
)
def test_safe_source_budget_codes_are_known_without_raw_source_fields(code):
    d = safe_diagnostic(
        "get_section",
        {
            "error": code,
            "node_id": "PRIVATE",
            "children": ["PRIVATE"],
            "instruction": "PRIVATE",
        },
    )
    assert d["code"] == code and "PRIVATE" not in js(d)


def test_wrong_source_reader_reports_kind_mismatch_without_disclosing_kind():
    d = safe_diagnostic(
        "get_lesson_full",
        tool_feedback(
            "get_lesson_full", ValueError("Requested node is not a PRIVATE kind")
        ),
    )
    assert d["code"] == "SOURCE_KIND_MISMATCH" and "PRIVATE" not in js(d)
