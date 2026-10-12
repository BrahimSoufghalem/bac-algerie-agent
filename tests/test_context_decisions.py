"""Scripted safety/path tests; not a live LLM semantic accuracy benchmark."""

import json
from dataclasses import replace
import httpx
import pytest
from bac.agent.context_decision import parse_assessment
from bac.agent.engine import AgentEngine
from bac.agent.full_index import build_catalog
from bac.agent.provider import ModelError
from bac.agent.tools import Tools
from bac.core.db import js
from bac.learning.usage import report
from tests.grounding_fixture import publish_reference
from tests.test_agent import chat_and_config
from tests.test_full_index_router import response, selector


def call(name, args, id_="call"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": id_,
                "type": "function",
                "function": {"name": name, "arguments": js(args)},
            }
        ],
    }


def answer(ids, text="نشرح الفكرة الحالية مع شروطها خطوة بخطوة.", kind="teaching"):
    return call(
        "render_answer",
        {
            "response_kind": kind,
            "source_ids": ids,
            "blocks": [{"type": "text", "text": text}],
        },
    )


def assessment_state(messages):
    state = {}
    for message in messages[1:]:
        state.update(json.loads(message["content"].split("\n", 1)[1]))
    return state


def supported_decision(ids, messages):
    """Explicit synthetic support, not an LLM semantic benchmark."""
    state = assessment_state(messages)
    bodies = state["actual_source_bodies"]
    aliases = {sid: alias for alias, sid in state["reference_choices"].items()}
    return {"requirements": [{"id":"goal", "kind":"goal", "description":"synthetic current goal"}, {"id":"rule", "kind":"rule", "description":"synthetic applicable rule"}], "decision": "sufficient", "source_ids": [aliases[sid] for sid in ids], "gaps": [],
            "coverage": [{"source_id": aliases[sid], "goal": "synthetic current task support",
                          "role": "current_goal", "requirement_ids":["goal", "rule"], "evidence_id": aliases[sid] + ":E1"}
                         for sid in ids if sid in bodies]}



class Tutor:
    def __init__(self, decisions, answers):
        self.decisions = iter(decisions)
        self.answers = iter(answers)
        self.assessments = []
        self.work = []

    async def decision_stream(self, messages, tools):
        assert [t["function"]["name"] for t in tools] == ["assess_context"]
        self.assessments.append(messages)
        state = assessment_state(messages)
        if state["assessment_stage"] != "initial":
            decision, ids = "sufficient", list(state["actual_source_bodies"])
        else:
            decision, ids = next(self.decisions)
        args = supported_decision(ids, messages) if decision == "sufficient" and all(sid in state["actual_source_bodies"] for sid in ids) else {"decision": decision, "source_ids": ids}
        yield {"type": "delta", "text": "PRIVATE ASSESSMENT MUST NOT STREAM"}
        yield {"type": "usage", "data": {"prompt_tokens": 41, "completion_tokens": 9}}
        yield {
            "type": "result",
            "message": call(
                "assess_context", args, "decision"
            ),
        }

    async def stream(self, messages, tools):
        self.work.append(messages)
        result = next(self.answers)
        yield {"type": "usage", "data": {"prompt_tokens": 100, "completion_tokens": 20}}
        yield {"type": "result", "message": result}


async def setup(s, second=False):
    node = await publish_reference(s)
    other = None
    if second:
        other = await publish_reference(s, "arithmetic")
        s.db.execute(
            "UPDATE documents SET subject='physics' WHERE id=(SELECT document_id FROM published_nodes WHERE id=?)",
            (other,),
        )
    user, chat = chat_and_config(s)
    selector(s)
    _, mapping = build_catalog(s)
    aliases = {n["id"]: a for a, n in mapping.items()}
    return node, other, user, chat, aliases


def router(s, aliases, plans):
    calls = []
    plans = iter(plans)

    def handle(req):
        data = json.loads(json.loads(req.content)["contents"][0]["parts"][0]["text"])
        calls.append(data)
        plan = next(plans)
        if isinstance(plan, dict):
            return response("route_sections", plan)
        return response(
            "route_sections",
            {
                "status": "read",
                "goals": [{"goal": "current task", "ids": [aliases[n] for n in plan]}],
                "question": "",
            },
        )

    s.selector_transport = httpx.MockTransport(handle)
    return calls


