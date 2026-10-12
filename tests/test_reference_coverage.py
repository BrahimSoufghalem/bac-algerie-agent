"""Deterministic policy/recorded-contract replay, no paid API or accuracy claims."""

import json
from pathlib import Path

import pytest

from bac.agent.context_decision import parse_assessment
from bac.agent.grounding import (
    GENERAL_POLICY,
    deterministic_general_reply,
    general_allowed,
    require_grounding,
)
from bac.agent.models import PresentedAnswer
from bac.agent.tools import Tools
from bac.core.db import js
from tests.test_agent import chat_and_config
from tests.test_context_decisions import Tutor, answer, call, router, run, setup


def support(sid, quote, role="current_goal"):
    return {
        "source_id": sid,
        "quote": quote,
        "role": role,
        "goal": "current concept and necessary hypotheses",
    }


def wire(ids, coverage, gaps=None):
    return call(
        "assess_context",
        {
            "decision": "sufficient",
            "source_ids": ids,
            "coverage": coverage,
            "gaps": gaps or [],
        },
    )


def actual_tools(s, question, bodies, metadata=None):
    user, chat = chat_and_config(s, "mathematics")
    t = Tools(s, user, chat)
    t.question = question
    t.coordinated = True
    t.sources = {sid: {"source_id": sid, "node_id": sid} for sid in bodies}
    t.delivered_sources.update(bodies)
    t.source_evidence = {
        sid: {"body": body, "local_metadata": (metadata or {}).get(sid, "")}
        for sid, body in bodies.items()
    }
    return t


@pytest.mark.parametrize(
    "question",
    [
        "مرحبا",
        "السَّلام عليكم!",
        "شكرا مسار",
        "Thank you!",
        "كيف أستخدم مسار؟",
        "كيف أفتح محادثة؟",
    ],
)
def test_closed_server_general_policy(question):
    assert general_allowed(question) and deterministic_general_reply(question)
    assert len(deterministic_general_reply(question)) < 600


@pytest.mark.parametrize(
    "question",
    [
        "مرحبا اشرح المشتقات",
        "شكرا، احسب 2+3",
        "ما هو الاحتمال؟",
        "كيف أرفع ملف في مسار؟",
        "كيف استخدم مسار لحل المتتاليات؟",
        "مرحبا " + "!" * 100,
    ],
)
def test_general_whitelist_not_educational_or_unbounded(question):
    assert (
        not general_allowed(question) and deterministic_general_reply(question) is None
    )


def test_policy_is_shared_by_tool_contract(services):
    t = actual_tools(services, "اشرح المشتقات", {})
    render = next(
        d for d in t.definitions() if d["function"]["name"] == "render_answer"
    )
    assert GENERAL_POLICY in render["function"]["description"]


@pytest.mark.parametrize("case", ["M17", "M18", "M20", "M22"])
def test_pr33_actual_logarithm_source_rejects_recorded_false_sufficiency(
    services, case
):
    f = json.loads(
        (Path(__file__).parent / "fixtures/pr33_coverage_replay.json").read_text()
    )
    sid = f["provenance"]["source_id"]
    t = actual_tools(
        services, f["questions"][case], {sid: f["body"]}, {sid: f["title"]}
    )
    # Even adding genuine quotes to the old decision cannot rescue the unrelated source.
    decision, _ = parse_assessment(wire([sid], [support(sid, f["body"][:1400])]), t)
    assert decision.decision == "uncertain" and not t.references_ready
    audit = services.db.one(
        "SELECT * FROM audit WHERE action='context_support_rejected'"
    )
    details = json.loads(audit["details"])
    assert "CURRENT_GOAL_BODY_TOPIC_MISMATCH" in details["reason_codes"]
    assert (
        f["body"][:100] not in audit["details"]
        and f["questions"][case] not in audit["details"]
    )
    assert not services.db.rows("SELECT * FROM run_events")


