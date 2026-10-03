"""Offline contract/permission/actual-read tests. Live quality has a separate report."""

import json, time
from dataclasses import replace
import httpx, pytest
from bac.agent.engine import AgentEngine
from bac.agent.selection import evaluate, selected_alias, focus, candidates
from bac.agent.provider import ModelError
from bac.agent.models import ModelConfig
from bac.agent.tools import Tools
from bac.core.db import uid, js
from bac.ops.diagnostics import diagnose_run
from tests.test_agent import chat_and_config
from tests.test_run_budget import call
from tests.test_grounding_recovery import reply
from tests.grounding_fixture import publish_reference
from tests.test_learning import setup_client
from bac.agent.presets import presets
from bac.agent.anthropic import AnthropicChat, messages_for_anthropic

BASE = "https://ai-gateway.vercel.sh/v1"


def selector(s, enabled=True):
    cfg = ModelConfig(
        base_url=BASE,
        model="convaiinnovations/laya",
        protocol="evaluation",
        provider="vercel",
        selector_enabled=enabled,
    ).model_dump()
    id = uid("selector")
    s.db.execute(
        "INSERT INTO context_selectors VALUES(?,?,?,?)",
        (id, js(cfg), s.vault.encrypt("PRIVATE-SELECTOR-KEY"), time.time()),
    )
    s.db.execute("INSERT OR REPLACE INTO active_selector VALUES(1,?)", (id,))
    return id


def choice(name="C1", confidence=0.92):
    return {
        "answers": {
            "source": {
                "type": "choice",
                "choice": name,
                "probabilities": {"C1": confidence, "none": 1 - confidence},
            }
        },
        "usage": {"inputTokens": 12, "outputTokens": 0},
    }


@pytest.mark.asyncio
async def test_selector_metadata_only_then_real_full_read_precedes_main_answer(
    services,
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    sid = selector(services)
    requests = []

    def handler(request):
        b = json.loads(request.content)
        requests.append(b)
        assert str(request.url) == BASE + "/evaluate"
        assert (
            "PRIVATE-SELECTOR-KEY" not in js(b)
            and user["id"] not in js(b)
            and node not in js(b)
        )
        assert "Neglect air resistance" not in js(b) and "paragraph" not in js(b)
        assert "غير شاقولية" in b["state"] and "ههههه" not in b["state"]
        return httpx.Response(200, json=choice())

    services.selector_transport = httpx.MockTransport(handler)

    class Main:
        async def stream(self, messages, definitions):
            names = {d["function"]["name"] for d in definitions}
            assert (
                "essential_context" in names
                and "get_section" not in names
                and "search_library" not in names
            )
            assert any(
                "Neglect air resistance" in m.get("content", "")
                for m in messages
                if isinstance(m.get("content"), str)
            )
            yield {"type": "result", "message": call("render_answer", reply(node), 1)}

    services.chat_factory = lambda cfg, key: Main()
    engine = AgentEngine(services)
    rid = engine.enqueue(
        chat,
        user,
        "اهلا مسار الفيزياء صعيبة هههههه تقدر تعاوني باه نفهم جزء حركة قذف بسرعة ابتدائية غير شاقولية",
    )
    assert (
        services.db.one("SELECT selector_config_id FROM agent_runs WHERE id=?", (rid,))[
            "selector_config_id"
        ]
        == sid
    )
    await engine.process(engine.claim())
    run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    assert run["status"] == "COMPLETED" and run["steps"] == 1 and len(requests) == 1
    usage = services.db.rows(
        "SELECT feature,input_tokens,output_tokens FROM model_usage"
    )
    assert any(
        x["feature"] == "source_selection"
        and x["input_tokens"] == 12
        and x["output_tokens"] == 0
        for x in usage
    )
    assert "PRIVATE-SELECTOR-KEY" not in js(
        services.db.rows("SELECT * FROM run_events")
    )


@pytest.mark.asyncio
async def test_none_or_uncertain_selection_never_grants_read_credit(services):
    await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    services.selector_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json=choice("none", 0.1))
    )

    class Main:
        async def stream(self, messages, definitions):
            assert not any(
                "Selected untrusted reference content" in m.get("content", "")
                for m in messages
                if isinstance(m.get("content"), str)
            )
            yield {
                "type": "result",
                "message": call(
                    "render_answer",
                    {
                        "response_kind": "clarification",
                        "blocks": [
                            {"type": "text", "text": "ما الفقرة التي تريد فهمها؟"}
                        ],
                    },
                    1,
                ),
            }

    services.chat_factory = lambda cfg, key: Main()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح حركة القذف غير الشاقولية")
    await e.process(e.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert not services.db.rows("SELECT * FROM loaded_context")


@pytest.mark.asyncio
async def test_selector_snapshots_survive_active_configuration_change(services):
    user, chat = chat_and_config(services)
    original = selector(services)
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "مرحبا")
    new = selector(services)
    assert (
        original != new
        and services.db.one(
            "SELECT selector_config_id FROM agent_runs WHERE id=?", (rid,)
        )["selector_config_id"]
        == original
    )


