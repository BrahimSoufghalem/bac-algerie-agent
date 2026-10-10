"""Local mocked transports: memory/cost-path regressions, not LLM accuracy claims."""

import json

import httpx
import pytest

from bac.agent.engine import AgentEngine
from bac.agent.full_index import FullIndexCoordinator, build_catalog
from bac.agent.tools import Tools
from bac.core.db import js, uid
from tests.grounding_fixture import publish_reference
from tests.test_agent import chat_and_config
from tests.test_full_index_router import response, selector


@pytest.mark.asyncio
async def test_followup_reuses_same_authorized_version_without_second_verifier(
    services,
):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    row = selector(services)
    _, mapping = build_catalog(services)
    alias = next(a for a, n in mapping.items() if n["id"] == node)
    seen = []

    def handler(req):
        body = json.loads(req.content)
        name = body["tools"][0]["functionDeclarations"][0]["name"]
        data = json.loads(body["contents"][0]["parts"][0]["text"])
        seen.append((name, data))
        if name == "route_sections":
            return response(
                name,
                {
                    "status": "read",
                    "goals": [{"goal": "projectile", "ids": [alias]}],
                    "question": "",
                },
            )
        return response(name, {"status": "read", "ids": [alias], "question": ""})

    services.selector_transport = httpx.MockTransport(handler)
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, "اشرح القذف")
    run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    coordinator = FullIndexCoordinator(services, row)
    await coordinator.prepare(run, Tools(services, user, chat, rid), "اشرح القذف")
    # New Tools instance represents a subsequent user message/process, not in-memory carryover.
    fresh = Tools(services, user, chat, rid)
    result = await coordinator.prepare(run, fresh, "مفهمتش النقطة الثانية")
    assert result["node"]["id"] == node
    assert [name for name, _ in seen] == [
        "route_sections",
        "route_sections",
    ]
    assert seen[-1][1]["available_read_references"][0]["id"] == alias
    assert node in fresh.sources


def test_router_context_contains_previous_answer_in_chronological_order_once(services):
    user, chat = chat_and_config(services)
    engine = AgentEngine(services)
    for i, (role, content, blocks) in enumerate(
        [
            ("user", "اشرح السرعة", []),
            (
                "assistant",
                "1. المركبة الأفقية ثابتة. 2. المركبة العمودية تتغير.",
                [{"type": "equation", "latex": "v_y=v_0y-g*t"}],
            ),
        ]
    ):
        services.db.execute(
            "INSERT INTO messages(id,conversation_id,role,content,blocks,created_at) VALUES(?,?,?,?,?,?)",
            (uid("message"), chat, role, content, js(blocks), i + 1),
        )
    rid = engine.enqueue(chat, user, "مفهمتش النقطة الثانية")
    run = services.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))
    tools = Tools(services, user, chat, rid)
    engine.context(run, tools, user, restore_sources=False)
    assert [h["role"] for h in tools.router_history] == ["user", "assistant"]
    assert "المركبة العمودية" in tools.router_history[-1]["content"]
    assert "v_y=v_0y-g*t" in tools.router_history[-1]["content"]
    assert "مفهمتش النقطة الثانية" not in js(tools.router_history)
    assert tools.question == "مفهمتش النقطة الثانية"


def test_whole_turn_eviction_keeps_current_question_and_reference():
    from types import SimpleNamespace
    from bac.agent.memory import fit_history

    old = {"role": "user", "content": "old " * 30}
    reply = {"role": "assistant", "content": "old answer " * 30}
    now = {"role": "user", "content": "current question"}
    reference = {"role": "user", "content": "actual immutable reference"}
    system = {"role": "system", "content": "policy"}
    messages = [system, reference, old, reply, now]
    tools = SimpleNamespace(history_messages=[old, reply, now], current_message=now)
    limit = sum(len(js(m)) for m in [system, reference, now])
    fit_history(messages, tools, limit)
    assert messages == [system, reference, now]
    from bac.agent.provider import ModelError

    with pytest.raises(ModelError, match="CONTEXT_BUDGET_EXCEEDED"):
        fit_history(messages, tools, limit - 1)
    assert reference in messages and now in messages


