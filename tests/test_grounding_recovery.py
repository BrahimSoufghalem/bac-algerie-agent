"""Actual-read gates and corrected graph workflows, with explicit offline models."""

import json
import pytest
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.agent.engine import AgentEngine
from bac.agent.provider import ModelError
from bac.agent.tools import Tools
from bac.core.activity import attach_activity
from bac.core.db import js
from bac.science.kernel import execute
from tests.test_agent import chat_and_config
from tests.test_api import login
from tests.test_run_budget import call
from tests.grounding_fixture import publish_reference


def reply(node, blocks=None):
    return {
        "source_ids": [node],
        "blocks": blocks
        or [
            {"type": "text", "text": "نحلّل الحركة في اتجاهين، مع إهمال مقاومة الهواء."}
        ],
    }


@pytest.mark.asyncio
async def test_unstructured_teaching_is_rejected_then_read_and_corrected(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    seen = []

    class Provider:
        async def stream(self, messages, definitions):
            seen.append(messages)
            step = len(seen)
            if step == 1:
                message = {
                    "role": "assistant",
                    "content": "هذا شرح درس من الذاكرة دون قراءة.",
                }
            elif step == 2:
                assert "REFERENCE_READ_REQUIRED" in messages[-1]["content"]
                message = call("get_section", {"node_id": node}, step)
            else:
                message = call("render_answer", reply(node), step)
            yield {"type": "result", "message": message}

    services.chat_factory = lambda cfg, key: Provider()
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرحلي القذف بسرعة ابتدائية غير شاقولية")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert len(seen) == 3
    saved = services.db.one(
        "SELECT content,sources FROM messages WHERE role='assistant'"
    )
    assert "من الذاكرة" not in saved["content"]
    assert json.loads(saved["sources"])[0]["node_id"] == node
    assert services.db.rows("SELECT * FROM run_events WHERE type='answer_rejected'")


@pytest.mark.asyncio
async def test_search_is_not_a_read_and_no_source_means_clarification(services):
    user, chat = chat_and_config(services)
    seen = []

    class Provider:
        async def stream(self, messages, definitions):
            seen.append(messages)
            step = len(seen)
            message = (
                call("search_library", {"query": "القذف"}, step)
                if step == 1
                else call(
                    "render_answer",
                    {"blocks": [{"type": "text", "text": "شرح غير مقروء من المرجع."}]},
                    step,
                )
                if step == 2
                else call(
                    "render_answer",
                    {
                        "response_kind": "clarification",
                        "blocks": [
                            {
                                "type": "text",
                                "text": "هل تستطيع إرسال الفقرة أو المعطيات التي تريد فهمها؟",
                            }
                        ],
                    },
                    step,
                )
            )
            if step == 3:
                assert "REFERENCE_READ_REQUIRED" in messages[-1]["content"]
            yield {"type": "result", "message": message}

    services.chat_factory = lambda cfg, key: Provider()
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح درس حركة القذف")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    saved = services.db.one(
        "SELECT content,sources FROM messages WHERE role='assistant'"
    )
    assert "؟" in saved["content"] and json.loads(saved["sources"]) == []
    assert "شرح غير مقروء" not in saved["content"]


