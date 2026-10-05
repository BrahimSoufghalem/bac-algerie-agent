"""Shared provider contracts; offline regression tests, not quality claims."""

import copy
import json

import httpx
import pytest
from pydantic import ValidationError

from bac.agent.anthropic import AnthropicChat
from bac.agent.compat import answer_tools
from bac.agent.full_index import (
    GOAL_MAX_CHARS,
    ROUTE_FUNCTION,
    ROUTE_SYSTEM,
    call_router_llm,
    parse_route,
    router_function,
)
from bac.agent.models import ModelConfig, PresentedAnswer
from bac.agent.presets import generation_config, presets
from bac.agent.provider import ModelError, OpenAIChat
from bac.core.db import js
from tests.test_learning import setup_client


def answer_manifest():
    return [
        {
            "type": "function",
            "function": {
                "name": "render_answer",
                "description": "Render",
                "parameters": PresentedAnswer.model_json_schema(),
            },
        }
    ]


def test_wire_schema_and_server_validation_remain_distinct():
    original = answer_manifest()
    before = copy.deepcopy(original)
    wire = answer_tools(original)
    assert original == before
    graph = wire[0]["function"]["parameters"]["$defs"]["GraphBlock"]
    assert set(graph["properties"]) == {"type", "result_id"}
    assert graph["additionalProperties"] is False
    assert "discriminator" in js(wire)
    assert PresentedAnswer.model_validate(
        {"blocks": [{"type": "graph", "result_id": "actual-result"}]}
    )
    with pytest.raises(ValidationError):
        PresentedAnswer.model_validate(
            {"blocks": [{"type": "graph", "result_id": "actual-result", "result": {}}]}
        )
    with pytest.raises(ValidationError):
        PresentedAnswer.model_validate(
            {"blocks": [{"type": "text", "latex": "wrong field"}]}
        )


@pytest.mark.parametrize("slot", ["agent", "selector"])
def test_existing_small_output_budgets_get_safe_effective_floor(slot):
    cfg = {"max_tokens": 1500, "temperature": 1}
    before = dict(cfg)
    actual = generation_config(cfg, slot)
    assert cfg == before
    assert actual["max_tokens"] == 6000
    assert actual["temperature"] == (0 if slot == "selector" else 0.1)
    assert generation_config(cfg | {"max_tokens": 8000}, slot)["max_tokens"] == 8000


def test_focus_is_local_optional_policy_not_extra_provider_parameter():
    cfg = {"max_tokens": 1500, "temperature": 1, "focused_mode": True}
    saved = generation_config(cfg, "agent", effective=False)
    assert saved["temperature"] == 1
    assert generation_config(saved, "agent")["temperature"] == 0.1
    assert (
        generation_config(saved | {"focused_mode": False}, "agent")["temperature"] == 1
    )
    assert generation_config(cfg | {"temperature": 0}, "agent")["temperature"] == 0
    assert generation_config(cfg, "extraction") == cfg
    for slot in ["agent", "selector"]:
        for preset in presets(slot):
            assert preset["max_tokens"] == 6000
            assert preset["temperature"] == (0 if slot == "selector" else 0.1)


