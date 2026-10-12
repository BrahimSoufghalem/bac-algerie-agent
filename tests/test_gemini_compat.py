"""Offline transport fixtures, not live Google acceptance or educational certification."""

import json
import time
import httpx
import pytest
from bac.agent.compat import model_identity
from bac.agent.provider import OpenAIChat, ModelError
from bac.agent.engine import AgentEngine
from bac.agent.tools import Tools
from bac.core.db import js, uid
from bac.ops.diagnostics import diagnose_run
from tests.test_agent import chat_and_config
from tests.test_learning import setup_client
from tests.grounding_fixture import publish_reference

BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
MODEL = "gemini-3.5-flash-lite"
SIGNATURE = "opaque-fixture-token-NOT-real-model-thinking"


def sse(*chunks):
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text="".join("data: " + js(x) + "\n\n" for x in chunks) + "data: [DONE]\n\n",
    )


def call(name, args, id="read"):
    return {
        "id": id,
        "type": "function",
        "function": {"name": name, "arguments": js(args)},
        "extra_content": {
            "google": {
                "thought_signature": SIGNATURE,
                "thought_summary": "PRIVATE REASONING",
            },
            "other": "PRIVATE EXTRA",
        },
    }


def response(name, args):
    return sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, **call(name, args)}],
                        "reasoning_content": "PRIVATE REASONING",
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 8, "completion_tokens": 6}},
    )


@pytest.mark.parametrize(
    "base,expected",
    [
        (BASE, MODEL),
        (BASE + "chat/completions", MODEL),
        ("https://openrouter.ai/api/v1", "models/" + MODEL),
        ("https://fixture.invalid/v1", "models/" + MODEL),
    ],
)
def test_only_google_model_namespace_is_normalized(base, expected):
    assert model_identity(base, "models/" + MODEL) == expected


def test_google_listing_prefix_matches_without_generation_or_secret_output(services):
    client, headers, user = setup_client(services, "owner")
    requests = []

    def handler(request):
        requests.append((request.method, str(request.url)))
        return httpx.Response(200, json={"data": [{"id": "models/" + MODEL}]})

    services.connection_transport = httpx.MockTransport(handler)
    cfg = uid("cfg")
    services.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            cfg,
            "agent",
            js({"base_url": BASE, "model": MODEL}),
            services.vault.encrypt("private-key"),
            time.time(),
        ),
    )
    services.db.execute("INSERT INTO active_models VALUES(?,?)", ("agent", cfg))
    r = client.post(
        "/api/owner/models/agent/test", json={"confirm": True}, headers=headers
    )
    assert r.status_code == 200 and r.json()["model_advertised"] is True
    assert r.json()["generation_requests"] == 0
    assert requests == [("GET", BASE + "models")]
    assert "private-key" not in r.text


@pytest.mark.asyncio
async def test_fragmented_stream_preserves_only_opaque_signature_and_normalizes_request():
    def handler(request):
        assert json.loads(request.content)["model"] == MODEL
        return sse(
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "PRIVATE REASONING",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "a",
                                    "function": {
                                        "name": "get_section",
                                        "arguments": '{"node_',
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "function": {"arguments": 'id":"x"}'},
                                    "extra_content": call("unused", {})[
                                        "extra_content"
                                    ],
                                }
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    items = [
        x
        async for x in OpenAIChat(
            {"base_url": BASE, "model": "models/" + MODEL},
            "fixture-key",
            transport=httpx.MockTransport(handler),
        ).stream([], [])
    ]
    result = items[-1]["message"]["tool_calls"][0]
    assert result["extra_content"] == {"google": {"thought_signature": SIGNATURE}}
    assert result["function"]["arguments"] == '{"node_id":"x"}'
    assert "PRIVATE" not in js(items)


@pytest.mark.asyncio
async def test_json_response_preserves_signature_without_any_reasoning_text():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "reasoning_content": "PRIVATE REASONING",
                            "tool_calls": [call("get_section", {"node_id": "x"})],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
        )

    items = [
        x
        async for x in OpenAIChat(
            {"base_url": BASE, "model": MODEL},
            "fixture-key",
            transport=httpx.MockTransport(handler),
        ).stream([], [])
    ]
    assert (
        items[-1]["message"]["tool_calls"][0]["extra_content"]["google"][
            "thought_signature"
        ]
        == SIGNATURE
    )
    assert "PRIVATE" not in js(items)


