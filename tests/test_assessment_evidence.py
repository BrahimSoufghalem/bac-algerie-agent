"""Exact server passage choices and recorded run8 recovery; no live model calls."""

import json
from pathlib import Path

import pytest

from bac.agent.assessment_evidence import body_spans, prepare_body_choices
from bac.agent.context_decision import ASSESS_SYSTEM, assessment_tool, parse_assessment
from bac.agent.reference_coverage import (
    canonical_quote,
    in_subject_math_request,
    topics,
)
from tests.test_context_decisions import call
from tests.test_reference_coverage import actual_tools


def choice(alias="R1", eid="R1:E1", role="current_goal"):
    return {
        "source_id": alias,
        "evidence_id": eid,
        "goal": "applicable rule and hypotheses",
        "role": role,
        "requirement_ids": ["goal", "rule"],
    }


def decision(ids=None, coverage=None, kind="sufficient", gaps=None):
    return call(
        "assess_context",
        {
            "decision": kind,
            "requirements": [{"id":"goal", "kind":"goal", "description":"current goal"}, {"id":"rule", "kind":"rule", "description":"applicable rule"}] if kind == "sufficient" else [],
            "source_ids": ["R1"] if ids is None else ids,
            "coverage": [choice()] if coverage is None else coverage,
            "gaps": gaps or [],
        },
    )


def test_body_spans_preserve_every_character_in_order():
    text = ("عنوان\n\nمعادلة $x+2=3$\n\n" * 240) + "خاتمة"
    spans = list(body_spans(text))
    assert spans[0][0] == 0 and spans[-1][1] == len(text)
    assert "".join(text[a:b] for a, b in spans) == text
    assert all(spans[i][1] == spans[i + 1][0] for i in range(len(spans) - 1))


def test_live_schema_is_stable_and_server_choices_are_closed(services):
    t = actual_tools(
        services,
        "اشرح الاحتمال",
        {
            "long-source-id": "الاحتمال الشرطي يساوي P(A|B)=P(A intersection B)/P(B) بشرط P(B)>0."
        },
    )
    payload = prepare_body_choices(t)
    schema = assessment_tool(t)["function"]["parameters"]
    assert payload["reference_choices"] == {"R1": "long-source-id"}
    assert "enum" not in schema["properties"]["source_ids"]["items"]
    assert "enum" not in schema["$defs"]["BodySupport"]["properties"]["evidence_id"]
    assert "quote" not in schema["$defs"]["BodySupport"]["properties"]
    d, _ = parse_assessment(decision(), t)
    assert d.decision == "sufficient" and d.source_ids == ["long-source-id"]
    assert t.covered_sources == {"long-source-id"}
    assert d.coverage[0].quote == t.source_evidence["long-source-id"]["body"]


@pytest.mark.parametrize(
    "ids,records,code",
    [
        (["R17"], [choice()], "UNKNOWN_ASSESSMENT_SOURCE_CHOICE"),
        (["long-source-id"], [choice()], "UNKNOWN_ASSESSMENT_SOURCE_CHOICE"),
        (["R1"], [choice(eid="R1:E90")], "UNKNOWN_ASSESSMENT_EVIDENCE_CHOICE"),
        (["R1"], [choice(eid="R2:E1")], "EVIDENCE_SOURCE_MISMATCH"),
        (
            ["R1"],
            [dict(choice(), quote="نص مخترع غير موجود في الدرس")],
            "LIVE_QUOTE_NOT_SERVER_EVIDENCE",
        ),
    ],
)
def test_unknown_or_cross_source_choices_never_grant_read_credit(
    services, ids, records, code
):
    t = actual_tools(
        services,
        "اشرح الاحتمال",
        {
            "long-source-id": "الاحتمال بين صفر وواحد، وكل احتمال شرطي لا يزيد على واحد.",
            "second": "المتتاليات متزايدة ومحدودة تتقارب.",
        },
    )
    prepare_body_choices(t)
    d, _ = parse_assessment(decision(ids, records), t)
    assert (
        d.decision == "uncertain" and not t.covered_sources and not t.coverage_validated
    )
    assert (
        code
        in services.db.one(
            "SELECT details FROM audit WHERE action='context_support_rejected'"
        )["details"]
    )