@pytest.mark.asyncio
async def test_retry_restores_actual_source_and_keeps_failed_attempt_in_history_export(
    services,
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)

    class FailAfterRead:
        def __init__(self):
            self.step = 0

        async def stream(self, messages, definitions):
            self.step += 1
            if self.step == 2:
                raise ModelError("TEST_FAILURE_AFTER_ACTUAL_READ")
            yield {
                "type": "result",
                "message": call("get_section", {"node_id": node}, 1),
            }

    services.chat_factory = lambda cfg, key: FailAfterRead()
    engine = AgentEngine(services)
    first = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (first,))["status"]
        == "FAILED"
    )

    class Retry:
        async def stream(self, messages, definitions):
            assert any(
                "Previously loaded untrusted source data" in m.get("content", "")
                for m in messages
                if isinstance(m.get("content"), str)
            )
            yield {"type": "result", "message": call("render_answer", reply(node), 1)}

    services.chat_factory = lambda cfg, key: Retry()
    second = engine.enqueue(chat, user, "اشرح درس القذف", retry=True)
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (second,))["status"]
        == "COMPLETED"
    )
    assert services.db.one(
        "SELECT type FROM run_events WHERE run_id=? AND type='source_reloaded'",
        (second,),
    )
    client = TestClient(create_app(services))
    login(client, "student@example.com")
    for response in [
        client.get("/api/conversations/" + chat).json(),
        client.get(f"/api/conversations/{chat}/export").json(),
        next(
            c
            for c in client.get("/api/privacy/export").json()["conversations"]
            if c["id"] == chat
        ),
    ]:
        question = next(m for m in response["messages"] if m["role"] == "user")
        answer = next(m for m in response["messages"] if m["role"] == "assistant")
        assert question["previous_activities"][0]["run_id"] == first
        assert question["previous_activities"][0]["status"] == "unavailable"
        assert answer["activity"]["run_id"] == second
        assert any(
            i["label"] == "مراجعة المعلومات السابقة"
            for i in answer["activity"]["items"]
        )
        assert "TEST_FAILURE" not in js(response)


@pytest.mark.asyncio
async def test_graph_error_is_actionable_and_corrected_with_grounded_reply(
    services, monkeypatch
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    seen = []
    # Execute fixed trusted fixture code, never incoming arbitrary model code.
    from bac.science.python_child import compute
    from bac.science.python_contract import validate_output
    from bac.science.python_runner import PythonRunner

    code = 'ts = [i/10 for i in range(21)]\nys = [10-9.8*t for t in ts]\nemit("chart", {"title":"مثال عددي توضيحي","x_label":"t (s)","y_label":"vy (m/s)","kind":"line","series":[{"label":"vy","x":ts,"y":ys}]})'
    good = {"code": code}

    def fixed_broker_result(self, args):
        assert args["code"] == code
        return validate_output(
            compute({"code": code, "inputs": {}, "limits": {"output_chars": 16000}})
        )

    monkeypatch.setattr(PythonRunner, "execute", fixed_broker_result)

    class Provider:
        async def stream(self, messages, definitions):
            seen.append(messages)
            step = len(seen)
            if step == 1:
                message = call("get_section", {"node_id": node}, step)
            elif step == 2:
                message = call("run_python", {"inputs": {}}, step)
            elif step == 3:
                feedback = json.loads(messages[-1]["content"])
                assert "code" in {i["field"] for i in feedback["issues"]}
                assert "import sympy" in feedback["example"]["code"]
                message = call("run_python", good, step)
            else:
                result = json.loads(messages[-1]["content"])
                message = call(
                    "render_answer",
                    reply(
                        node,
                        [
                            {
                                "type": "text",
                                "text": "هذا مثال توضيحي باختيار سرعة شاقولية ابتدائية 10 m/s، وليس معطيات مفروضة من الدرس.",
                            },
                            {"type": "graph", "result_id": result["result_id"]},
                        ],
                    ),
                    step,
                )
            yield {"type": "result", "message": message}

    services.chat_factory = lambda cfg, key: Provider()
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "ارسم علاقة السرعة والتسارع في درس القذف")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    messages = services.db.rows(
        "SELECT * FROM messages WHERE conversation_id=?", (chat,)
    )
    messages = attach_activity(services.db, chat, user["id"], messages)
    states = [
        i["state"] for i in messages[-1]["activity"]["items"] if i["kind"] == "math"
    ]
    assert states == ["unavailable", "done"]
    blocks = json.loads(messages[-1]["blocks"])
    graph = next(b for b in blocks if b["type"] == "graph")
    ys = graph["result"]["output"]["chart"]["series"][0]["y"]
    assert ys[0] == 10 and abs(ys[-1] + 9.6) < 1e-9