@pytest.mark.parametrize(
    "question,body",
    [
        (
            "اشرح المشتقات",
            "قاعدة المشتقات: مشتقة مجموع دالتين هي مجموع مشتقتيهما إذا كانتا قابلتين للاشتقاق.",
        ),
        (
            "اشرح الاحتمال الشرطي",
            "الاحتمال الشرطي يساوي P(A|B)=P(A intersection B)/P(B) بشرط P(B)>0.",
        ),
        (
            "وضح المتتاليات",
            "المتتاليات العددية تعين لكل عدد طبيعي n الحد u_n. النهاية تختلف عن الحد الثاني u2.",
        ),
    ],
)
def test_current_topic_requires_actual_body_and_quote(services, question, body):
    t = actual_tools(services, question, {"real": body})
    decision, _ = parse_assessment(wire(["real"], [support("real", body)]), t)
    assert decision.decision == "sufficient" and t.coverage_validated
    assert t.covered_sources == {"real"}


def test_topic_related_but_missing_indispensable_condition_is_not_sufficient(services):
    body = (
        "المتتاليات المتزايدة تحقق u_n <= u_{n+1}. التزايد لا يحدد نهاية منتهية بمفرده."
    )
    t = actual_tools(services, "هل كل متتالية متزايدة لها نهاية منتهية؟", {"seq": body})
    decision, _ = parse_assessment(wire(["seq"], [support("seq", body)]), t)
    assert decision.decision == "uncertain"
    assert (
        "MISSING_CONVERGENCE_BOUND_CONDITION"
        in services.db.one(
            "SELECT details FROM audit WHERE action='context_support_rejected'"
        )["details"]
    )


def test_nonverbatim_quote_and_reported_gap_revoke_support(services):
    body = "درس الاحتمال: يتراوح احتمال الحدث بين صفر وواحد."
    t = actual_tools(services, "اشرح الاحتمالات", {"prob": body})
    decision, _ = parse_assessment(
        wire(
            ["prob"],
            [support("prob", "نص مختلق غير موجود في الدرس")],
            ["missing conditional rule"],
        ),
        t,
    )
    assert decision.decision == "uncertain"
    details = services.db.one(
        "SELECT details FROM audit WHERE action='context_support_rejected'"
    )["details"]
    assert "QUOTE_NOT_IN_ACTUAL_BODY" in details and "REPORTED_SUPPORT_GAP" in details
    assert "missing conditional rule" not in details


def test_metadata_parent_topic_cannot_certify_child_body(services):
    body = "اللوغاريتم النيبيري معرف على الأعداد الموجبة."
    t = actual_tools(
        services,
        "اشرح الاحتمالات",
        {"child": body},
        {"child": "كتاب الرياضيات: الاحتمالات والمتتاليات والمشتقات"},
    )
    decision, _ = parse_assessment(wire(["child"], [support("child", body)]), t)
    assert decision.decision == "uncertain"


def test_current_topic_overrides_prior_logarithm_and_multistep_retains_prerequisite(
    services,
):
    derivative = "قاعدة الاشتقاق: مشتقة مجموع دالتين هي مجموع مشتقتيهما إذا كانتا قابلتين للاشتقاق."
    logarithm = (
        "اللوغاريتم النيبيري ln(x) معرف فقط عندما x>0 ومشتقته 1/x على هذا المجال."
    )
    t = actual_tools(
        services,
        "احسب مشتقة الدالة اللوغاريتمية باستعمال قاعدة الاشتقاق وشرط التعريف",
        {"d": derivative, "l": logarithm},
    )
    t.router_history = [{"role": "user", "content": "اشرح الاحتمالات"}]
    decision, _ = parse_assessment(
        wire(["d", "l"], [support("d", derivative), support("l", logarithm)]), t
    )
    assert decision.decision == "sufficient" and t.covered_sources == {"d", "l"}


@pytest.mark.asyncio
async def test_misclassified_general_routes_once_and_cannot_loop_without_reference(
    services,
):
    s = services
    _, _, user, chat, aliases = await setup(s)
    routes = router(s, aliases, [{"status": "no_new", "goals": [], "question": ""}])
    tutor = Tutor([("general_allowed", [])], [])
    s.chat_factory = lambda cfg, key: tutor
    result = await run(s, user, chat, "اشرح مشتقة دالة لا يوجد لها مرجع")
    assert result["status"] == "COMPLETED"
    assert len(routes) == 1 and len(tutor.assessments) == 1 and not tutor.work
    response = s.db.one("SELECT sources,content FROM messages WHERE role='assistant'")
    assert json.loads(response["sources"]) == [] and "؟" in response["content"]