def test_body_mutation_after_assessment_preparation_cannot_gain_credit(services):
    t = actual_tools(
        services,
        "اشرح الاحتمال",
        {"source": "الاحتمال بين صفر وواحد وهو نسبة عدد المخارج الملائمة."},
    )
    prepare_body_choices(t)
    t.source_evidence["source"]["body"] = (
        "الاحتمال بين صفر وواحد لكن هذا النص لم يرسل في التقييم."
    )
    d, _ = parse_assessment(decision(), t)
    assert d.decision == "uncertain" and not t.coverage_validated


@pytest.mark.parametrize("kind", ["missing_reference", "uncertain", "out_of_scope"])
def test_partial_support_for_nonsufficient_does_not_crash_or_authorize_teaching(
    services, kind
):
    t = actual_tools(
        services,
        "اشرح الاحتمال الشرطي",
        {"s": "درس الاحتمال الشرطي P(A|B)=P(A intersection B)/P(B). بشرط P(B)>0."},
    )
    prepare_body_choices(t)
    d, _ = parse_assessment(
        decision(
            ids=["invented"],
            coverage=[choice(alias="invented", eid="invented")],
            kind=kind,
        ),
        t,
    )
    assert d.decision == ("uncertain" if kind == "out_of_scope" else kind)
    assert not d.source_ids and not d.coverage and not t.coverage_validated


@pytest.mark.parametrize(
    "question",
    [
        "احسب مشتقة x^3",
        "اشرح الاحتمالات",
        "وضح المتتاليات",
        "u_{n+1}=u_n+1 احسب الحد الثاني",
        "ارسم f(x)=x^3-3x",
        "والآن خذ P(B|A)=1.2. احسب بنفس الطريقة.",
    ],
)
def test_in_scope_source_gap_is_not_platform_refusal(services, question):
    t = actual_tools(
        services,
        question,
        {"unrelated": "الدالة اللوغاريتمية معرفة على الأعداد الموجبة."},
    )
    prepare_body_choices(t)
    d, _ = parse_assessment(decision(ids=[], coverage=[], kind="out_of_scope"), t)
    assert in_subject_math_request(t) and d.decision == "uncertain"
    assert not t.coverage_validated  # Scope is NOT a sufficiency proof.


@pytest.mark.parametrize(
    "question",
    [
        "اكتب أغنية عن الاحتمالات",
        "اشرح فيزياء القذف",
        "تحدث عن كرة القدم",
        "كيف أرفع ملف في مسار؟",
    ],
)
def test_math_hint_does_not_expand_product_or_foreign_subject_policy(
    services, question
):
    t = actual_tools(services, question, {})
    prepare_body_choices(t)
    assert not in_subject_math_request(t)
    d, _ = parse_assessment(decision(ids=[], coverage=[], kind="out_of_scope"), t)
    assert d.decision == "out_of_scope" and not t.coverage_validated
    assert topics("تحدث عن كرة القدم") == set()


def test_darija_followup_uses_recent_math_not_loaded_body_topic(services):
    t = actual_tools(services, "ما فهمتش النقطة الثانية. عاود على نفس الدالة.", {})
    t.router_history = [
        {"role": "user", "content": "احسب المشتقة وادرس التغيرات f(x)=x^3-3x"}
    ]
    prepare_body_choices(t)
    d, _ = parse_assessment(decision(ids=[], coverage=[], kind="wrong_subject"), t)
    assert d.decision == "uncertain"


def test_escape_compatibility_is_narrow_and_preserves_math():
    assert canonical_quote(r"P_A(B)=\\frac{P(A\\cap B)}{P(A)}") == canonical_quote(
        r"P_A(B)=\frac{P(A\cap B)}{P(A)}"
    )
    assert canonical_quote(r"a \\ b \\\frac{1}{2}") == r"a \\ b \\\frac{1}{2}"
    assert canonical_quote(r"\\unknown{x}") == r"\\unknown{x}"
    assert canonical_quote("x+2=3") != canonical_quote("x-2=3")


