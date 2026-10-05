import json, asyncio, time
import pytest
from bac.core.auth import create_user
from bac.core.db import uid, js
from bac.agent.engine import AgentEngine
from tests.test_library import seeded, process_and_publish


class Scripted:
    def __init__(self, node):
        self.step = 0
        self.node = node

    async def stream(self, messages, tools):
        self.step += 1
        if self.step == 1:
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call1",
                        "type": "function",
                        "function": {
                            "name": "get_lesson_full",
                            "arguments": json.dumps({"node_id": self.node}),
                        },
                    }
                ],
            }
        else:
            msg = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call2",
                        "type": "function",
                        "function": {
                            "name": "render_answer",
                            "arguments": json.dumps(
                                {
                                    "blocks": [
                                        {
                                            "type": "text",
                                            "text": "الحرارة تنتقل بين جسمين.",
                                        },
                                        {"type": "equation", "latex": "Q=mc\\Delta T"},
                                    ],
                                    "source_ids": [self.node],
                                }
                            ),
                        },
                    }
                ],
            }
        yield {"type": "usage", "data": {"prompt_tokens": 10, "completion_tokens": 20}}
        yield {"type": "result", "message": msg}


def chat_and_config(s, subject="physics"):
    user = create_user(s.db, "student@example.com", "Strong-password-1", "Student")
    s.db.execute(
        "UPDATE users SET study_track='experimental_sciences' WHERE id=?", (user,)
    )
    chat = uid("chat")
    s.db.execute(
        "INSERT INTO conversations(id,user_id,title,created_at,updated_at,study_subject) VALUES(?,?,?,?,?,?)",
        (chat, user, "Test", time.time(), time.time(), subject),
    )
    cfg = uid("cfg")
    s.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            cfg,
            "agent",
            js({"base_url": "https://example.org/v1", "model": "fake"}),
            s.vault.encrypt("fake"),
            time.time(),
        ),
    )
    s.db.execute("INSERT OR REPLACE INTO active_models VALUES(?,?)", ("agent", cfg))
    return s.db.one("SELECT * FROM users WHERE id=?", (user,)), chat


@pytest.mark.asyncio
async def test_actual_tool_source_answer_and_usage(services):
    lib, r, owner = seeded(services)
    d = await process_and_publish(services, lib, r, owner)
    node = lib.nodes(d["id"], "lesson")[0]["id"]
    user, chat = chat_and_config(services)
    services.chat_factory = lambda cfg, key: Scripted(node)
    engine = AgentEngine(services)
    id = engine.enqueue(chat, user, "اشرح الحرارة")
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (id,))["status"]
        == "COMPLETED"
    )
    events = services.db.rows("SELECT * FROM run_events WHERE run_id=?", (id,))
    assert any(e["type"] == "tool_start" for e in events)
    payload = json.loads([e for e in events if e["type"] == "answer"][0]["payload"])
    assert payload["sources"][0]["node_id"] == node
    assert len(services.db.rows("SELECT * FROM model_usage")) == 2
    assert all(
        r["cached_tokens"] is None and r["estimated_cost"] is None
        for r in services.db.rows("SELECT * FROM model_usage")
    )


@pytest.mark.asyncio
async def test_step_limit_and_no_fake_success(services):
    user, chat = chat_and_config(services)

    class Loop:
        async def stream(self, *args):
            yield {
                "type": "result",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "x",
                            "type": "function",
                            "function": {
                                "name": "get_section",
                                "arguments": '{"node_id":"missing"}',
                            },
                        }
                    ],
                },
            }

    services.chat_factory = lambda cfg, key: Loop()
    e = AgentEngine(services)
    e.enqueue(chat, user, "Question")
    await e.process(e.claim())
    assert services.db.one("SELECT status,error FROM agent_runs")["status"] == "FAILED"
    assert not services.db.rows("SELECT * FROM messages WHERE role='assistant'")


@pytest.mark.asyncio
async def test_real_cancellation_and_edit_ownership(services):
    user, chat = chat_and_config(services)

    class Slow:
        async def stream(self, *args):
            await asyncio.sleep(5)
            yield {
                "type": "result",
                "message": {"role": "assistant", "content": "Never finish"},
            }

    services.chat_factory = lambda cfg, key: Slow()
    e = AgentEngine(services)
    r = e.enqueue(chat, user, "Question")
    job = e.claim()
    task = asyncio.create_task(e.process(job))
    await asyncio.sleep(0.1)
    services.db.execute("UPDATE agent_runs SET cancel_requested=1 WHERE id=?", (r,))
    await task
    assert services.db.one("SELECT status FROM agent_runs")["status"] == "CANCELLED"
    with pytest.raises(Exception):
        e.enqueue("not-their-chat", user, "Question")


@pytest.mark.asyncio
async def test_retry_reuses_question_and_preserves_old_answer_as_inactive(services):
    lib, r, owner = seeded(services)
    d = await process_and_publish(services, lib, r, owner)
    node = lib.nodes(d["id"], "lesson")[0]["id"]
    user, chat = chat_and_config(services)
    services.chat_factory = lambda cfg, key: Scripted(node)
    e = AgentEngine(services)
    e.enqueue(chat, user, "اشرح الحرارة")
    await e.process(e.claim())
    e.enqueue(chat, user, "اشرح الحرارة", retry=True)
    await e.process(e.claim())
    messages = services.db.rows(
        "SELECT * FROM messages WHERE conversation_id=?", (chat,)
    )
    assert len([m for m in messages if m["role"] == "user"]) == 1
    assert len([m for m in messages if m["role"] == "assistant"]) == 2
    assert len([m for m in messages if m["role"] == "assistant" and m["active"]]) == 1
