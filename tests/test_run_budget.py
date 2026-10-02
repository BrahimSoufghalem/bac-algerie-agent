"""Deterministic regression tests, not a claim of real-model quality."""

import json
import pytest
from dataclasses import replace
from bac.agent.engine import AgentEngine
from tests.test_agent import chat_and_config


def call(name, args, i):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": f"c{i}",
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def answer(text="أي جزء من الفقرة تريد أن نراجعه؟"):
    return {
        "blocks": [{"type": "text", "text": text}],
        "source_ids": [],
        "response_kind": "clarification",
    }


class ExhaustWorkingRounds:
    def __init__(self):
        self.calls = []

    async def stream(self, messages, tools):
        names = {t["function"]["name"] for t in tools}
        self.calls.append(names)
        i = len(self.calls)
        if names == {"render_answer"}:
            msg = call("render_answer", answer(), i)
        else:
            msg = call("list_private_uploads", {}, i)
        yield {"type": "result", "message": msg}


@pytest.mark.asyncio
async def test_time_pressure_reserves_final_without_extra_model_calls(services):
    user, chat = chat_and_config(services)
    # Two working rounds avoid the independent identical-call guard.
    services.settings = replace(services.settings, max_run_steps=3)
    provider = ExhaustWorkingRounds()
    services.chat_factory = lambda cfg, key: provider
    e = AgentEngine(services)
    remaining = iter([20, 15, 0])
    e.remaining_time = lambda deadline: next(remaining)
    run = e.enqueue(chat, user, "اشرحلي حركة قذف بسرعة ابتدائية غير شاقولية")
    await e.process(e.claim())
    row = services.db.one("SELECT * FROM agent_runs WHERE id=?", (run,))
    assert row["status"] == "COMPLETED"
    assert row["steps"] == 3 and len(provider.calls) == 3
    assert provider.calls[-1] == {"render_answer"}


@pytest.mark.asyncio
async def test_empty_search_variants_stop_without_student_tool_instructions(services):
    user, chat = chat_and_config(services)
    seen = []

    class Searching:
        async def stream(self, messages, tools):
            names = {t["function"]["name"] for t in tools}
            seen.append(names)
            if "search_library" in names:
                msg = call(
                    "search_library",
                    {
                        "query": [
                            "قذف",
                            "حركة قذف",
                            "مقذوفات",
                            "projectile",
                            "physics",
                        ][len(seen) - 1]
                    },
                    len(seen),
                )
            else:
                msg = call(
                    "render_answer",
                    answer("هل يمكنك إرسال الفقرة أو المعطيات التي تريد أن نراجعها؟"),
                    len(seen),
                )
            yield {"type": "result", "message": msg}

    services.chat_factory = lambda cfg, key: Searching()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرحلي حركة قذف بسرعة ابتدائية غير شاقولية")
    await e.process(e.claim())
    row = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    assert row["status"] == "COMPLETED" and row["steps"] == 3
    assert "search_library" not in seen[-1]
    stored = services.db.one(
        "SELECT sources,content FROM messages WHERE role='assistant'"
    )
    assert json.loads(stored["sources"]) == [] and "؟" in stored["content"]
    assert "شرح عام" not in stored["content"]