@pytest.mark.asyncio
async def test_greeting_skips_selector_request_and_source_content(services):
    user, chat = chat_and_config(services)
    selector(services)
    services.selector_transport = httpx.MockTransport(
        lambda r: pytest.fail("No paid selector greeting request")
    )

    class Main:
        async def stream(self, *args):
            yield {
                "type": "result",
                "message": call(
                    "render_answer", {"blocks": [{"type": "text", "text": "أهلًا!"}]}, 1
                ),
            }

    services.chat_factory = lambda cfg, key: Main()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "مرحبا")
    await e.process(e.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert not services.db.rows(
        "SELECT 1 FROM model_usage WHERE feature='source_selection'"
    )


@pytest.mark.asyncio
async def test_main_cannot_bypass_coordinator_with_unadvertised_library_tool(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    services.selector_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json=choice())
    )
    seen = []

    class Main:
        async def stream(self, messages, definitions):
            seen.append(messages)
            if len(seen) == 1:
                message = call("get_section", {"node_id": node}, 1)
            else:
                assert (
                    "not available in coordinated-source mode"
                    in messages[-1]["content"]
                )
                message = call("render_answer", reply(node), 2)
            yield {"type": "result", "message": message}

    services.chat_factory = lambda cfg, key: Main()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح القذف غير الشاقولي")
    await e.process(e.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
        and len(seen) == 2
    )
    assert len(services.db.rows("SELECT * FROM loaded_context")) == 1


@pytest.mark.asyncio
async def test_coordinated_main_has_small_round_budget_and_forced_final(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    services.selector_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json=choice())
    )
    seen = []

    class Main:
        async def stream(self, messages, definitions):
            seen.append("regular")
            yield {
                "type": "result",
                "message": call(
                    "calculate", {"expression": str(len(seen)) + "+2"}, len(seen)
                ),
            }

        async def final_stream(self, messages, definitions):
            seen.append("final")
            assert {x["function"]["name"] for x in definitions} == {"render_answer"}
            yield {
                "type": "result",
                "message": call("render_answer", reply(node), len(seen)),
            }

    services.chat_factory = lambda cfg, key: Main()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح القذف غير الشاقولي")
    await e.process(e.claim())
    assert (
        seen == ["regular"] * 3 + ["final"]
        and services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))[
            "status"
        ]
        == "COMPLETED"
    )


@pytest.mark.asyncio
async def test_full_context_prefetch_is_not_blocked_by_old_tool_result_limit(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    services.settings = replace(services.settings, max_tool_chars=1000)
    services.selector_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json=choice())
    )

    class Main:
        async def stream(self, messages, definitions):
            yield {"type": "result", "message": call("render_answer", reply(node), 1)}

    services.chat_factory = lambda cfg, key: Main()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح القذف غير الشاقولي")
    await e.process(e.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )


@pytest.mark.asyncio
async def test_selector_429_does_not_retry_or_call_main_or_invent_sources(services):
    await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    requests = []

    def handle(r):
        requests.append(r)
        return httpx.Response(429, json={"error": {"message": "PRIVATE provider body"}})

    services.selector_transport = httpx.MockTransport(handle)
    services.chat_factory = lambda cfg, key: object()
    e = AgentEngine(services)
    e.enqueue(chat, user, "اشرح القذف غير الشاقولي")
    await e.process(e.claim())
    assert diagnose_run(services.db)["error"] == "HTTP_429" and len(requests) == 1
    assert not services.db.rows('SELECT * FROM messages WHERE role="assistant"')
    assert "PRIVATE" not in js(services.db.rows("SELECT * FROM run_events"))