@pytest.mark.asyncio
async def test_engine_forwards_real_received_signature_on_subsequent_tool_round_without_persisting_it(
    services,
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return response("get_section", {"node_id": node})
        assistant = next(
            m
            for m in body["messages"]
            if m["role"] == "assistant" and m.get("tool_calls")
        )
        assert assistant["tool_calls"][0]["extra_content"] == {
            "google": {"thought_signature": SIGNATURE}
        }
        assert "PRIVATE REASONING" not in js(body)
        return response(
            "render_answer",
            {
                "response_kind": "teaching",
                "source_ids": [node],
                "blocks": [
                    {
                        "type": "text",
                        "text": "نحلّل الحركة في اتجاهين مع إهمال مقاومة الهواء.",
                    }
                ],
            },
        )

    services.chat_factory = lambda cfg, key: OpenAIChat(
        {"base_url": BASE, "model": MODEL},
        "fixture-key",
        transport=httpx.MockTransport(handler),
    )
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert len(requests) == 2
    assert SIGNATURE not in js(services.db.rows("SELECT * FROM run_events"))
    assert SIGNATURE not in js(services.db.rows("SELECT * FROM messages"))


@pytest.mark.asyncio
async def test_plain_greeting_finishes_without_provider_or_optional_mode(
    services,
):
    user, chat = chat_and_config(services)
    requests = []

    def handler(request):
        requests.append(request)
        return response(
            "render_answer",
            {"blocks": [{"type": "text", "text": "أهلًا! كيف يمكنني مساعدتك؟"}]},
        )

    services.chat_factory = lambda cfg, key: OpenAIChat(
        {"base_url": BASE, "model": MODEL},
        "fixture-key",
        transport=httpx.MockTransport(handler),
    )
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "hi")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert not requests and not services.db.rows(
        "SELECT 1 FROM run_events WHERE type='answer_rejected'"
    )


@pytest.mark.parametrize(
    "question,args",
    [
        (
            "hi اشرح درس القذف",
            {"blocks": [{"type": "text", "text": "شرح من الذاكرة."}]},
        ),
        ("hi 2+2", {"blocks": [{"type": "text", "text": "أهلًا."}]}),
        ("hi", {"blocks": [{"type": "equation", "latex": "v=gt"}]}),
        ("hi", {"blocks": [{"type": "text", "text": "x" * 601}]}),
    ],
)
def test_greeting_inference_never_relaxes_teaching_or_bounded_social_guard(
    services, question, args
):
    user, chat = chat_and_config(services)
    rid = AgentEngine(services).enqueue(chat, user, question)
    tools = Tools(services, user, chat, rid)
    tools.question = tools.study_context = question
    with pytest.raises(ValueError):
        tools.answer(args)


@pytest.mark.asyncio
async def test_stream_error_is_fail_closed_and_never_prints_provider_error_body():
    def handler(request):
        return sse({"error": {"code": 404, "message": "PRIVATE KEY / MODEL TRACE"}})

    with pytest.raises(ModelError, match="^HTTP_404$"):
        _ = [
            x
            async for x in OpenAIChat(
                {"base_url": BASE, "model": MODEL},
                "fixture-key",
                transport=httpx.MockTransport(handler),
            ).stream([], [])
        ]


