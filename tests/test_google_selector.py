import json

import httpx
import pytest

from bac.agent.engine import AgentEngine
from bac.agent.google_selector import BASE, google_router_request, parse_google_router
from bac.agent.models import ModelConfig
from bac.agent.presets import presets
from bac.agent.provider import ModelError
from bac.agent.selection import (
    ContextSelector,
    evaluate,
    selected_aliases,
)
from bac.agent.tools import Tools
from bac.core.db import js, uid
from tests.grounding_fixture import publish_reference
from tests.test_agent import chat_and_config
from tests.test_learning import setup_client

CFG = {
    "provider": "google",
    "protocol": "google",
    "base_url": BASE,
    "model": "gemma-4-31b-it",
    "temperature": 0,
    "max_tokens": 1000,
    "selector_enabled": True,
}


def request():
    state = {
        "selection_policy": "Select actual requested concepts only.",
        "student_request": "قارن نصف العمر النووي وزمن نصف التفاعل.",
        "already_selected_metadata": [
            {"title": "covered", "kind": "section", "id": "PRIVATE-COVERED-ID"}
        ],
        "candidate_concepts": [
            {
                "alias": "C1",
                "title": "Nuclear",
                "type": "section",
                "description": "Radioactive half-life",
                "id": "PRIVATE-ID",
                "content": "PRIVATE-BODY",
            },
            {
                "alias": "C2",
                "title": "Chemical",
                "type": "section",
                "description": "Chemical half-time",
            },
        ],
    }
    questions = {a: {"type": "boolean"} for a in ["C1", "C2"]}
    return state, questions


def reply(values=None):
    return {
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {
                    "role": "model",
                    "parts": [
                        {
                            "functionCall": {
                                "name": "choose_sources",
                                "args": {
                                    "selected": values or {"C1": True, "C2": True}
                                },
                            }
                        }
                    ],
                },
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "totalTokenCount": 125,
            "cachedContentTokenCount": 10,
        },
    }


def test_native_request_uses_system_policy_and_one_forced_decision_schema():
    state, questions = request()
    endpoint, body = google_router_request(CFG, state, questions)
    assert endpoint == BASE + "/models/gemma-4-31b-it:generateContent"
    assert state["selection_policy"] in body["systemInstruction"]["parts"][0]["text"]
    assert body["toolConfig"]["functionCallingConfig"] == {
        "mode": "ANY",
        "allowedFunctionNames": ["choose_sources"],
    }
    assert len(body["tools"][0]["functionDeclarations"]) == 1
    assert "PRIVATE" not in js(body)
    assert (
        "selected"
        in body["tools"][0]["functionDeclarations"][0]["parameters"]["properties"]
    )
    assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "minimal"


def test_native_explicit_booleans_do_not_invent_confidence_probabilities():
    result = parse_google_router(reply(), ["C1", "C2"])
    assert result["decisions"] == {"C1": True, "C2": True}
    assert "answers" not in result and "probability" not in js(result)
    assert result["usage"] == {
        "inputTokens": 100,
        "outputTokens": 25,
        "cachedTokens": 10,
    }
    assert selected_aliases(
        result,
        ["C1", "C2"],
        {"selector_min_confidence": 0.99, "selector_min_margin": 0.8},
    ) == ["C1", "C2"]
    assert selected_aliases(result, ["C1", "C2"], {"selector_max_sources": 1}) == ["C1"]


@pytest.mark.parametrize(
    "values",
    [
        {"C1": True},
        {"C1": True, "C2": False, "invented": True},
        {"C1": 1, "C2": 0},
        {"C1": "true", "C2": False},
    ],
)
def test_bad_decisions_fail_closed(values):
    with pytest.raises(ModelError, match="INVALID_SELECTOR_RESPONSE"):
        parse_google_router(reply(values), ["C1", "C2"])


@pytest.mark.parametrize(
    "change",
    [
        "prose",
        "inline_prose",
        "multiple",
        "wrong_name",
        "truncated",
        "bad_part",
        "bad_candidate",
    ],
)
def test_unstructured_or_incomplete_response_is_rejected(change):
    data = reply()
    if change == "prose":
        data["candidates"][0]["content"]["parts"].append({"text": "Let me teach you."})
    elif change == "inline_prose":
        data["candidates"][0]["content"]["parts"][0]["text"] = "Let me teach you."
    elif change == "multiple":
        data["candidates"][0]["content"]["parts"] *= 2
    elif change == "wrong_name":
        data["candidates"][0]["content"]["parts"][0]["functionCall"]["name"] = (
            "read_source"
        )
    elif change == "truncated":
        data["candidates"][0]["finishReason"] = "MAX_TOKENS"
    elif change == "bad_part":
        data["candidates"][0]["content"]["parts"] = [None]
    else:
        data["candidates"] = [7]
    with pytest.raises(ModelError, match="INVALID_SELECTOR_RESPONSE"):
        parse_google_router(data, ["C1", "C2"])