@pytest.mark.parametrize(
    "payload",
    [
        choice("unknown"),
        {
            "answers": {
                "source": {
                    "choice": "C1",
                    "probabilities": {"C1": float("nan"), "none": 0},
                }
            }
        },
        {"answers": {"source": {"choice": "C1", "probabilities": {"C1": 0.99}}}},
    ],
)
def test_unregistered_choices_or_invalid_probabilities_fail_closed(payload):
    with pytest.raises(ModelError):
        selected_alias(payload, {"C1", "none"}, {})


def test_focus_preserves_nonvertical_negation_and_uses_literal_request():
    q = "اهلا مسار بارح قريت شوي ههه تقدر تعاوني باه نفهم جزء حركة قذف بسرعة ابتدائية غير شاقولية"
    assert focus(q) == "جزء حركة قذف بسرعة ابتدائية غير شاقولية"
    assert "غير" in focus(q)


@pytest.mark.parametrize(
    "provider", ["openai", "google", "anthropic", "vercel", "openrouter"]
)
def test_provider_presets_set_endpoint_and_correct_protocol_without_generation(
    provider,
):
    p = next(x for x in presets("agent") if x["id"] == provider)
    assert p["base_url"].startswith("https://") and p["model"]
    assert p["protocol"] == ("anthropic" if provider == "anthropic" else "openai")


def test_owner_only_independent_selector_config_and_no_key_forwarding(services):
    c, h, user = setup_client(services, "owner")
    before = len(services.db.rows("SELECT * FROM model_usage"))
    items = c.get("/api/owner/model-presets?slot=selector").json()["items"]
    assert next(p for p in items if p["id"] == "vercel")["protocol"] == "evaluation"
    cfg = {
        "provider": "vercel",
        "protocol": "evaluation",
        "base_url": BASE,
        "model": "convaiinnovations/laya",
        "selector_enabled": False,
    }
    r = c.put(
        "/api/owner/models/selector",
        json={"config": cfg, "api_key": "PRIVATE-FIRST-KEY"},
        headers=h,
    )
    assert r.status_code == 200
    data = c.get("/api/owner/models").json()
    assert "PRIVATE-FIRST-KEY" not in js(data)
    bad = cfg | {"provider": "custom", "base_url": "https://example.org/v1"}
    assert (
        c.put(
            "/api/owner/models/selector", json={"config": bad, "api_key": ""}, headers=h
        ).status_code
        == 422
    )
    assert (
        c.put(
            "/api/owner/models/selector",
            json={"config": bad, "api_key": "PRIVATE-NEW-KEY"},
            headers=h,
        ).status_code
        == 200
    )
    assert len(services.db.rows("SELECT * FROM model_usage")) == before
    student, _, _ = setup_client(services, "student", "student-presets@test.invalid")
    assert student.get("/api/owner/model-presets").status_code == 403


def test_native_claude_connection_uses_correct_auth_not_openai_headers(services):
    c, h, _ = setup_client(services, "owner")
    cfg = {
        "provider": "anthropic",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-5",
    }
    assert (
        c.put(
            "/api/owner/models/agent",
            json={"config": cfg, "api_key": "PRIVATE-CLAUDE-KEY"},
            headers=h,
        ).status_code
        == 200
    )

    def handler(r):
        assert (
            r.headers["x-api-key"] == "PRIVATE-CLAUDE-KEY"
            and "authorization" not in r.headers
        )
        assert r.headers["anthropic-version"] == "2023-06-01"
        return httpx.Response(200, json={"data": [{"id": "claude-sonnet-4-5"}]})

    services.connection_transport = httpx.MockTransport(handler)
    result = c.post("/api/owner/models/agent/test", json={"confirm": True}, headers=h)
    assert (
        result.status_code == 200
        and result.json()["model_advertised"] is True
        and result.json()["generation_requests"] == 0
    )
    assert "PRIVATE" not in result.text


def test_native_claude_history_groups_parallel_results_and_private_pixels():
    system, ms = messages_for_anthropic(
        [
            {"role": "system", "content": "policy"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "one", "function": {"name": "read", "arguments": "{}"}},
                    {"id": "two", "function": {"name": "calc", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "one", "content": "data"},
            {"role": "tool", "tool_call_id": "two", "content": "result"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,YQ=="},
                    }
                ],
            },
        ]
    )
    assert system == "policy" and [m["role"] for m in ms] == ["assistant", "user"]
    assert [b["type"] for b in ms[1]["content"]] == [
        "tool_result",
        "tool_result",
        "image",
    ]