@pytest.mark.asyncio
async def test_router_loading_wrong_topic_stops_before_teaching_and_no_recursive_route(
    services,
):
    s = services
    node, _, user, chat, aliases = await setup(s)
    routes = router(s, aliases, [[node]])
    tutor = Tutor([("uncertain", [])], [answer([node])])
    s.chat_factory = lambda cfg, key: tutor
    result = await run(s, user, chat, "اشرح الاحتمالات")
    assert result["status"] == "COMPLETED"
    assert len(routes) == 1 and len(tutor.assessments) == 2 and not tutor.work
    assert (
        "CURRENT_GOAL_BODY_TOPIC_MISMATCH"
        in s.db.one(
            "SELECT details FROM audit WHERE action='context_support_rejected'"
        )["details"]
    )


@pytest.mark.asyncio
async def test_followup_reads_actual_body_without_router(services):
    s = services
    node, _, user, chat, aliases = await setup(s)
    Tools(s, user, chat).load(node)
    routes = router(s, aliases, [])
    tutor = Tutor([("sufficient", [node])], [answer([node])])
    s.chat_factory = lambda cfg, key: tutor
    result = await run(s, user, chat, "لم أفهم الخطوة الثانية")
    assert result["status"] == "COMPLETED" and not routes
    assert len(tutor.assessments) == len(tutor.work) == 1
    request = js(tutor.assessments[0])
    assert "Initial components" in request and "complete_book_index" not in request
    assert (
        "You are Masar" not in request
    )  # Classification is isolated from the teaching prompt.


def test_delivered_id_without_verified_support_cannot_render_teaching(services):
    t = actual_tools(services, "اشرح الاحتمالات", {"prob": "الاحتمال بين صفر وواحد."})
    t.references_ready = True
    with pytest.raises(ValueError, match="REFERENCE_ASSESSMENT_REQUIRED"):
        require_grounding(
            PresentedAnswer.model_validate(
                {
                    "response_kind": "teaching",
                    "source_ids": ["prob"],
                    "blocks": [{"type": "text", "text": "شرح"}],
                }
            ),
            t,
        )


def test_multi_goal_body_topic_words_do_not_replace_unquoted_goal_support(services):
    derivative = "درس المشتقات: مشتقة مجموع دالتين هي مجموع مشتقتيهما إذا كانتا قابلتين للاشتقاق."
    probability = "درس الاحتمالات: الاحتمال الشرطي يساوي نسبة احتمال التقاطع إلى احتمال الحدث المشروط به."
    t = actual_tools(services, "اشرح المشتقات والاحتمالات", {"mixed": derivative + "\n" + probability})
    decision, _ = parse_assessment(wire(["mixed"], [support("mixed", derivative)]), t)
    assert decision.decision == "uncertain"
    assert "CURRENT_GOAL_NOT_SUPPORTED" in services.db.one(
        "SELECT details FROM audit WHERE action='context_support_rejected'")["details"]


@pytest.mark.asyncio
async def test_initial_route_plus_one_repair_has_three_assessments_no_recursive_loop(services):
    s = services
    node, _, user, chat, aliases = await setup(s)
    routes = router(s, aliases, [[node], [node]])
    repair = call("essential_context", {"importance": "essential", "query": "الشرط المكمل", "reason": "Missing essential condition"})
    tutor = Tutor([("missing_reference", [])], [repair, repair, answer([], "هل ترسل الشرط المقصود؟", "clarification")])
    s.chat_factory = lambda cfg, key: tutor
    result = await run(s, user, chat, "اشرح القذف")
    assert result["status"] == "COMPLETED"
    assert len(routes) == 2 and len(tutor.assessments) == 3 and len(tutor.work) == 3
    stats = s.db.one("SELECT * FROM context_decisions WHERE run_id=?", (result["id"],))
    assert stats["essential_requests"] == 1 and stats["router_requests"] == 2