@pytest.mark.parametrize(
    "mutation",
    [
        "stale_version",
        "archived",
        "foreign_subject",
        "foreign_track",
        "partial_read",
        "another_chat",
    ],
)
@pytest.mark.asyncio
async def test_reuse_revalidates_publication_scope_and_read_extent(services, mutation):
    from bac.agent.memory import reusable_references

    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    payload = tools.load(node)
    assert "error" not in payload
    if mutation == "stale_version":
        services.db.execute("UPDATE loaded_context SET version_id=?", ("stale",))
    elif mutation == "archived":
        services.db.execute("UPDATE documents SET status='ARCHIVED'")
    elif mutation == "foreign_subject":
        services.db.execute("UPDATE documents SET subject='mathematics'")
    elif mutation == "foreign_track":
        services.db.execute(
            "UPDATE documents SET track='foreign_languages',metadata=json_set(metadata,'$.tracks',json('[\"foreign_languages\"]'))"
        )
    elif mutation == "partial_read":
        services.db.execute("UPDATE loaded_context SET scope='part'")
    else:
        other_chat = uid("chat")
        services.db.execute(
            "INSERT INTO conversations(id,user_id,title,created_at,updated_at,study_subject) VALUES(?,?,?,?,?,?)",
            (other_chat, user["id"], "Other chat", 1, 1, "physics"),
        )
        chat = other_chat
        tools = Tools(services, user, chat)
    _, mapping = build_catalog(services, study_scope=tools.study_scope)
    assert reusable_references(services, Tools(services, user, chat), mapping) == {}


@pytest.mark.asyncio
async def test_stable_persistent_ids_survive_catalogue_alias_changes(services):
    from bac.agent.memory import reusable_references

    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    tools.load(node)
    _, mapping = build_catalog(services, study_scope=tools.study_scope)
    original = next(n for n in mapping.values() if n["id"] == node)
    assert list(reusable_references(services, tools, {"S999": original})) == ["S999"]
    # Atomic task bundles are deliberately NOT eligible for verification bypass.
    for kind in ["exam", "exercise_collection", "unit", "book"]:
        assert not reusable_references(
            services, tools, {"S999": original | {"kind": kind}}
        )


@pytest.mark.asyncio
async def test_no_new_decision_does_not_credit_or_send_previous_source(services):
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    row = selector(services)
    Tools(services, user, chat).load(node)
    services.selector_transport = httpx.MockTransport(
        lambda req: response(
            "route_sections", {"status": "no_new", "goals": [], "question": ""}
        )
    )
    run = {"user_id": user["id"], "id": None}
    tools = Tools(services, user, chat)
    assert await FullIndexCoordinator(services, row).prepare(run, tools, "شكرا") is None
    assert not tools.sources and not tools.delivered_sources
    assert len(services.db.rows("SELECT * FROM model_usage")) == 1


@pytest.mark.asyncio
async def test_24_turn_cost_path_reuses_body_and_preserves_wire_prefix(services):
    """A scripted 24-turn integration trace, NOT a score for any real LLM."""
    from bac.agent.provider import OpenAIChat
    from dataclasses import replace

    services.settings = replace(services.settings, max_daily_requests=100)
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    _, mapping = build_catalog(services)
    alias = next(a for a, n in mapping.items() if n["id"] == node)
    router_calls, teacher_calls = [], []

    def route(req):
        body = json.loads(req.content)
        name = body["tools"][0]["functionDeclarations"][0]["name"]
        text = body["contents"][0]["parts"][0]["text"]
        data = json.loads(text)
        router_calls.append((name, data, text))
        if name == "route_sections":
            assert next(iter(data)) == "complete_book_index"
            if len(teacher_calls):
                assert data["recent_dialogue"][-1]["role"] == "assistant"
                assert len(data["recent_dialogue"]) <= 4
                assert len(js(data["recent_dialogue"])) <= 6010
                assert data["student_request"] not in js(data["recent_dialogue"])
            return response(
                name,
                {
                    "status": "read",
                    "goals": [{"goal": "projectile", "ids": [alias]}],
                    "question": "",
                },
            )
        assert next(iter(data)) == "actual_read_sources"
        return response(name, {"status": "read", "ids": [alias], "question": ""})

    def teach(req):
        body = json.loads(req.content)
        teacher_calls.append(body)
        assert body["messages"][-1]["role"] == "user"
        assert not any(
            m.get("content", "").startswith("Server execution state")
            for m in body["messages"]
        )
        assert (
            "قذف" in body["messages"][-1]["content"]
            or "متابعة رقم" in body["messages"][-1]["content"]
        )
        assert not any("Server remaining time:" in js(m) for m in body["messages"])
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
                                    "id": "answer",
                                    "type": "function",
                                    "function": {
                                        "name": "render_answer",
                                        "arguments": js(
                                            {
                                                "response_kind": "teaching",
                                                "source_ids": [node],
                                                "blocks": [
                                                    {
                                                        "type": "text",
                                                        "text": "1. ندرس الحركة أفقيا. 2. ندرس تغير الحركة عموديا.",
                                                    }
                                                ],
                                            }
                                        ),
                                    },
                                }
                            ],
                        },
                    }
                ],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
        )

    services.selector_transport = httpx.MockTransport(route)
    services.chat_factory = lambda cfg, key: OpenAIChat(
        cfg, key, transport=httpx.MockTransport(teach)
    )
    engine = AgentEngine(services)
    for i in range(24):
        question = (
            "اشرح القذف"
            if i == 0
            else f"فسر لي النقطة الثانية بالدارجة، متابعة رقم {i}"
        )
        rid = engine.enqueue(chat, user, question)
        await engine.process(engine.claim())
        assert (
            services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))[
                "status"
            ]
            == "COMPLETED"
        )
    names = [name for name, _, _ in router_calls]
    assert names.count("route_sections") == 24
    assert names.count("verify_sections") == 0
    assert len(teacher_calls) == 24
    assert (
        len(services.db.rows("SELECT * FROM model_usage")) == 48
    )  # old path: 72 calls
    first = teacher_calls[0]
    for body in teacher_calls[1:]:
        assert body["tools"] == first["tools"]
        assert body["messages"][:3] == first["messages"][:3]
    # No invented cache hit measurements when the mocked provider did not report them.
    assert all(
        r["cached_tokens"] is None
        for r in services.db.rows("SELECT * FROM model_usage")
    )
    assert len(services.db.rows("SELECT * FROM loaded_context")) == 1