@pytest.mark.asyncio
async def test_native_claude_stream_tool_inputs_usage_and_forced_choice():
    requests = []

    def handle(r):
        b = json.loads(r.content)
        requests.append(b)
        assert (
            b["tool_choice"] == {"type": "tool", "name": "render_answer"}
            and "thinking" not in b
        )
        chunks = [
            {
                "type": "message_start",
                "message": {
                    "usage": {"input_tokens": 10, "cache_read_input_tokens": 3}
                },
            },
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "a",
                    "name": "render_answer",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"blocks":[]}'},
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 4},
            },
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join("data: " + js(x) + "\n\n" for x in chunks),
        )

    p = AnthropicChat(
        {"base_url": "https://api.anthropic.com/v1", "model": "fixture"},
        "PRIVATE",
        transport=httpx.MockTransport(handle),
    )
    items = [
        x
        async for x in p.final_stream(
            [{"role": "user", "content": "hi"}],
            [
                {
                    "function": {
                        "name": "render_answer",
                        "description": "Finish",
                        "parameters": {"type": "object"},
                    }
                }
            ],
        )
    ]
    assert (
        items[-1]["message"]["tool_calls"][0]["function"]["arguments"]
        == '{"blocks":[]}'
    )
    assert (
        items[-2]["data"]["prompt_tokens"] == 13
        and items[-2]["data"]["prompt_tokens_details"]["cached_tokens"] == 3
    )


@pytest.mark.asyncio
async def test_switchable_chat_selector_is_one_structured_call_without_execution():
    seen = []

    def handler(r):
        body = json.loads(r.content)
        seen.append(body)
        assert body["tool_choice"]["function"]["name"] == "choose_source"
        assert body["tools"][0]["function"]["parameters"]["properties"]["choice"][
            "enum"
        ] == ["C1", "none"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "pick",
                                    "function": {
                                        "name": "choose_source",
                                        "arguments": js(
                                            {
                                                "choice": "C1",
                                                "probabilities": {
                                                    "C1": 0.9,
                                                    "none": 0.1,
                                                },
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": {"prompt_tokens": 9, "completion_tokens": 4},
            },
        )

    payload = await evaluate(
        {
            "base_url": "https://example.org/v1",
            "model": "decision",
            "protocol": "openai",
        },
        "PRIVATE",
        "question",
        {
            "source": {
                "type": "choice",
                "criteria": {"C1": "A lesson", "none": "No suitable source"},
            }
        },
        transport=httpx.MockTransport(handler),
    )
    assert selected_alias(payload, {"C1", "none"}, {}) == "C1" and len(seen) == 1
    assert payload["usage"] == {"inputTokens": 9, "outputTokens": 4}


@pytest.mark.asyncio
async def test_essential_addition_is_single_and_same_batch_cannot_render(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    requests = []

    def handler(r):
        requests.append(r)
        return httpx.Response(200, json=choice())

    services.selector_transport = httpx.MockTransport(handler)
    turns = []

    class Main:
        async def stream(self, messages, definitions):
            turns.append(messages)
            if len(turns) == 1:
                m = call(
                    "essential_context",
                    {
                        "importance": "essential",
                        "query": "حركة قذف بسرعة ابتدائية غير شاقولية",
                        "reason": "Need the precise acceleration concept required by the question.",
                    },
                    1,
                )
                m["tool_calls"] += call("render_answer", reply(node), 2)["tool_calls"]
            elif len(turns) == 2:
                assert "Render the answer alone" in messages[-1]["content"]
                m = call(
                    "essential_context",
                    {
                        "importance": "essential",
                        "query": "القذف حركة",
                        "reason": "Another essential request.",
                    },
                    3,
                )
            else:
                assert "already attempted" in messages[-1]["content"]
                m = call("render_answer", reply(node), 4)
            yield {"type": "result", "message": m}

    services.chat_factory = lambda cfg, key: Main()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح القذف غير الشاقولي")
    await e.process(e.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert len(requests) == 2 and len(turns) == 3


@pytest.mark.asyncio
async def test_native_claude_actual_read_then_grounded_answer_engine(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    requests = []

    def handler(r):
        body = json.loads(r.content)
        requests.append(body)
        if len(requests) == 1:
            name, args = "get_section", {"node_id": node}
        else:
            assert body["messages"][-1]["role"] == "user"
            assert body["messages"][-1]["content"][0]["type"] == "tool_result"
            name, args = "render_answer", reply(node)
        chunks = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": str(len(requests)),
                    "name": name,
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": js(args)},
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 4},
            },
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join("data: " + js(x) + "\n\n" for x in chunks),
        )

    services.chat_factory = lambda cfg, key: AnthropicChat(
        {"base_url": "https://api.anthropic.com/v1", "model": "fixture"},
        "PRIVATE",
        transport=httpx.MockTransport(handler),
    )
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح القذف غير الشاقولي")
    await e.process(e.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
        and len(requests) == 2
    )


def test_candidate_publication_and_metadata_privacy(services):
    # No draft nodes can enter a selector's candidate universe.
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    assert candidates(tools, "قذف") == []


@pytest.mark.asyncio
async def test_native_claude_vision_forced_schema_validated_page(
    services, tmp_path, monkeypatch
):
    from bac.agent import anthropic_vision
    from bac.vendor.bookforge.models.page import PageDocument
    from tests.fixture_book import golden_page

    raw = PageDocument.model_validate(golden_page(1, 600, 850))
    seen = []

    def handler(r):
        b = json.loads(r.content)
        seen.append(b)
        assert b["tool_choice"] == {"type": "tool", "name": "extract_page"}
        assert b["messages"][0]["content"][1]["type"] == "image"
        assert b["messages"][0]["content"][1]["source"]["media_type"] == "image/png"
        assert b["tools"][0]["input_schema"]["title"] == "PageDocument"
        chunks = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "page",
                    "name": "extract_page",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": raw.model_dump_json(),
                },
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 5},
            },
        ]
        return httpx.Response(
            200, text="".join("data: " + js(x) + "\n\n" for x in chunks)
        )

    monkeypatch.setattr(
        anthropic_vision,
        "AnthropicChat",
        lambda cfg, key, private: AnthropicChat(
            cfg, key, private, httpx.MockTransport(handler)
        ),
    )
    image = tmp_path / "page.png"
    image.write_bytes(b"\x89PNG" + b"test")
    adapter = services.vision_provider(
        {
            "protocol": "anthropic",
            "base_url": "https://api.anthropic.com/v1",
            "model": "fixture",
        },
        "PRIVATE",
        lambda c, k: None,
    )
    page, usage = await adapter.extract(image, 1, 600, 850)
    assert page == raw and usage["completion_tokens"] == 5 and len(seen) == 1