async def run(s, user, chat, question):
    engine = AgentEngine(s)
    rid = engine.enqueue(chat, user, question)
    await engine.process(engine.claim())
    return s.db.one("SELECT * FROM agent_runs WHERE id=?", (rid,))


@pytest.mark.asyncio
async def test_first_reference_then_second_and_n_followups_do_not_route_by_default(
    services,
):
    s = services
    s.settings = replace(s.settings, max_daily_requests=100)
    node, _, u, c, aliases = await setup(s)
    routes = router(s, aliases, [[node]])
    tutor = Tutor(
        [("missing_reference", [])] + [("sufficient", [node])] * 11,
        [answer([node])] * 12,
    )
    s.chat_factory = lambda cfg, key: tutor
    for i in range(12):
        state = await run(
            s, u, c, "اشرح القذف" if i == 0 else f"وضح نفس الفكرة أكثر، متابعة {i}"
        )
        assert state["status"] == "COMPLETED", state
    assert len(routes) == 1 and len(tutor.assessments) == 13 and len(tutor.work) == 12
    assert "complete_book_index" not in js(tutor.assessments)
    assert "Initial components" in js(
        tutor.assessments[-1]
    )  # Actual body, not just title.
    stats = report(s, u)["context_decisions"]
    assert (
        stats["messages"] == 12
        and stats["router_requests"] == 1
        and stats["reused_current"] == 11
    )
    assert stats["reuse_ratio"] == 11 / 12
    assert len(s.db.rows("SELECT * FROM model_usage")) == 26
    assert not any(
        "PRIVATE ASSESSMENT" in e["payload"]
        for e in s.db.rows("SELECT payload FROM run_events")
    )
    ledger = s.db.one(
        "SELECT * FROM run_reference_state WHERE run_id=? AND source_id=?",
        (state["id"], node),
    )
    assert (
        ledger["loaded"]
        == ledger["delivered"]
        == ledger["active"]
        == ledger["used"]
        == 1
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("question", ["مرحبا", "كيف أستخدم مسار؟"])
async def test_first_general_allowed_never_routes(services, question):
    s = services
    _, _, u, c, aliases = await setup(s)
    routes = router(s, aliases, [])
    tutor = Tutor(
        [("general_allowed", [])],
        [answer([], "أهلا بك في مسار. اختر المادة ثم أرسل سؤالك.", "conversation")],
    )
    s.chat_factory = lambda cfg, key: tutor
    assert (await run(s, u, c, question))["status"] == "COMPLETED"
    assert not routes and not tutor.work and not tutor.assessments


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["wrong_subject", "out_of_scope"])
async def test_redirection_does_not_run_teacher_or_router(services, decision):
    s = services
    _, _, u, c, aliases = await setup(s)
    routes = router(s, aliases, [])
    tutor = Tutor([(decision, [])], [])
    s.chat_factory = lambda cfg, key: tutor
    assert (await run(s, u, c, "اشرح التاريخ"))["status"] == "COMPLETED"
    assert not routes and not tutor.work


@pytest.mark.asyncio
@pytest.mark.parametrize("retain_old", [True, False])
async def test_new_reference_can_retain_prerequisite_or_deactivate_previous(
    services, retain_old
):
    s = services
    n, other, u, c, aliases = await setup(s, second=True)
    final = [n, other] if retain_old else [other]
    routes = router(s, aliases, [[n], final])
    tutor = Tutor(
        [("missing_reference", []), ("missing_reference", [])],
        [answer([n]), answer(final)],
    )
    s.chat_factory = lambda cfg, key: tutor
    assert (await run(s, u, c, "اشرح القذف"))["status"] == "COMPLETED"
    state = await run(
        s,
        u,
        c,
        "انتقل إلى الموضوع الجديد"
        if not retain_old
        else "أكمل مع المفهوم السابق والمفهوم الجديد",
    )
    assert state["status"] == "COMPLETED", state
    assert len(routes) == 2
    prior = routes[-1]["available_read_references"]
    assert any(
        r["id"] == aliases[n] and r["active"] and r["delivered_in_current_context"]
        for r in prior
    )
    rows = s.db.rows(
        "SELECT node_id,active FROM loaded_context WHERE conversation_id=?", (c,)
    )
    assert len(rows) == 2
    assert {r["node_id"]: r["active"] for r in rows} == {n: int(retain_old), other: 1}
    if not retain_old:
        assert "Initial components" not in js(tutor.work[-1])
        # Historical read still exists, but cannot authorize citation after dropping it.
        assert (
            s.db.one(
                "SELECT active FROM run_reference_state WHERE run_id=? AND source_id=?",
                (state["id"], n),
            )["active"]
            == 0
        )