def test_thought_text_is_not_forwarded_and_missing_usage_is_not_zero():
    data = reply()
    data["candidates"][0]["content"]["parts"].insert(
        0, {"thought": True, "text": "PRIVATE-REASONING"}
    )
    data.pop("usageMetadata")
    result = parse_google_router(data, ["C1", "C2"])
    assert "PRIVATE" not in js(result)
    assert (
        result["usage"]["inputTokens"] is None
        and result["usage"]["outputTokens"] is None
    )


@pytest.mark.asyncio
async def test_native_google_failure_has_one_request_no_retry_or_fallback():
    state, questions = request()
    calls = []

    def handler(r):
        calls.append(str(r.url))
        assert r.headers["x-goog-api-key"] == "PRIVATE-KEY"
        assert "authorization" not in r.headers
        return httpx.Response(
            429, json={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}
        )

    with pytest.raises(ModelError, match="HTTP_429"):
        await evaluate(
            CFG, "PRIVATE-KEY", state, questions, transport=httpx.MockTransport(handler)
        )
    assert calls == [BASE + "/models/gemma-4-31b-it:generateContent"]


def test_native_endpoint_and_model_cannot_forward_key_to_another_host():
    state, questions = request()
    for change in [{"base_url": "https://example.org/v1beta"}, {"model": "../other"}]:
        with pytest.raises(ModelError, match="INVALID_SELECTOR_REQUEST"):
            google_router_request(CFG | change, state, questions)


def test_selector_preset_does_not_change_teaching_or_activate_implicitly(services):
    google = next(p for p in presets("selector") if p["id"] == "google")
    assert google["model"] == CFG["model"] and google["protocol"] == "google"
    assert (
        next(p for p in presets("agent") if p["id"] == "google")["protocol"] == "openai"
    )
    c, h, _ = setup_client(services, "owner")
    saved = c.put(
        "/api/owner/models/selector",
        headers=h,
        json={
            "config": CFG | {"selector_enabled": False},
            "api_key": "PRIVATE-GOOGLE-KEY",
        },
    )
    assert saved.status_code == 200
    assert not services.db.rows("SELECT * FROM active_models")
    assert not services.db.rows("SELECT * FROM model_usage")
    assert "PRIVATE-GOOGLE-KEY" not in c.get("/api/owner/models").text
    assert (
        c.put(
            "/api/owner/models/agent",
            headers=h,
            json={"config": CFG, "api_key": "PRIVATE-GOOGLE-KEY"},
        ).status_code
        == 422
    )


def test_native_catalog_test_is_get_only_and_returns_normalized_names(services):
    c, h, _ = setup_client(services, "owner")
    assert (
        c.put(
            "/api/owner/models/selector",
            headers=h,
            json={"config": CFG, "api_key": "PRIVATE-GOOGLE-KEY"},
        ).status_code
        == 200
    )
    calls = []

    def handler(r):
        calls.append((r.method, str(r.url)))
        assert r.headers["x-goog-api-key"] == "PRIVATE-GOOGLE-KEY"
        assert "authorization" not in r.headers
        return httpx.Response(200, json={"models": [{"name": "models/gemma-4-31b-it"}]})

    services.connection_transport = httpx.MockTransport(handler)
    result = c.post(
        "/api/owner/models/selector/test", headers=h, json={"confirm": True}
    )
    assert result.status_code == 200
    assert (
        result.json()["model_advertised"] is True
        and result.json()["generation_requests"] == 0
    )
    assert result.json()["models"] == [{"id": CFG["model"], "type": "language"}]
    assert calls == [("GET", BASE + "/models")]


@pytest.mark.asyncio
async def test_google_decision_precedes_real_full_read_on_same_coordinator(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    config = ModelConfig(**CFG).model_dump()
    id_ = uid("selector")
    services.db.execute(
        "INSERT INTO context_selectors VALUES(?,?,?,?)",
        (id_, js(config), services.vault.encrypt("PRIVATE-KEY"), 1),
    )
    services.db.execute("INSERT INTO active_selector VALUES(1,?)", (id_,))
    calls = []

    def handler(r):
        body = json.loads(r.content)
        assert node not in js(body) and user["id"] not in js(body)
        assert "Neglect air resistance" not in js(body)
        assert not services.db.rows("SELECT * FROM loaded_context")
        calls.append(str(r.url))
        return httpx.Response(200, json=reply({"C1": True}))

    services.selector_transport = httpx.MockTransport(handler)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح حركة القذف")
    run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    tools = Tools(services, user, chat, rid)
    result = await ContextSelector(
        services, services.db.one("SELECT * FROM context_selectors WHERE id=?", (id_,))
    ).prepare(run, tools, "اشرح حركة القذف")
    assert (
        result["node"]["id"] == node and "Neglect air resistance" in result["content"]
    )
    assert len(services.db.rows("SELECT * FROM loaded_context")) == 1
    assert len(calls) == 1