@pytest.mark.asyncio
async def test_time_pressure_can_answer_but_cannot_execute_work(services):
    user, chat = chat_and_config(services)
    services.settings = replace(services.settings, max_run_steps=1)
    provider = ExhaustWorkingRounds()
    services.chat_factory = lambda cfg, key: provider
    e = AgentEngine(services)
    e.remaining_time = lambda deadline: 0
    r = e.enqueue(chat, user, "مرحبا")
    await e.process(e.claim())
    row = services.db.one(
        "SELECT status,steps,tool_calls FROM agent_runs WHERE id=?", (r,)
    )
    assert row == {"status": "COMPLETED", "steps": 1, "tool_calls": 0}
    assert provider.calls == [{"render_answer"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name,args,code",
    [
        ("search_library", {"query": "قذف"}, "FINAL_ANSWER_REQUIRED"),
        (
            "render_answer",
            {"blocks": [{"type": "image", "asset_id": "not-read"}]},
            "FINAL_ANSWER_INVALID",
        ),
        (
            "render_answer",
            {
                "blocks": [{"type": "text", "text": "alleged source"}],
                "source_ids": ["invented"],
            },
            "FINAL_ANSWER_INVALID",
        ),
        (
            "render_answer",
            {"blocks": [{"type": "verification", "result_id": "not-computed"}]},
            "FINAL_ANSWER_INVALID",
        ),
    ],
)
async def test_final_round_fail_closed_without_fabricated_answer(
    services, name, args, code
):
    user, chat = chat_and_config(services)
    services.settings = replace(services.settings, max_run_steps=1)

    class Wrong:
        async def stream(self, messages, tools):
            yield {"type": "result", "message": call(name, args, 1)}

    services.chat_factory = lambda cfg, key: Wrong()
    e = AgentEngine(services)
    e.remaining_time = lambda deadline: 0
    rid = e.enqueue(chat, user, "اشرحلي الدرس")
    await e.process(e.claim())
    row = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    assert (
        row["status"] == "FAILED"
        and row["error"] == code
        and row["steps"] == 1
        and row["tool_calls"] == 0
    )
    assert not services.db.rows("SELECT * FROM messages WHERE role='assistant'")
    error = json.loads(
        services.db.one("SELECT payload FROM run_events WHERE type='error'")["payload"]
    )
    assert error["steps"] == 1 and "step_limit" not in error


@pytest.mark.asyncio
async def test_unstructured_reply_does_not_auto_cite_previous_topic(
    services, monkeypatch
):

    user, chat = chat_and_config(services)
    original = AgentEngine.context

    def context(self, run, tools, user):
        messages = original(self, run, tools, user)
        tools.sources["unrelated-heat-source"] = {"node_id": "unrelated-heat-source"}
        return messages

    monkeypatch.setattr(AgentEngine, "context", context)

    class Plain:
        async def stream(self, messages, tools):
            yield {
                "type": "result",
                "message": {
                    "role": "assistant",
                    "content": "شرح عام للقذف، لا للحرارة.",
                },
            }

    services.chat_factory = lambda cfg, key: Plain()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرحلي القذف")
    await e.process(e.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "FAILED"
    )
    assert not services.db.one("SELECT * FROM messages WHERE role='assistant'")
    assert services.db.rows("SELECT * FROM run_events WHERE type='answer_rejected'")


@pytest.mark.asyncio
async def test_no_fixed_eight_round_or_twenty_tool_ceiling(services, monkeypatch):
    from bac.agent.tools import Tools

    user, chat = chat_and_config(services)
    # Even a legacy max_run_steps=1 must not impose a round cap.
    services.settings = replace(services.settings, max_run_steps=1)
    original = Tools.execute

    def execute(self, name, args):
        if name == "search_library":
            return {"items": [{"locator_only": True, "query": args["query"]}]}
        return original(self, name, args)

    monkeypatch.setattr(Tools, "execute", execute)
    calls = []

    class Long:
        async def stream(self, messages, tools):
            calls.append(1)
            i = len(calls)
            msg = (
                call("search_library", {"query": "unique " + str(i)}, i)
                if i <= 22
                else call("render_answer", answer(), i)
            )
            yield {"type": "result", "message": msg}

    services.chat_factory = lambda cfg, key: Long()
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "اشرحلي درسًا")
    await e.process(e.claim())
    row = services.db.one(
        "SELECT status,steps,tool_calls FROM agent_runs WHERE id=?", (rid,)
    )
    assert row == {"status": "COMPLETED", "steps": 23, "tool_calls": 22}