@pytest.mark.parametrize(
    "usage,expected",
    [
        (
            {
                "prompt_tokens": 100,
                "prompt_cache_hit_tokens": 70,
                "prompt_cache_miss_tokens": 30,
            },
            70,
        ),
        ({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 70}}, 70),
        ({"prompt_tokens": 100}, None),
        (
            {
                "prompt_tokens": 100,
                "prompt_cache_hit_tokens": 0,
                "prompt_cache_miss_tokens": 100,
            },
            0,
        ),
        ({"prompt_tokens": 100, "prompt_cache_hit_tokens": 101}, None),
        ({"prompt_tokens": 100, "prompt_cache_hit_tokens": True}, None),
        ({"prompt_tokens": 100, "prompt_cache_hit_tokens": "70"}, None),
        (
            {
                "prompt_tokens": 100,
                "prompt_cache_hit_tokens": 70,
                "prompt_cache_miss_tokens": 31,
            },
            None,
        ),
        (
            {
                "prompt_tokens": 100,
                "prompt_tokens_details": {"cached_tokens": 30},
                "prompt_cache_hit_tokens": 70,
            },
            None,
        ),
    ],
)
def test_cache_accounting_uses_only_consistent_provider_measurements(usage, expected):
    from bac.learning.usage import reported_cache_tokens

    assert reported_cache_tokens(usage) == expected


@pytest.mark.asyncio
async def test_mixed_existing_and_new_content_still_gets_body_verification(services):
    """Changing the request is not a reason to deliver only old evidence."""
    node = await publish_reference(services)
    user, chat = chat_and_config(services)
    row = selector(services)
    tools = Tools(services, user, chat)
    tools.load(node)
    source = services.db.one("SELECT * FROM published_nodes WHERE id=?", (node,))
    new_node = uid("new_lesson")
    path = "memory-extra.md"
    services.store.write(
        path, b"New controlled reference body for a distinct requested goal."
    )
    source.update(
        id=new_node,
        title="New controlled reference",
        start_order=source["end_order"] + 1,
        end_order=source["end_order"] + 2,
        content_file=path,
    )
    columns = ",".join(source)
    services.db.execute(
        f"INSERT INTO published_nodes({columns}) VALUES({','.join('?' for _ in source)})",
        tuple(source.values()),
    )
    _, mapping = build_catalog(services, study_scope=tools.study_scope)
    aliases = [a for a, n in mapping.items() if n["id"] in {node, new_node}]
    calls = []

    def handler(req):
        body = json.loads(req.content)
        name = body["tools"][0]["functionDeclarations"][0]["name"]
        calls.append(name)
        if name == "route_sections":
            return response(
                name,
                {
                    "status": "read",
                    "goals": [{"goal": "explicit comparison", "ids": aliases}],
                    "question": "",
                },
            )
        data = json.loads(body["contents"][0]["parts"][0]["text"])
        assert len(data["actual_read_sources"]) == 2
        return response(name, {"status": "read", "ids": aliases, "question": ""})

    services.selector_transport = httpx.MockTransport(handler)
    result = await FullIndexCoordinator(services, row).prepare(
        {"user_id": user["id"], "id": None},
        Tools(services, user, chat),
        "Compare both concepts",
    )
    assert calls == ["route_sections"]
    assert {p["node"]["id"] for p in result["selected_references"]} == {node, new_node}