@pytest.mark.asyncio
async def test_selector_public_history_sse_exports_keep_provenance_private(services):
    from bac.api.main import create_app
    from fastapi.testclient import TestClient
    from tests.test_api import login

    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    services.selector_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json=choice())
    )

    class Main:
        async def stream(self, messages, definitions):
            yield {"type": "result", "message": call("render_answer", reply(node), 1)}

    services.chat_factory = lambda cfg, key: Main()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح حركة القذف غير الشاقولي")
    await e.process(e.claim())
    client = TestClient(create_app(services))
    login(client, "student@example.com")
    for url in [
        f"/api/conversations/{chat}",
        f"/api/conversations/{chat}/export",
        "/api/privacy/export",
        f"/api/runs/{rid}/events",
    ]:
        data = client.get(url)
        assert data.status_code == 200
        assert node not in data.text
        assert all(
            x not in data.text
            for x in [
                "convaiinnovations",
                "ai-gateway.vercel",
                "PRIVATE-SELECTOR",
                "select_context",
                "Neglect air resistance",
            ]
        )
        assert "حركة قذف بسرعة ابتدائية غير شاقولية" not in data.text


@pytest.mark.asyncio
async def test_configured_full_context_overflow_is_explicit_not_silent(services):
    await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    services.selector_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json=choice())
    )
    # Preserve a published complete source, while simulating a very long serialized payload.
    original = Tools.load

    def oversized(self, *args, **kwargs):
        payload = original(self, *args, **kwargs)
        payload["large_untrusted_content"] = "x" * 30000
        return payload

    Tools.load = oversized
    calls = []
    services.chat_factory = lambda cfg, key: calls.append("main")
    cfg = services.db.one("SELECT * FROM model_configs WHERE slot='agent'")
    config = json.loads(cfg["config"]) | {"max_context_chars": 10000}
    services.db.execute(
        "UPDATE model_configs SET config=? WHERE id=?", (js(config), cfg["id"])
    )
    try:
        e = AgentEngine(services)
        rid = e.enqueue(chat, user, "اشرح القذف غير الشاقولي")
        await e.process(e.claim())
        run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
        assert run["status"] == "FAILED" and run["error"] == "CONTEXT_BUDGET_EXCEEDED"
        assert not services.db.rows("SELECT * FROM messages WHERE role='assistant'")
    finally:
        Tools.load = original