@pytest.mark.asyncio
async def test_uncertain_routes_and_router_clarification_finishes_without_work(
    services,
):
    s = services
    _, _, u, c, aliases = await setup(s)
    routes = router(
        s, aliases, [{"status": "clarify", "goals": [], "question": "أي مفهوم تقصد؟"}]
    )
    tutor = Tutor([("uncertain", [])], [])
    s.chat_factory = lambda cfg, key: tutor
    assert (await run(s, u, c, "اشرح الحركة"))["status"] == "COMPLETED"
    assert len(routes) == 1 and not tutor.work
    assert (
        s.db.one("SELECT content FROM messages WHERE role='assistant'")["content"]
        == "أي مفهوم تقصد؟"
    )


@pytest.mark.asyncio
async def test_invalid_router_id_fails_closed(services):
    s = services
    _, _, u, c, aliases = await setup(s)
    router(
        s,
        aliases,
        [
            {
                "status": "read",
                "goals": [{"goal": "x", "ids": ["invented"]}],
                "question": "",
            }
        ],
    )
    tutor = Tutor([("missing_reference", [])], [])
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, u, c, "اشرح القذف")
    assert state["status"] == "FAILED" and not tutor.work
    assert not s.db.rows("SELECT * FROM messages WHERE role='assistant'")


@pytest.mark.asyncio
async def test_unloadable_source_keeps_old_active_and_never_claims_read(
    services, monkeypatch
):
    s = services
    n, other, u, c, aliases = await setup(s, second=True)
    Tools(s, u, c).load(n)
    router(s, aliases, [[other]])
    tutor = Tutor([("missing_reference", [])], [])
    s.chat_factory = lambda cfg, key: tutor
    original = Tools.load

    def bad(self, id_, *args, **kwargs):
        if id_ == other:
            return {"error": "MISSING_CONTENT"}
        return original(self, id_, *args, **kwargs)

    monkeypatch.setattr(Tools, "load", bad)
    state = await run(s, u, c, "أحتاج مفهوما جديدا")
    assert state["status"] == "COMPLETED" and not tutor.work  # Safe clarification.
    assert (
        s.db.one("SELECT active FROM loaded_context WHERE node_id=?", (n,))["active"]
        == 1
    )
    row = s.db.one(
        "SELECT * FROM run_reference_state WHERE run_id=? AND source_id=?",
        (state["id"], other),
    )
    assert (
        row["selected"] == 1 and row["loaded"] == row["delivered"] == row["used"] == 0
    )


@pytest.mark.asyncio
async def test_missing_attachment_stops_before_both_models(services):
    s = services
    _, _, u, c, aliases = await setup(s)
    routes = router(s, aliases, [])
    tutor = Tutor([], [])
    s.chat_factory = lambda cfg, key: tutor
    assert (await run(s, u, c, "اشرح الصورة التي أرسلتها"))["status"] == "COMPLETED"
    assert not routes and not tutor.work and not tutor.assessments


@pytest.mark.asyncio
async def test_essential_repair_is_bounded_and_detects_sufficiency_reversal(services):
    s = services
    n, _, u, c, aliases = await setup(s)
    Tools(s, u, c).load(n)
    routes = router(s, aliases, [[n]])
    request = call(
        "essential_context",
        {
            "importance": "essential",
            "query": "الشرط الناقص",
            "reason": "Current request needs a missing prerequisite",
        },
    )
    tutor = Tutor(
        [("sufficient", [n])],
        [request, request, answer([], "هل تحدد الشرط الناقص؟", "clarification")],
    )
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, u, c, "اشرح شرط القذف")
    assert state["status"] == "COMPLETED", state
    assert len(routes) == 1
    stats = s.db.one("SELECT * FROM context_decisions WHERE run_id=?", (state["id"],))
    assert stats["essential_requests"] == stats["sufficiency_gap"] == 1
    assert routes[0]["current_student_request"] == "اشرح شرط القذف"
    assert routes[0]["essential_reference_query"] == "الشرط الناقص"