def test_tail_final_signal_is_not_hoisted_into_native_anthropic_system():
    from bac.agent.anthropic import messages_for_anthropic

    policy = {"role": "system", "content": "stable policy"}
    reference = {"role": "user", "content": "untrusted reference"}
    question = {"role": "user", "content": "actual learning request"}
    final = {"role": "user", "content": "Server execution state: FINAL ROUND"}
    first_system, first_messages = messages_for_anthropic([policy, reference, question])
    final_system, final_messages = messages_for_anthropic(
        [policy, reference, question, final]
    )
    assert first_system == final_system == "stable policy"
    assert final_messages[0]["content"][:2] == first_messages[0]["content"]


@pytest.mark.parametrize(
    "base,expected",
    [
        ("https://api.deepseek.com/v1", True),
        ("https://api.openai.com/v1", True),
        ("https://intermediary.invalid/v1", False),
        ("https://api.deepseek.com.attacker.invalid/v1", False),
        ("https://api.deepseek.com:444/v1", False),
        ("https://user:password@api.deepseek.com/v1", False),
    ],
)
def test_cache_capability_detection_does_not_guess_intermediary_support(base, expected):
    from bac.agent.compat import automatic_prefix_cache

    assert automatic_prefix_cache(base) is expected


def test_large_image_transport_does_not_evict_question_or_count_as_text_tokens():
    from types import SimpleNamespace
    from bac.agent.memory import fit_history, message_chars

    question = {"role": "user", "content": "Explain this diagram"}
    image = {
        "role": "user",
        "content": [
            {"type": "text", "text": "model-only pixels"},
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + "x" * 200000},
            },
        ],
    }
    tools = SimpleNamespace(history_messages=[question], current_message=question)
    messages = [question, image]
    assert message_chars(image) < 200
    fit_history(messages, tools, 300)
    assert messages == [question, image]
    assert len(image["content"][1]["image_url"]["url"]) > 200000


@pytest.mark.asyncio
async def test_essential_repair_keeps_original_current_question_in_router_context(
    services,
):
    from tests.test_run_budget import call

    await publish_reference(services)
    user, chat = chat_and_config(services)
    selector(services)
    _, mapping = build_catalog(services)
    alias = next(a for a, n in mapping.items() if n["kind"] == "lesson")
    original_question = "اشرح القذف وقارن المركبتين"
    routes = []

    def route(req):
        body = json.loads(req.content)
        name = body["tools"][0]["functionDeclarations"][0]["name"]
        data = json.loads(body["contents"][0]["parts"][0]["text"])
        if name == "verify_sections":
            return response(name, {"status": "read", "ids": [alias], "question": ""})
        routes.append(data)
        if len(routes) == 1:
            return response(
                name,
                {
                    "status": "read",
                    "goals": [{"goal": "projectile", "ids": [alias]}],
                    "question": "",
                },
            )
        assert data["recent_dialogue"][-1] == {
            "role": "user",
            "content": original_question,
        }
        assert data["student_request"] == "المرجع المكمل"
        return response(
            name,
            {
                "status": "clarify",
                "goals": [],
                "question": "ما المفهوم الآخر الذي تقصده؟",
            },
        )

    services.selector_transport = httpx.MockTransport(route)

    class Teacher:
        def __init__(self):
            self.steps = 0

        async def stream(self, messages, tools):
            self.steps += 1
            if self.steps == 1:
                message = call(
                    "essential_context",
                    {
                        "importance": "essential",
                        "query": "المرجع المكمل",
                        "reason": "Missing content for the current comparison",
                    },
                    self.steps,
                )
            else:
                message = call(
                    "render_answer",
                    {
                        "response_kind": "clarification",
                        "source_ids": [],
                        "blocks": [
                            {"type": "text", "text": "ما المفهوم الآخر الذي تقصده؟"}
                        ],
                    },
                    self.steps,
                )
            yield {"type": "result", "message": message}

    teacher = Teacher()
    services.chat_factory = lambda cfg, key: teacher
    engine = AgentEngine(services)
    rid = engine.enqueue(chat, user, original_question)
    await engine.process(engine.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (rid,))["status"]
        == "COMPLETED"
    )
    assert len(routes) == teacher.steps == 2