@pytest.mark.asyncio
async def test_multisource_choices_finish_before_any_full_read(services, monkeypatch):
    from bac.agent.selection import ContextSelector

    first = await publish_reference(services)
    second = await publish_reference(services, "arithmetic")
    user, chat = chat_and_config(services)
    sid = selector(services)
    row = services.db.one("SELECT * FROM context_selectors WHERE id=?", (sid,))
    config = json.loads(row["config"]) | {"selector_max_sources": 3}
    row["config"] = js(config)
    sequence = []
    original = Tools.load

    def load(self, *args, **kwargs):
        sequence.append("read")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Tools, "load", load)

    def handler(r):
        b = json.loads(r.content)
        assert "read" not in sequence
        sequence.append("choose")
        criteria = b["questions"]["source"]["criteria"]
        if len(sequence) == 2:
            assert "already_selected_metadata" in b["state"]
            assert first not in b["state"] and second not in b["state"]
        probabilities = {
            k: 0.9 if k == "C1" else 0.1 / (len(criteria) - 1) for k in criteria
        }
        return httpx.Response(
            200,
            json={
                "answers": {"source": {"choice": "C1", "probabilities": probabilities}},
                "usage": {"inputTokens": 4, "outputTokens": 0},
            },
        )

    services.selector_transport = httpx.MockTransport(handler)
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح حركة القذف وحساب الجمع")
    run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    tools = Tools(services, user, chat, rid)
    data = await ContextSelector(services, row).prepare(
        run, tools, "اشرح حركة القذف وحساب الجمع"
    )
    assert sequence == ["choose", "choose", "read", "read"]
    assert {r["node"]["id"] for r in data["selected_references"]} == {first, second}


@pytest.mark.asyncio
async def test_multisource_stops_when_decider_says_enough(services):
    from bac.agent.selection import ContextSelector

    await publish_reference(services)
    await publish_reference(services, "arithmetic")
    user, chat = chat_and_config(services)
    sid = selector(services)
    row = services.db.one("SELECT * FROM context_selectors WHERE id=?", (sid,))
    row["config"] = js(json.loads(row["config"]) | {"selector_max_sources": 8})
    calls = []

    def handler(r):
        calls.append(r)
        criteria = json.loads(r.content)["questions"]["source"]["criteria"]
        selected = "C1" if len(calls) == 1 else "none"
        scores = {
            k: 0.9 if k == selected else 0.1 / (len(criteria) - 1) for k in criteria
        }
        return httpx.Response(
            200,
            json={"answers": {"source": {"choice": selected, "probabilities": scores}}},
        )

    services.selector_transport = httpx.MockTransport(handler)
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح حركة القذف وحساب الجمع")
    run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    data = await ContextSelector(services, row).prepare(
        run, Tools(services, user, chat, rid), "اشرح حركة القذف وحساب الجمع"
    )
    assert len(calls) == 2 and "node" in data and "selected_references" not in data


@pytest.mark.parametrize(
    "q,title,expected",
    [
        ("قذف بسرعة ابتدائية غير شاقولية", "قذف شاقولي", True),
        ("قذف بسرعة ابتدائية غير شاقولية", "قذف غير شاقولي", False),
        ("Explain oblique projectile motion", "Vertical motion", True),
        ("حركة قذف", "قذف شاقولي", False),
        ("قذف غير شاقولي", "قانون نيوتن", False),
    ],
)
def test_explicit_motion_negation_does_not_admit_opposite_title(q, title, expected):
    from bac.agent.selection import conflicts_with_explicit_motion

    assert conflicts_with_explicit_motion(q, title) is expected


@pytest.mark.parametrize(
    "title",
    [
        "المركبة الأفقية والشاقولية لحركة القذف",
        "Horizontal and vertical components of projectile motion",
    ],
)
def test_motion_guard_keeps_component_lessons(title):
    from bac.agent.selection import conflicts_with_explicit_motion

    assert not conflicts_with_explicit_motion("قذف بسرعة ابتدائية غير شاقولية", title)