@pytest.mark.asyncio
async def test_structured_previous_equations_are_in_follow_up_context(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    engine = AgentEngine(services)

    class Initial:
        def __init__(self):
            self.step = 0

        async def stream(self, messages, definitions):
            self.step += 1
            yield {
                "type": "result",
                "message": call("get_section", {"node_id": node}, 1)
                if self.step == 1
                else call(
                    "render_answer",
                    reply(node, [{"type": "equation", "latex": "v_y=10-9.8t"}]),
                    2,
                ),
            }

    services.chat_factory = lambda cfg, key: Initial()
    first = engine.enqueue(chat, user, "اشرح درس القذف")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (first,))["status"]
        == "COMPLETED"
    )

    class Follow:
        async def stream(self, messages, definitions):
            previous = [m["content"] for m in messages if m["role"] == "assistant"]
            assert any("v_y=10-9.8t" in value for value in previous)
            yield {"type": "result", "message": call("render_answer", reply(node), 1)}

    services.chat_factory = lambda cfg, key: Follow()
    second = engine.enqueue(chat, user, "ارسم لهذه الحالة")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (second,))["status"]
        == "COMPLETED"
    )


def test_teaching_requires_delivered_credit_not_just_registered_source(services):
    user, chat = chat_and_config(services)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح الدرس")
    tools = Tools(services, user, chat, rid)
    from bac.agent.grounding import require_grounding
    from bac.agent.models import Answer

    answer = Answer.model_validate(reply("known-but-not-delivered"))
    tools.sources["known-but-not-delivered"] = {}
    with pytest.raises(ValueError, match="REFERENCE_READ_REQUIRED"):
        require_grounding(answer, tools)
    tools.delivered_sources.add("known-but-not-delivered")
    require_grounding(answer, tools)


@pytest.mark.parametrize(
    "args",
    [
        {
            "response_kind": "conversation",
            "blocks": [{"type": "text", "text": "شرح قصير."}],
        },
        {
            "response_kind": "clarification",
            "blocks": [{"type": "equation", "latex": "v=gt"}],
        },
        {
            "response_kind": "clarification",
            "blocks": [{"type": "text", "text": "شرح بلا سؤال."}],
        },
        {"response_kind": "refusal", "blocks": [{"type": "text", "text": "x" * 601}]},
        {
            "response_kind": "clarification",
            "blocks": [{"type": "text", "text": "ما المعطيات؟"}],
            "warnings": ["شرح إضافي يحاول تجاوز شرط القراءة."],
        },
        {"response_kind": "calculation", "blocks": [{"type": "text", "text": "شرح."}]},
    ],
)
def test_non_teaching_modes_cannot_silently_bypass_guard(services, args):
    user, chat = chat_and_config(services)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح درس القذف")
    tools = Tools(services, user, chat, rid)
    tools.question = tools.study_context = "اشرح درس القذف"
    with pytest.raises(ValueError):
        tools.answer(args)


def test_parameterized_velocity_and_constant_acceleration_and_domain_exclusions():
    common = {
        "variable": "t",
        "lower": 0,
        "upper": 2,
        "samples": 21,
        "title": "Illustration",
    }
    v = execute(
        "plot_function",
        common
        | {
            "expression": "v0y-g*t",
            "values": {"v0y": "10", "g": "9.8"},
            "y_label": "velocity (m/s)",
        },
    )
    a = execute(
        "plot_function",
        common
        | {
            "expression": "-g",
            "values": {"g": "9.8"},
            "y_label": "acceleration (m/s^2)",
        },
    )
    assert v["chart"]["series"][0]["y"][0] == 10
    assert set(a["chart"]["series"][0]["y"]) == {-9.8}
    hole = execute(
        "plot_function",
        common | {"lower": -1, "expression": "k*t/t", "values": {"k": "2"}},
    )
    assert len(hole["chart"]["series"]) == 2
    assert all(x != 0 for s in hole["chart"]["series"] for x in s["x"])
    with pytest.raises(ValueError, match="plotting variable"):
        execute("plot_function", common | {"expression": "t", "values": {"t": "2"}})
    with pytest.raises(ValueError, match="constant"):
        execute("plot_function", common | {"expression": "g*t", "values": {"g": "u"}})