@pytest.mark.asyncio
async def test_oversized_opaque_metadata_is_not_silently_dropped():
    def handler(request):
        c = call("get_section", {"node_id": "x"})
        c["extra_content"]["google"]["thought_signature"] = "x" * 64001
        return sse(
            {
                "choices": [
                    {
                        "delta": {"tool_calls": [{"index": 0, **c}]},
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )

    with pytest.raises(ModelError, match="^PROVIDER_METADATA_TOO_LARGE$"):
        _ = [
            x
            async for x in OpenAIChat(
                {"base_url": BASE, "model": MODEL},
                "fixture-key",
                transport=httpx.MockTransport(handler),
            ).stream([], [])
        ]


def test_diagnostic_distinguishes_old_failed_run_from_new_saved_provider_config(
    services,
):
    user, chat = chat_and_config(services)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "PRIVATE QUESTION")
    services.db.execute(
        "UPDATE agent_runs SET status='FAILED',error='HTTP_404' WHERE id=?", (rid,)
    )
    assert diagnose_run(services.db)["uses_current_model_config"] is True
    cfg = uid("cfg")
    services.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            cfg,
            "agent",
            js({"base_url": BASE, "model": MODEL}),
            services.vault.encrypt("PRIVATE KEY"),
            time.time(),
        ),
    )
    services.db.execute(
        "UPDATE active_models SET config_id=? WHERE slot='agent'", (cfg,)
    )
    engine.enqueue(chat, user, "PRIVATE NEW QUESTION")
    report = diagnose_run(services.db)
    assert (
        report["uses_current_model_config"] is False
        and report["newer_run_exists"] is True
    )
    assert "PRIVATE" not in js(report) and cfg not in js(report)


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit_null", [False, True])
async def test_google_parallel_stream_calls_without_indices_keep_distinct_ids(explicit_null):
    def handler(request):
        chunk = {"choices": [{"delta": {"tool_calls": [
                call("calculate", {"expression": "8*2"}, "calc-x"),
                {"id": "calc-z", "type": "function", "function": {
                    "name": "calculate", "arguments": '{"expression":"10*2-5*2**2"}'}},
                {"id": "plot-v", "type": "function", "function": {
                    "name": "plot_function", "arguments": '{"expression":"10-10*t"}'}}
            ]}, "finish_reason": "tool_calls"}]}
        if explicit_null:
            for tool in chunk["choices"][0]["delta"]["tool_calls"]:
                tool["index"] = None
        return sse(chunk, {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 8}})
    items = [x async for x in OpenAIChat(
        {"base_url": BASE, "model": MODEL}, "fixture-key",
        transport=httpx.MockTransport(handler)).stream([], [])]
    calls = items[-1]["message"]["tool_calls"]
    assert [x["id"] for x in calls] == ["calc-x", "calc-z", "plot-v"]
    assert [x["function"]["name"] for x in calls] == ["calculate", "calculate", "plot_function"]
    assert [json.loads(x["function"]["arguments"]) for x in calls] == [
        {"expression": "8*2"}, {"expression": "10*2-5*2**2"}, {"expression": "10-10*t"}]
    assert calls[0]["extra_content"] == {"google": {"thought_signature": SIGNATURE}}
    assert "extra_content" not in calls[1]
    assert "PRIVATE REASONING" not in js(items)


@pytest.mark.asyncio
async def test_google_unindexed_ambiguous_fragment_fails_without_guessing():
    def handler(request):
        return sse(
            {"choices": [{"delta": {"tool_calls": [
                call("calculate", {}, "a"),
                {"id": "b", "function": {"name": "calculate", "arguments": "{}"}}
            ]}}]},
            {"choices": [{"delta": {"tool_calls": [{"function": {"arguments": "x"}}]}}]},
        )
    with pytest.raises(ModelError, match="AMBIGUOUS_TOOL_CALL_DELTA"):
        _ = [x async for x in OpenAIChat(
            {"base_url": BASE, "model": MODEL}, "fixture-key",
            transport=httpx.MockTransport(handler)).stream([], [])]


def test_google_plain_answer_wire_schema_does_not_mutate_or_relax_server_validation():
    from bac.agent.compat import google_answer_tools
    from bac.agent.models import PresentedAnswer
    from pydantic import ValidationError
    original = [{"type": "function", "function": {
        "name": "render_answer", "description": "Render", "parameters": PresentedAnswer.model_json_schema()}}]
    frozen = js(original)
    wire = google_answer_tools(original)
    assert js(original) == frozen
    assert "$defs" not in js(wire) and "discriminator" not in js(wire)
    assert "result" not in wire[0]["function"]["parameters"]["properties"]["blocks"]["items"]["properties"]
    with pytest.raises(ValidationError):
        PresentedAnswer.model_validate({"blocks": [{"type": "text", "latex": "v=gt"}]})
    with pytest.raises(ValidationError):
        PresentedAnswer.model_validate({"blocks": [{"type": "graph", "result_id": "x", "result": {}}]})


@pytest.mark.asyncio
async def test_google_working_round_keeps_auto_with_plain_answer_schema():
    from bac.agent.models import PresentedAnswer
    def handler(request):
        body = json.loads(request.content)
        assert "tool_choice" not in body
        assert "$defs" not in js(body["tools"])
        return response("render_answer", {"blocks": [{"type": "text", "text": "Hello"}]})
    tools = [{"type": "function", "function": {"name": "render_answer", "description": "Render", "parameters": PresentedAnswer.model_json_schema()}}]
    _ = [x async for x in OpenAIChat({"base_url": BASE, "model": MODEL}, "fixture-key", transport=httpx.MockTransport(handler)).stream([], tools)]