@pytest.mark.asyncio
async def test_failed_repair_cannot_use_old_sources_as_sufficient(services):
    s = services
    n, _, u, c, aliases = await setup(s)
    Tools(s, u, c).load(n)
    router(s, aliases, [{"status": "no_new", "goals": [], "question": ""}])
    tutor = Tutor(
        [("sufficient", [n])],
        [
            call(
                "essential_context",
                {
                    "importance": "essential",
                    "query": "شرط جديد",
                    "reason": "An essential condition is absent",
                },
            ),
            answer([n]),
            answer([], "هل تكتب الشرط المطلوب؟", "clarification"),
        ],
    )
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, u, c, "اشرح الشرط الجديد")
    assert state["status"] == "COMPLETED", state
    msg = s.db.one("SELECT content,sources FROM messages WHERE role='assistant'")
    assert "هل" in msg["content"] and json.loads(msg["sources"]) == []
    assert s.db.rows("SELECT * FROM run_events WHERE type='answer_rejected'")


@pytest.mark.asyncio
async def test_python_result_ids_and_grounded_final_renderer_still_enforced(
    services, monkeypatch
):
    s = services
    n, _, u, c, aliases = await setup(s)
    Tools(s, u, c).load(n)
    routes = router(s, aliases, [])
    from bac.science.python_runner import PythonRunner

    monkeypatch.setattr(
        PythonRunner,
        "execute",
        lambda self, args: {
            "status": "computed",
            "outputs": {"sum": 5},
            "checks": [{"label":"النتيجة المحسوبة خمسة.", "status":"passed", "evidence":{"observed":5,"expected":5,"relation":"equal","tolerance":0}}],
            "stdout": "",
        },
    )
    class CheckedTutor(Tutor):
        async def stream(self, messages, tools):
            async for event in super().stream(messages,tools):
                if event["type"] == "result" and "نشرح الفكرة" in js(event):
                    rid = next(json.loads(m["content"])["result_id"] for m in reversed(messages) if m["role"] == "tool" and "result_id" in json.loads(m["content"]))
                    event["message"] = call("render_answer", {"response_kind":"teaching", "source_ids":[n], "blocks":[{"type":"text", "text":"النتيجة المحسوبة خمسة."}], "checked_claims":[{"block_index":0,"claim":"النتيجة المحسوبة خمسة.","result_id":rid,"check_index":0}]})
                yield event
    tutor = CheckedTutor(
        [("sufficient", [n])],
        [
            call("run_python", {"code": "emit('sum', 2+3)"}),
            call(
                "render_answer",
                {
                    "response_kind": "teaching",
                    "source_ids": [n],
                    "blocks": [{"type": "graph", "result_id": "invented"}],
                },
            ),
            answer([n]),
        ],
    )
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, u, c, "تحقق حسابيا من المثال في الدرس")
    assert state["status"] == "COMPLETED", state
    assert not routes
    assert (
        len(
            s.db.rows("SELECT * FROM scientific_results WHERE run_id=?", (state["id"],))
        )
        == 1
    )
    assert s.db.rows("SELECT * FROM run_events WHERE type='answer_rejected'")


@pytest.mark.asyncio
async def test_round_ceiling_forbids_more_repair_and_unsafe_final(services):
    s = services
    n, _, u, c, aliases = await setup(s)
    Tools(s, u, c).load(n)
    cfg = s.db.one("SELECT * FROM model_configs")
    config = json.loads(cfg["config"])
    config["main_max_rounds"] = 2
    s.db.execute(
        "UPDATE model_configs SET config=? WHERE id=?", (js(config), cfg["id"])
    )
    router(s, aliases, [])
    request = call("list_my_notes", {})
    tutor = Tutor([("sufficient", [n])], [request, request])
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, u, c, "اشرح القذف")
    assert state["status"] == "FAILED" and state["error"] == "FINAL_ANSWER_REQUIRED"
    assert len(tutor.work) == 2 and len(tutor.assessments) == 1