def test_student_givens_need_not_be_verbatim_book_examples(services):
    body = r"الاحتمال الشرطي: P(A|B)=\frac{P(A\cap B)}{P(B)} بشرط P(B)>0. مجموع الاحتمالات الكلية يساوي احتمال الحدث."
    t = actual_tools(
        services, "P(A)=0.4 وP(B|A)=0.8. احسب P(A وعدم B).", {"source": body}
    )
    prepare_body_choices(t)
    d, _ = parse_assessment(decision(), t)
    assert "0.4" not in body and d.decision == "sufficient"
    assert "need NOT appear in the book" in ASSESS_SYSTEM
    # This only validates actual rule evidence, not the subsequent numerical answer.


@pytest.mark.parametrize(
    "question,body",
    [
        (
            "هل كل متتالية متزايدة تتقارب إلى نهاية منتهية؟",
            "المتتاليات المتزايدة تحقق u_n <= u_{n+1}. لا توجد هنا مبرهنة تقارب.",
        ),
        ("اشرح المتتاليات", "الاحتمال الشرطي يعين احتمال حادثة إذا تحقق حادث آخر."),
    ],
)
def test_passage_markers_do_not_rescue_wrong_topic_or_missing_bound(
    services, question, body
):
    t = actual_tools(services, question, {"s": body})
    prepare_body_choices(t)
    d, _ = parse_assessment(decision(), t)
    assert d.decision == "uncertain"


@pytest.mark.parametrize("case", ["M16", "M18", "M19", "M22"])
def test_pr34_recorded_partial_contracts_and_m22_scope_confusion(services, case):
    f = json.loads(
        (Path(__file__).parent / "fixtures/pr34_contract_replay.json").read_text()
    )
    x = next(x for x in f["records"] if x["case"] == case)
    t = actual_tools(services, x["question"], x["bodies"])
    t.router_history = x["recent_dialogue"]
    prepare_body_choices(t)
    d, _ = parse_assessment(call("assess_context", x["decision"]), t)
    assert d.decision in {"missing_reference", "uncertain"}
    assert not d.source_ids and not t.coverage_validated


def test_pr34_fabricated_student_quote_not_accepted_as_book_evidence(services):
    f = json.loads(
        (Path(__file__).parent / "fixtures/pr34_contract_replay.json").read_text()
    )
    x = next(x for x in f["records"] if x["case"] == "M05" and x["stage"] == "initial")
    t = actual_tools(services, x["question"], x["bodies"])
    d, _ = parse_assessment(call("assess_context", x["decision"]), t)
    assert d.decision == "uncertain" and not t.coverage_validated
    details = services.db.one(
        "SELECT details FROM audit WHERE action='context_support_rejected'"
    )["details"]
    assert "QUOTE_NOT_IN_ACTUAL_BODY" in details
    assert "f(-1)=0" not in details


@pytest.mark.asyncio
@pytest.mark.parametrize("post_route", [False, True])
async def test_scope_recovery_is_bounded_and_cannot_teach_from_unrelated_body(
    services, post_route
):
    from bac.agent.full_index import build_catalog
    from tests.grounding_fixture import publish_reference
    from tests.test_agent import chat_and_config
    from tests.test_context_decisions import Tutor, router, run
    from tests.test_full_index_router import selector

    s = services
    node = await publish_reference(s, "arithmetic")
    user, chat = chat_and_config(s, "mathematics")
    selector(s)
    _, mapping = build_catalog(s)
    aliases = {n["id"]: a for a, n in mapping.items()}
    plan = (
        [node]
        if post_route
        else {"status": "clarify", "goals": [], "question": "هل تحدد درس الاشتقاق؟"}
    )
    routes = router(s, aliases, [plan])

    class ScopeConfused(Tutor):
        async def decision_stream(self, messages, tools):
            self.assessments.append(messages)
            yield {
                "type": "usage",
                "data": {"prompt_tokens": 20, "completion_tokens": 6},
            }
            yield {
                "type": "result",
                "message": decision(ids=[], coverage=[], kind="out_of_scope"),
            }

    tutor = ScopeConfused([], [])
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, user, chat, "احسب المشتقة وادرس التغيرات f(x)=x^3-3x")
    assert state["status"] == "COMPLETED" and not tutor.work
    assert len(routes) == 1 and len(tutor.assessments) == (2 if post_route else 1)
    metrics = s.db.one("SELECT * FROM context_decisions WHERE run_id=?", (state["id"],))
    assert metrics["router_requests"] == 1
    assert metrics["reused_current"] == 0
