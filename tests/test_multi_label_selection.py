import json
import httpx
import pytest
from bac.agent.selection import (
    selected_aliases,
    ContextSelector,
    has_source_body,
    focus,
)
from bac.agent.provider import ModelError
from bac.agent.tools import Tools
from bac.agent.models import ModelConfig
from bac.agent.engine import AgentEngine
from bac.core.db import js
from tests.test_context_selector import selector
from tests.test_agent import chat_and_config
from tests.grounding_fixture import publish_reference


def labels(**values):
    return {
        "answers": {k: {"type": "boolean", "probability": p} for k, p in values.items()}
    }


def test_independent_probabilities_can_select_two_equal_high_matches():
    assert selected_aliases(labels(C1=0.9, C2=0.9, C3=0.1), ["C1", "C2", "C3"], {}) == [
        "C1",
        "C2",
    ]


def test_empty_selection_is_valid_not_a_fabricated_none_reference():
    assert selected_aliases(labels(C1=0.1, C2=0.2), ["C1", "C2"], {}) == []


def test_cap_stable_ties_and_include_exclude_margin_not_between_sources():
    payload = labels(C1=0.7, C2=0.7, C3=0.7, C4=0.56)
    assert selected_aliases(
        payload, list(payload["answers"]), {"selector_max_sources": 2}
    ) == ["C1", "C2"]
    assert (
        selected_aliases(
            labels(C1=0.6, C2=0.6), ["C1", "C2"], {"selector_min_margin": 0.3}
        )
        == []
    )


@pytest.mark.parametrize(
    "p", [None, True, "0.9", float("nan"), float("inf"), -0.1, 1.1]
)
def test_invalid_probabilities_fail_closed(p):
    with pytest.raises(ModelError):
        selected_aliases(labels(C1=p), ["C1"], {})


@pytest.mark.parametrize(
    "payload",
    [
        {"answers": {}},
        labels(C1=0.9, invented=0.9),
        {"answers": {"C1": {"type": "choice", "probability": 0.9}}},
    ],
)
def test_missing_unknown_or_wrong_answer_types_fail_closed(payload):
    with pytest.raises(ModelError):
        selected_aliases(payload, ["C1"], {})


def test_default_allows_multiple_without_forcing_multiple():
    assert (
        ModelConfig(
            base_url="https://example.org", model="fixture"
        ).selector_max_sources
        == 3
    )


def test_heading_only_does_not_count_as_teaching_content():
    assert not has_source_body("<!-- PDF provenance -->\n\n# حركة السقوط")
    assert has_source_body("# قانون\n\n$$\nF=ma\n$$")


def test_short_followup_keeps_newest_preceding_question():
    q = "زيد وضح"
    result = focus(q, q + "\nاشرح شحن المكثفة\nاشرح نصف العمر")
    assert "المكثفة" in result and "نصف العمر" not in result


@pytest.mark.asyncio
async def test_multi_refs_read_once_and_second_prepare_skips_already_read(services):
    await publish_reference(services)
    await publish_reference(services, "arithmetic")
    user, chat = chat_and_config(services)
    sid = selector(services)
    calls = []

    def handler(r):
        body = json.loads(r.content)
        calls.append(body)
        assert "PRIVATE-SELECTOR" not in js(body)
        state = json.loads(body["state"])
        assert state["selection_policy"].count("You are a concept-selection") == 1
        return httpx.Response(
            200,
            json={
                "answers": {
                    k: {"type": "boolean", "probability": 0.95}
                    for k in body["questions"]
                }
            },
        )

    services.selector_transport = httpx.MockTransport(handler)
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح حركة القذف وحساب الجمع")
    run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    tools = Tools(services, user, chat, rid)
    decider = ContextSelector(
        services, services.db.one("SELECT * FROM context_selectors WHERE id=?", (sid,))
    )
    data = await decider.prepare(run, tools, "اشرح حركة القذف وحساب الجمع")
    assert len(data["selected_references"]) == 2
    assert len(services.db.rows("SELECT * FROM loaded_context")) == 2
    assert await decider.prepare(run, tools, "اشرح حركة القذف وحساب الجمع") is None
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_no_credit_for_header_only_selected_reference(services, monkeypatch):
    await publish_reference(services)
    user, chat = chat_and_config(services)
    sid = selector(services)
    services.selector_transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json=labels(C1=0.95))
    )
    original = Tools.load

    def header(self, *a, **kw):
        result = original(self, *a, **kw)
        result["content"] = "# عنوان فقط"
        return result

    monkeypatch.setattr(Tools, "load", header)
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرح حركة القذف")
    run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    with pytest.raises(ModelError, match="SELECTED_SOURCE_HAS_NO_BODY"):
        await ContextSelector(
            services,
            services.db.one("SELECT * FROM context_selectors WHERE id=?", (sid,)),
        ).prepare(run, Tools(services, user, chat, rid), "اشرح حركة القذف")
    assert not services.db.rows("SELECT * FROM loaded_context")


@pytest.mark.parametrize("enabled", [True, False])
def test_migration_preserves_key_old_snapshot_and_activation(services, enabled):
    sid = selector(services, enabled)
    old = services.db.one("SELECT * FROM context_selectors WHERE id=?", (sid,))
    config = json.loads(old["config"]) | {"selector_max_sources": 1}
    services.db.execute(
        "UPDATE context_selectors SET config=? WHERE id=?", (js(config), sid)
    )
    services.db.execute("DELETE FROM migrations WHERE version=8")
    services.db.migrate()
    new_id = services.db.one("SELECT config_id FROM active_selector")["config_id"]
    new = services.db.one("SELECT * FROM context_selectors WHERE id=?", (new_id,))
    unchanged = services.db.one("SELECT * FROM context_selectors WHERE id=?", (sid,))
    assert new_id != sid and new["encrypted_key"] == old["encrypted_key"]
    assert json.loads(new["config"])["selector_max_sources"] == 3
    assert json.loads(new["config"])["selector_enabled"] == enabled
    assert json.loads(unchanged["config"])["selector_max_sources"] == 1
    services.db.migrate()
    assert (
        services.db.one("SELECT config_id FROM active_selector")["config_id"] == new_id
    )