@pytest.mark.parametrize(
    "decision,ids",
    [
        ("sufficient", []),
        ("sufficient", ["invented"]),
        ("missing_reference", ["known"]),
        ("uncertain", ["known"]),
    ],
)
def test_decision_contract_rejects_false_read_credit(services, decision, ids):
    u, c = chat_and_config(services)
    tools = Tools(services, u, c)
    tools.question = "اشرح درسا"
    with pytest.raises(ModelError, match="INVALID_CONTEXT_DECISION"):
        parse_assessment(
            call("assess_context", {"decision": decision, "source_ids": ids}), tools
        )


@pytest.mark.parametrize("ids", [[], ["known"]])
def test_general_classification_is_not_a_grounding_bypass(services, ids):
    u, c = chat_and_config(services)
    tools = Tools(services, u, c)
    tools.question = "اشرح الاشتقاقية"
    result, _ = parse_assessment(
        call("assess_context", {"decision": "general_allowed", "source_ids": ids}), tools)
    assert result.decision == "uncertain" and not result.source_ids
    assert not tools.coverage_validated


@pytest.mark.asyncio
async def test_router_no_new_still_allows_actual_private_pixels_not_inventory(services):
    from bac.learning.private import PrivateFiles
    from tests.test_learning import png, PrivateScript

    s = services
    _, _, u, c, aliases = await setup(s)
    upload = PrivateFiles(s).add(u, c, "actual.png", png())
    routes = router(s, aliases, [{"status": "no_new", "goals": [], "question": ""}])

    class PrivateTutor(PrivateScript):
        async def decision_stream(self, messages, tools):
            yield {
                "type": "result",
                "message": call(
                    "assess_context", {"decision": "uncertain", "source_ids": []}
                ),
            }

    tutor = PrivateTutor(upload["id"])
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, u, c, "اشرح المرفق الموجود")
    assert state["status"] == "COMPLETED", state
    assert len(routes) == 1 and tutor.saw_pixels
    row = s.db.one("SELECT * FROM run_reference_state WHERE run_id=?", (state["id"],))
    assert row["scope"] == "private" and row["delivered"] == row["used"] == 1
    assert "base64" not in js(s.db.rows("SELECT * FROM run_events"))


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["openai", "anthropic"])
async def test_real_adapters_force_structured_assessment_without_free_text_parser(
    protocol,
):
    from bac.agent.provider import OpenAIChat
    from bac.agent.anthropic import AnthropicChat
    from bac.agent.context_decision import assessment_tool

    bodies = []

    def handler(req):
        body = json.loads(req.content)
        bodies.append(body)
        if protocol == "openai":
            assert body["tool_choice"]["function"]["name"] == "assess_context"
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": call(
                                "assess_context",
                                {"decision": "uncertain", "source_ids": []},
                            ),
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            )
        assert body["tool_choice"] == {"type": "tool", "name": "assess_context"}
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "a",
                    "name": "assess_context",
                    "input": {},
                },
            },
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {
                    "type": "input_json_delta",
                    "partial_json": js({"decision": "uncertain", "source_ids": []}),
                },
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 5},
            },
            {"type": "message_stop"},
        ]
        return httpx.Response(
            200,
            text="".join(
                "event: " + e["type"] + "\ndata: " + js(e) + "\n\n" for e in events
            ),
            headers={"content-type": "text/event-stream"},
        )

    provider = (OpenAIChat if protocol == "openai" else AnthropicChat)(
        {"base_url": "https://example.org/v1", "model": "unchanged"},
        "TEST-ONLY",
        transport=httpx.MockTransport(handler),
    )
    events = [
        e
        async for e in provider.decision_stream(
            [
                {"role": "system", "content": "policy"},
                {"role": "user", "content": "current"},
            ],
            [assessment_tool()],
        )
    ]
    result = next(e["message"] for e in events if e["type"] == "result")
    assert (
        result["tool_calls"][0]["function"]["name"] == "assess_context"
        and len(bodies) == 1
    )


def test_atomic_statement_solution_cannot_be_partially_dropped(services):
    from bac.agent.context_decision import retain

    u, c = chat_and_config(services)
    tools = Tools(services, u, c)
    tools.sources = {
        sid: {"node_id": sid, "version_id": "v", "scope": "bundle"}
        for sid in ["statement", "solution"]
    }
    tools.delivered_sources = {"statement", "solution"}
    tools.atomic_reference_groups = [{"statement", "solution"}]
    message = {"role": "user", "content": "Atomic bundle body"}
    tools.reference_messages[id(message)] = {"statement", "solution"}
    messages = [message]
    retain(tools, ["statement"], messages)
    assert set(tools.sources) == {"statement", "solution"} and messages == [message]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["stale_version", "foreign_subject", "archived"])
