"""Public per-answer work summaries, not internal reasoning or tool payloads."""

import json
import pytest
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.agent.engine import AgentEngine
from bac.core.activity import Activity
from bac.core.db import js
from tests.test_agent import chat_and_config
from tests.test_api import login
from tests.test_learning import setup_client


def row(id, type, **payload):
    return {"id": id, "type": type, "payload": js(payload)}


def test_public_work_summary_uses_only_allowlisted_facts():
    projection = Activity("own-run")
    for event in [
        row(1, "queued", label="PRIVATE FILE"),
        row(2, "model_start", label="PRIVATE THOUGHT"),
        row(3, "delta", text="PRIVATE REASONING"),
        row(4, "thought", text="PRIVATE REASONING"),
        row(
            5,
            "tool_start",
            name="get_section",
            label="PRIVATE SOURCE",
            arguments={"node_id": "node_secret"},
        ),
        row(6, "tool_end", name="get_section", success=True, label="PRIVATE SOURCE"),
        row(7, "tool_start", name="verify_calculation", label="PRIVATE TRACE"),
        row(
            8,
            "tool_end",
            name="verify_calculation",
            success=False,
            label="PRIVATE ERROR",
        ),
        row(9, "answer", message_id="hidden-message", sources=["PRIVATE SOURCE"]),
    ]:
        projection.feed(event)
    public = projection.snapshot()
    serialized = js(public)
    for private in [
        "PRIVATE",
        "get_section",
        "verify_calculation",
        "node_secret",
        "arguments",
        "hidden-message",
        "sources",
    ]:
        assert private not in serialized
    assert public["status"] == "completed"
    assert [item["state"] for item in public["items"]] == [
        "done",
        "done",
        "done",
        "unavailable",
        "done",
    ]
    assert "مراجعة المعلومات" in serialized
    assert "مراجعة النتيجة المحددة" in serialized


def test_repeated_invocations_are_distinct_and_errors_never_mark_success():
    projection = Activity("run")
    for event in [
        row(1, "tool_start", name="calculate"),
        row(2, "tool_start", name="calculate"),
        row(3, "tool_end", name="calculate", success=True),
        row(4, "error", code="SECRET_FAILURE", label="PRIVATE"),
    ]:
        projection.feed(event)
    activity = projection.snapshot()
    assert [item["id"] for item in activity["items"]] == ["1", "2", "4"]
    assert [item["state"] for item in activity["items"]] == [
        "done",
        "stopped",
        "unavailable",
    ]
    assert "SECRET" not in js(activity) and "PRIVATE" not in js(activity)
    assert projection.snapshot("INTERRUPTED")["status"] == "unavailable"


class WorkProvider:
    def __init__(self):
        self.step = 0

    async def stream(self, messages, tools):
        self.step += 1
        name, args = (
            ("calculate", {"expression": "2+2"})
            if self.step == 1
            else (
                "render_answer",
                {"blocks": [{"type": "text", "text": "الناتج أربعة."}]},
            )
        )
        yield {
            "type": "result",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": str(self.step),
                        "type": "function",
                        "function": {"name": name, "arguments": js(args)},
                    }
                ],
            },
        }


@pytest.mark.asyncio
async def test_two_answers_keep_their_own_activity_on_history_export_and_reopen(
    services,
):
    user, chat = chat_and_config(services)
    services.chat_factory = lambda config, key: WorkProvider()
    client = TestClient(create_app(services))
    login(client, "student@example.com")
    engine = AgentEngine(services)
    first = engine.enqueue(chat, user, "ما ناتج جمع اثنين واثنين؟")
    await engine.process(engine.claim())
    initial = client.get("/api/conversations/" + chat).json()
    first_answer = next(m for m in initial["messages"] if m["role"] == "assistant")
    saved = first_answer["activity"]
    assert saved["run_id"] == first and saved["status"] == "completed"
    second = engine.enqueue(chat, user, "اشرحه أبسط")
    await engine.process(engine.claim())
    # A new API/controller instance reconstructs persisted summaries, not a shared UI array.
    reopened = TestClient(create_app(services))
    login(reopened, "student@example.com")
    messages = reopened.get("/api/conversations/" + chat).json()["messages"]
    answers = [m for m in messages if m["role"] == "assistant"]
    assert len(answers) == 2
    assert answers[0]["activity"] == saved
    assert answers[1]["activity"]["run_id"] == second
    assert set(item["id"] for item in saved["items"]).isdisjoint(
        item["id"] for item in answers[1]["activity"]["items"]
    )
    exported = reopened.get(f"/api/conversations/{chat}/export").json()["messages"]
    assert [m["activity"] for m in exported if m["role"] == "assistant"] == [
        m["activity"] for m in answers
    ]
    personal = reopened.get("/api/privacy/export").json()
    exported_chat = next(c for c in personal["conversations"] if c["id"] == chat)
    assert (
        next(m for m in exported_chat["messages"] if m["id"] == first_answer["id"])[
            "activity"
        ]
        == saved
    )
    for private in [
        "tool_start",
        "tool_end",
        "calculate",
        "expression",
        "render_answer",
        "inputs",
    ]:
        assert private not in js(messages)
    outsider, _, _ = setup_client(services, email="outsider-activity@test.invalid")
    assert outsider.get("/api/runs/" + first).status_code == 404
    assert outsider.get("/api/conversations/" + chat).status_code == 404


@pytest.mark.asyncio
async def test_replayed_sse_is_ordered_sanitized_and_restores_prior_running_entries(
    services,
):
    user, chat = chat_and_config(services)
    services.chat_factory = lambda config, key: WorkProvider()
    client = TestClient(create_app(services))
    login(client, "student@example.com")
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "ما الناتج؟")
    await engine.process(engine.claim())
    start = services.db.one(
        "SELECT id FROM run_events WHERE run_id=? AND type='tool_start'", (rid,)
    )["id"]
    response = client.get(
        f"/api/runs/{rid}/events", headers={"Last-Event-ID": str(start)}
    )
    packets = [p for p in response.text.split("\n\n") if p.startswith("id:")]
    ids = [int(p.splitlines()[0][4:]) for p in packets]
    assert ids == sorted(set(ids)) and ids[0] > start
    progress = [
        json.loads(p.split("data: ")[1]) for p in packets if "event: progress" in p
    ]
    assert any(
        item["id"] == str(start) and item["state"] == "done"
        for item in progress[0]["items"]
    )
    final = json.loads(
        next(p for p in packets if "event: answer" in p).split("data: ")[1]
    )
    assert final["activity"] == client.get("/api/runs/" + rid).json()["activity"]
    for private in [
        "calculate",
        "tool_start",
        "tool_end",
        "model_start",
        "arguments",
        "reasoning",
        "expression",
    ]:
        assert private not in response.text


def test_cancelled_unanswered_question_retains_its_drawer(services):
    user, chat = chat_and_config(services)
    client = TestClient(create_app(services))
    headers = login(client, "student@example.com")
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "سؤال متوقف")
    assert client.post(f"/api/runs/{rid}/cancel", headers=headers).status_code == 200
    question = client.get("/api/conversations/" + chat).json()["messages"][0]
    assert question["unanswered_activity"]["run_id"] == rid
    assert question["unanswered_activity"]["status"] == "cancelled"
    assert not any(
        item["state"] == "running" for item in question["unanswered_activity"]["items"]
    )