def test_goal_bounds_are_advertised_and_match_server_validator():
    frozen = js(ROUTE_FUNCTION)
    function = router_function(5)
    props = function["parameters"]["properties"]
    goal = props["goals"]["items"]["properties"]["goal"]
    assert goal["minLength"] == 1 and goal["maxLength"] == GOAL_MAX_CHARS == 400
    assert props["goals"]["maxItems"] == 5
    assert props["goals"]["items"]["properties"]["ids"]["maxItems"] == 5
    assert props["question"]["maxLength"] == 280
    assert (
        router_function(5, verify=True)["parameters"]["properties"]["ids"]["maxItems"]
        == 5
    )
    assert js(ROUTE_FUNCTION) == frozen
    for length in [169, 400]:
        args = {
            "status": "read",
            "goals": [{"goal": "ه" * length, "ids": ["S1"]}],
            "question": "",
        }
        assert parse_route(args, {"S1"})["selected_ids"] == ["S1"]
    with pytest.raises(ModelError):
        parse_route(
            {
                "status": "read",
                "goals": [{"goal": "ه" * 401, "ids": ["S1"]}],
                "question": "",
            },
            {"S1"},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base",
    [
        "https://tokenharbor.ai/v1",
        "https://api.deepseek.com/v1",
        "https://openrouter.ai/api/v1",
        "https://fixture.invalid/v1",
    ],
)
async def test_openai_compatible_providers_never_advertise_server_graph_payload(base):
    original = answer_manifest()

    def handler(request):
        body = json.loads(request.content)
        fields = body["tools"][0]["function"]["parameters"]["$defs"]["GraphBlock"][
            "properties"
        ]
        assert "result" not in fields and "result_id" in fields
        assert "focused_mode" not in body and "reasoning_effort" not in body
        assert body["temperature"] == 0.1 and body["max_tokens"] == 6000
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "terminal",
                                    "type": "function",
                                    "function": {
                                        "name": "render_answer",
                                        "arguments": js(
                                            {
                                                "blocks": [
                                                    {"type": "text", "text": "Hello"}
                                                ]
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    cfg = generation_config(
        {"base_url": base, "model": "fixture", "temperature": 1}, "agent"
    )
    _ = [
        x
        async for x in OpenAIChat(
            cfg, "fixture-only", transport=httpx.MockTransport(handler)
        ).final_stream([], original)
    ]
    assert (
        "result"
        in original[0]["function"]["parameters"]["$defs"]["GraphBlock"]["properties"]
    )


@pytest.mark.asyncio
async def test_native_anthropic_gets_same_safe_answer_schema():
    def handler(request):
        body = json.loads(request.content)
        fields = body["tools"][0]["input_schema"]["$defs"]["GraphBlock"]["properties"]
        assert "result" not in fields and "result_id" in fields
        assert "focused_mode" not in body
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 5}}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "f",
                    "name": "render_answer",
                    "input": {"blocks": [{"type": "text", "text": "Hello"}]},
                },
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 3},
            },
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join("data: " + js(event) + "\n\n" for event in events),
        )

    cfg = generation_config(
        {"base_url": "https://api.anthropic.com/v1", "model": "fixture"}, "agent"
    )
    _ = [
        x
        async for x in AnthropicChat(
            cfg, "fixture-only", transport=httpx.MockTransport(handler)
        ).final_stream([], answer_manifest())
    ]


@pytest.mark.asyncio
async def test_router_uses_new_budget_even_for_an_old_saved_configuration():
    args = {
        "status": "read",
        "goals": [{"goal": "ه" * 169, "ids": ["S1"]}],
        "question": "",
    }

    def handler(request):
        body = json.loads(request.content)
        assert body["max_tokens"] == 6000 and body["temperature"] == 0
        assert (
            body["tools"][0]["function"]["parameters"]["properties"]["goals"]["items"][
                "properties"
            ]["goal"]["maxLength"]
            == 400
        )
        assert body["tool_choice"]["function"]["name"] == "route_sections"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "route",
                                    "type": "function",
                                    "function": {
                                        "name": "route_sections",
                                        "arguments": js(args),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            },
        )

    cfg = {
        "base_url": "https://fixture.invalid/v1",
        "model": "fixture",
        "max_tokens": 1500,
    }
    decision, usage = await call_router_llm(
        cfg,
        "fixture-only",
        ROUTE_SYSTEM,
        {},
        router_function(),
        transport=httpx.MockTransport(handler),
    )
    assert parse_route(decision, {"S1"})["selected_ids"] == ["S1"]
    assert usage["inputTokens"] == 20


def test_owner_can_save_disable_focus_without_mutating_old_version(
    services, monkeypatch
):
    client, headers, _ = setup_client(services, "owner")

    async def valid_url(*args):
        return None

    monkeypatch.setattr("bac.api.main.validate_base_url", valid_url)
    cfg = ModelConfig(
        base_url="https://fixture.invalid/v1",
        model="fixture",
        max_tokens=1500,
        temperature=1,
        focused_mode=True,
    ).model_dump()
    first = client.put(
        "/api/owner/models/agent",
        json={"config": cfg, "api_key": "PRIVATE-FIXTURE"},
        headers=headers,
    )
    assert first.status_code == 200
    old = services.db.one(
        "SELECT * FROM model_configs WHERE id=?", (first.json()["id"],)
    )
    assert json.loads(old["config"])["max_tokens"] == 6000
    assert json.loads(old["config"])["temperature"] == 1
    second = client.put(
        "/api/owner/models/agent",
        json={"config": cfg | {"focused_mode": False}},
        headers=headers,
    )
    assert second.status_code == 200 and second.json()["id"] != first.json()["id"]
    public = client.get("/api/owner/models").json()["items"][0]
    assert public["focused_mode"] is False and public["temperature"] == 1
    assert "PRIVATE-FIXTURE" not in json.dumps(public)
    assert (
        services.db.one("SELECT config FROM model_configs WHERE id=?", (old["id"],))[
            "config"
        ]
        == old["config"]
    )