async def test_sufficient_cannot_restore_stale_or_unauthorized_publication(
    services, change
):
    s = services
    n, _, u, c, aliases = await setup(s)
    Tools(s, u, c).load(n)
    if change == "stale_version":
        s.db.execute(
            "UPDATE loaded_context SET version_id='stale' WHERE node_id=?", (n,)
        )
    elif change == "foreign_subject":
        s.db.execute("UPDATE documents SET subject='mathematics'")
    else:
        s.db.execute("UPDATE documents SET status='ARCHIVED'")
    routes = router(s, aliases, [{"status": "clarify", "goals": [], "question": "هل تحدد المرجع الصحيح؟"}])
    tutor = Tutor([("sufficient", [n])], [])
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, u, c, "اشرح القذف")
    assert state["status"] == "COMPLETED"
    assert len(routes) <= 1 and not tutor.work
    # Recovery may ask the router once, never restore an unauthorized/stale body on model authority.
    assert n not in assessment_state(tutor.assessments[0])["actual_source_bodies"]



@pytest.mark.asyncio
async def test_upgrade_keeps_legacy_read_ids_dormant_without_reloading_all(services):
    from bac.core.db import DB
    s=services;n,_,u,c,_=await setup(s)
    tools=Tools(s,u,c);tools.load(n)
    original=s.db.one("SELECT node_id,version_id,scope,scope_id FROM loaded_context WHERE conversation_id=?",(c,))
    # Reconstruct the exact pre-012 schema in this disposable database.
    with s.db.tx() as conn:
        conn.execute("DROP TABLE context_decisions")
        conn.execute("DROP TABLE run_reference_state")
        conn.execute("ALTER TABLE loaded_context DROP COLUMN active")
        conn.execute("DELETE FROM migrations WHERE version=12")
    DB(s.db.path)
    old=s.db.one("SELECT * FROM loaded_context WHERE conversation_id=?",(c,))
    assert old["active"]==0
    assert {k:old[k] for k in original}==original
    # The full read ID can still be reloaded/reselected after scope/version validation.
    tools.load(n)
    assert s.db.one("SELECT active FROM loaded_context WHERE node_id=?",(n,))["active"]==1


@pytest.mark.asyncio
async def test_partial_selection_failure_records_loaded_but_not_delivered_or_active(services,monkeypatch):
    s=services;n,other,u,c,aliases=await setup(s,second=True)
    ordered=sorted([n,other],key=lambda node:int(aliases[node][1:]))
    first,failed=ordered
    Tools(s,u,c).load(failed) # Previous active set must survive failed replacement.
    router(s,aliases,[ordered])
    tutor=Tutor([("missing_reference",[])],[]);s.chat_factory=lambda cfg,key:tutor
    original=Tools.load
    def load(self,id_,*args,**kwargs):
        if id_==failed:return {"error":"MISSING_COMPLEMENTARY_CONTENT"}
        return original(self,id_,*args,**kwargs)
    monkeypatch.setattr(Tools,"load",load)
    state=await run(s,u,c,"أحتاج المفهومين معا")
    assert state["status"]=="COMPLETED" and not tutor.work
    row=s.db.one("SELECT * FROM run_reference_state WHERE run_id=? AND source_id=?",(state["id"],first))
    assert row["selected"]==row["loaded"]==1
    assert row["delivered"]==row["active"]==row["used"]==0
    assert s.db.one("SELECT active FROM loaded_context WHERE node_id=?",(failed,))["active"]==1


@pytest.mark.parametrize("question",["ما هو مسار؟ 2+3", "كيف أستخدم مسار؟ ١+٢"])
def test_platform_help_whitelist_cannot_hide_numeric_educational_request(services,question):
    u,c=chat_and_config(services);tools=Tools(services,u,c);tools.question=question
    decision, _ = parse_assessment(call("assess_context", {"decision":"general_allowed", "source_ids":[]}), tools)
    assert decision.decision == "uncertain" and not tools.coverage_validated
