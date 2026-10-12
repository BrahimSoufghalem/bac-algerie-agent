"""Deterministic contracts/physics/history/language cases, not live pedagogy scores."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
import yaml
from bac.agent.assessment_evidence import prepare_body_choices
from bac.agent.context_decision import assessment_tool, parse_assessment
from bac.agent.context_prefix import stable_reference_prefix
from bac.agent.task_state import task_kind, history_only, task_state
from bac.agent.session_state import read_history
from bac.agent.models import Answer
from bac.agent.claim_checks import validate_claims
from bac.science.python_contract import validate_output
from bac.science.python_child import compute
from bac.core.db import js, uid
from tests.test_reference_coverage import actual_tools
from tests.test_context_decisions import call


def structured(ids=None, links=None, condition=False):
    reqs = [
        {"id": "goal", "kind": "goal", "description": "current objective"},
        {"id": "rule", "kind": "rule", "description": "applicable rule"},
    ]
    if condition:
        reqs.append(
            {
                "id": "condition",
                "kind": "condition",
                "description": "indispensable applicability condition",
            }
        )
    return call(
        "assess_context",
        {
            "decision": "sufficient",
            "source_ids": ids or ["R1"],
            "requirements": reqs,
            "coverage": [
                {
                    "source_id": "R1",
                    "role": "current_goal",
                    "goal": "current goal with conditions",
                    "evidence_id": "R1:E1",
                    "requirement_ids": links or [r["id"] for r in reqs],
                }
            ],
        },
    )


@pytest.mark.parametrize(
    "subject,question,body,other",
    [
        (
            "physics",
            "اشرح حركة القذف",
            "قذف جسم: الحركة الأفقية منتظمة والعمودية متسارعة بإهمال مقاومة الهواء.",
            "درس كهرباء: التيار والتوتر في دارة كهربائية.",
        ),
        (
            "electrical_engineering",
            "اشرح شحن المكثفة",
            "شحن المكثفة: ثابت الزمن يساوي RC والتوتر يزداد في دارة كهربائية مثالية.",
            "درس حركة قذف جسم في مجال الجاذبية.",
        ),
        (
            "history_geography",
            "اشرح الحرب الباردة",
            "الحرب الباردة صراع بين المعسكرين دون مواجهة مباشرة شاملة في سياق دولي محدد.",
            "التحرر من الاستعمار يرتبط بحركات المقاومة الوطنية.",
        ),
        (
            "arabic",
            "اشرح الإعراب",
            "الإعراب يحدد الوظيفة النحوية للكلمة حسب موقعها والقواعد النحوية.",
            "حجاج النص يعتمد على الأطروحة والحجج والنتائج.",
        ),
        (
            "natural_sciences",
            "اشرح الوراثة",
            "الوراثة انتقال صفات وراثية ترتبط بالمورثات وفق شروط ومراحل التكاثر.",
            "الاحتمال الشرطي يساوي نسبة احتمال تقاطع حادثتين.",
        ),
        (
            "accounting",
            "اشرح المحاسبة",
            "المحاسبة تسجل العمليات في الحسابات وفق مبدأ القيد المزدوج والوثائق المثبتة.",
            "التفاعلات الكيميائية تحول المواد المتفاعلة.",
        ),
    ],
)
def test_subject_neutral_body_gate(services, subject, question, body, other):
    t = actual_tools(services, question, {"s": body})
    t.study_scope.subject = (
        subject  # Unit-level contract; real scope permissions tested separately.
    )
    prepare_body_choices(t)
    d, _ = parse_assessment(structured(), t)
    assert d.decision == "sufficient"
    t.source_evidence["s"]["body"] = other
    t.coverage_validated = t.references_ready = False
    t.covered_sources.clear()
    t.study_scope.subject = subject
    prepare_body_choices(t)
    d, _ = parse_assessment(structured(), t)
    assert d.decision == "uncertain" and not t.coverage_validated


def test_missing_dependency_link_cannot_grant_sufficiency(services):
    t = actual_tools(
        services,
        "اشرح المشتقة",
        {"s": "قاعدة الاشتقاق تحدد مشتقة مجموع دالتين قابلتين للاشتقاق."},
    )
    prepare_body_choices(t)
    d, _ = parse_assessment(structured(links=["goal", "rule"], condition=True), t)
    assert d.decision == "uncertain"
    assert (
        "UNSUPPORTED_REQUIREMENT"
        in services.db.one(
            "SELECT details FROM audit WHERE action='context_support_rejected'"
        )["details"]
    )


def test_closed_server_allowlist_despite_constant_wire_schema(services):
    t = actual_tools(services, "اشرح الاحتمال", {})
    prepare_body_choices(t)
    empty_schema = assessment_tool(t)
    t.sources = {"s": {"source_id": "s"}}
    t.source_evidence = {
        "s": {"body": "الاحتمال يتراوح بين صفر وواحد في تجربة احتمالية."}
    }
    t.delivered_sources.add("s")
    prepare_body_choices(t)
    assert assessment_tool(t) == empty_schema
    d, _ = parse_assessment(structured(ids=["R999"]), t)
    assert d.decision == "uncertain"


def test_canonical_reference_prefix_stable_order_versions_and_no_truncation(services):
    t = actual_tools(services, "اشرح", {"b": "نص ب " * 15000, "a": "نص أ " * 100})
    for sid in t.sources:
        t.sources[sid]["version_id"] = "v1"
    old = {"role": "user", "content": "OLD dynamic restored envelope"}
    t.reference_messages[id(old)] = set(t.sources)
    first = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "settings1"},
        old,
        {"role": "user", "content": "question1"},
    ]
    stable_reference_prefix(first, t)
    prefix = deepcopy(first[:3])
    second = [
        {"role": "system", "content": "policy"},
        {"role": "user", "content": "settings2"},
        {"role": "user", "content": "question2"},
    ]
    t.source_evidence = dict(reversed(list(t.source_evidence.items())))
    stable_reference_prefix(second, t)
    assert prefix == second[:3]
    assert len(second[2]["content"]) > 60000
    assert "question" not in js(prefix) and "settings" not in js(prefix)
    t.sources["b"]["version_id"] = "v2"
    changed = [{"role": "system", "content": "policy"}]
    stable_reference_prefix(changed, t)
    assert changed[2] != prefix[2]
    del t.sources["b"]
    removed = [{"role": "system", "content": "policy"}]
    stable_reference_prefix(removed, t)
    assert len(removed) == 2  # Never keep unauthorized/irrelevant data just for cache.


def test_plot_not_inherit_old_derivative_goal(services):
    from bac.agent.reference_coverage import current_topics

    t = actual_tools(services, "ارسم g على المجال المطلوب", {})
    t.router_history = [{"role": "user", "content": "احسب مشتقة الدالة اللوغاريتمية g"}]
    assert task_kind(t.question) == "plot"
    assert current_topics(t) == {"logarithms"}
    assert task_kind("اشرح معنى المقاومة الكهربائية") == "explanation"
    assert task_kind("احسب شدة التيار") == "calculation"


def test_current_student_state_cannot_import_book_examples(services):
    t = actual_tools(services, "بدل المعطيات الآن", {"s": "example 12345"})
    state = task_state(
        t,
        "current",
        [
            {"id": "old", "role": "user", "content": "original givens"},
            {"id": "book", "role": "assistant", "content": "book example"},
        ],
    )
    assert state["current_request_message_id"] == "current"
    assert state["recent_student_givens"][0]["message_id"] == "old"
    assert "12345" not in js(state) and "book example" not in js(state)


@pytest.mark.parametrize(
    "question,only",
    [
        ("لخص أخطائي خلال هذه المحادثة", True),
        ("لخص الأخطاء التي وقعت فيها أنا خلال هذه المحادثة ثم اقترح تمرينا", False),
        ("لخص أخطاء الاشتقاق", False),
    ],
)
def test_history_not_a_teaching_bypass(question, only):
    assert history_only(question) is only


def test_history_pagination_ownership_inactive_messages_and_provenance(services):
    t = actual_tools(services, "لخص أخطائي خلال المحادثة", {})
    ids = []
    for i in range(27):
        mid = uid("message")
        ids.append(mid)
        services.db.execute(
            "INSERT INTO messages(id,conversation_id,role,content,blocks,created_at) VALUES(?,?,?,?,?,?)",
            (mid, t.chat, "user", f"أظن أن الفكرة رقم {i} صحيحة", "[]", i),
        )
    services.db.execute("UPDATE messages SET active=0 WHERE id=?", (ids[4],))
    page = read_history(t)
    assert not page["complete"] and len(page["items"]) == 24
    last = read_history(t, page["next_before_message_id"])
    assert last["complete"] and len(last["items"]) == 2
    assert ids[4] not in t.history_evidence and ids[0] in t.history_evidence
    t.history_summary_request = t.history_summary_requested = True
    ans = Answer.model_validate(
        {
            "response_kind": "history_summary",
            "blocks": [
                {"type": "text", "text": "نراجع الاعتقاد الأول دون اعتباره إتقانا."}
            ],
            "history_evidence": [
                {
                    "block_index": 0,
                    "message_id": ids[0],
                    "quote": "أظن أن الفكرة رقم 0 صحيحة",
                }
            ],
        }
    )
    validate_claims(ans, t)
    services.db.execute("UPDATE messages SET active=0 WHERE id=?", (ids[0],))
    with pytest.raises(ValueError, match="active|Active"):
        validate_claims(ans, t)
    with pytest.raises(ValueError):
        read_history(t, "another-chat-id")
    t.user = {"id": "foreign-owner"}
    with pytest.raises(ValueError):
        read_history(t)


def output(code):
    # Fixed trusted unit code only. Application never executes code on host.
    return validate_output(compute({"code": code, "limits": {"output_chars": 16000}}))


def test_print_ok_and_check_constant_without_evidence_are_not_claim_verification():
    t = SimpleNamespace(
        coordinated=True,
        scientific={
            "r": {
                "tool": "run_python",
                "output": output('print("OK")\ncheck("claim", True)'),
            }
        },
        history_summary_requested=False,
    )
    ans = Answer.model_validate(
        {
            "response_kind": "calculation",
            "blocks": [{"type": "text", "text": "claim"}],
            "checked_claims": [
                {"claim": "claim", "block_index": 0, "result_id": "r", "check_index": 0}
            ],
        }
    )
    with pytest.raises(ValueError, match="THIS claim"):
        validate_claims(ans, t)


@pytest.mark.parametrize(
    "code,label",
    [
        (
            'observed=3*(-2)**2-3\ncheck("derivative is negative", observed<0, evidence={"observed":observed,"expected":0,"relation":"less"})',
            "derivative is negative",
        ),
        (
            'import math\nobserved=(0>0)\ncheck("zero is in the logarithm domain", observed, evidence={"observed":observed,"expected":True})',
            "zero is in the logarithm domain",
        ),
        (
            'voltage=12; resistance=6\nobserved=voltage/resistance\ncheck("current equals three amperes", observed==3, evidence={"observed":observed,"expected":3})',
            "current equals three amperes",
        ),
    ],
)
def test_run9_claim_regressions_and_physics_false_claim_rejected(code, label):
    result = output(code)
    assert result["status"] == "failed"
    t = SimpleNamespace(
        coordinated=True,
        scientific={"r": {"tool": "run_python", "output": result}},
        history_summary_requested=False,
    )
    ans = Answer.model_validate(
        {
            "blocks": [{"type": "text", "text": label}],
            "checked_claims": [
                {"claim": label, "block_index": 0, "result_id": "r", "check_index": 0}
            ],
        }
    )
    with pytest.raises(ValueError):
        validate_claims(ans, t)


def test_real_specific_check_label_and_result_binding():
    result = output(
        'a=12/6\ncheck("current equals two amperes", a==2, evidence={"observed":a,"expected":2})'
    )
    t = SimpleNamespace(
        coordinated=True,
        scientific={"r": {"tool": "run_python", "output": result}},
        history_summary_requested=False,
    )
    args = {
        "response_kind": "calculation",
        "blocks": [{"type": "text", "text": "current equals two amperes"}],
        "checked_claims": [
            {
                "claim": "current equals two amperes",
                "block_index": 0,
                "result_id": "r",
                "check_index": 0,
            }
        ],
    }
    validate_claims(Answer.model_validate(args), t)
    args["blocks"][0]["text"] = "current equals three amperes"
    with pytest.raises(ValueError, match="public answer block"):
        validate_claims(Answer.model_validate(args), t)
    with pytest.raises(ValueError, match="disagrees"):
        validate_output(
            {
                "checks": [
                    {
                        "label": "bad",
                        "status": "passed",
                        "evidence": {"observed": 2, "expected": 3},
                    }
                ]
            }
        )


def test_nested_equation_wrapper_normalization_and_subject_neutral_prompt():
    from bac.agent.answer_quality import prepare_answer

    assert (
        prepare_answer(
            {
                "blocks": [
                    {"type": "equation", "latex": r"\\[ x=1 \\]".replace("\\\\", "\\")}
                ]
            },
            "",
            {},
        )["blocks"][0]["latex"]
        == "x=1"
    )
    prompt = yaml.safe_load(open("config/agent.yaml"))["system"]
    assert (
        "multi-subject platform" in prompt
        and "Bayes" not in prompt
        and "Derivative/extremum" not in prompt
    )


from bac.core.study import SUBJECTS, TRACK_SUBJECTS


@pytest.mark.parametrize("subject", sorted(SUBJECTS))
def test_real_authenticated_scope_uses_same_assessment_contract_for_every_subject(
    services, subject
):
    from bac.agent.tools import Tools
    from bac.core.auth import create_user

    user_id = create_user(services.db, "scope@example.com", "Strong-password-1", "Student")
    user = services.db.one("SELECT * FROM users WHERE id=?", (user_id,))
    chat = uid("chat")
    track = next(
        track for track, subjects in TRACK_SUBJECTS.items() if subject in subjects
    )
    services.db.execute(
        "UPDATE users SET study_track=? WHERE id=?", (track, user["id"])
    )
    services.db.execute("INSERT INTO conversations(id,user_id,title,created_at,updated_at,study_subject) VALUES(?,?,?,?,?,?)", (chat,user_id,"Test",0,0,subject))
    t = Tools(services, user, chat)
    t.question = "اشرح الفكرة الأساسية في هذا الدرس مع شروطها"
    t.sources = {"s": {"source_id": "s", "node_id": "s"}}
    t.source_evidence = {
        "s": {
            "body": "الفكرة الأساسية قاعدة معرفية في هذا الدرس، ويجب تطبيقها ضمن الشروط المذكورة."
        }
    }
    t.delivered_sources.add("s")
    prepare_body_choices(t)
    d, _ = parse_assessment(structured(condition=True), t)
    assert t.study_scope.subject == subject and d.decision == "sufficient"
    # All scopes use one fixed tool schema, not subject-tuned instructions.
    schema = assessment_tool(t)
    t.source_evidence.clear()
    prepare_body_choices(t)
    assert assessment_tool(t) == schema


@pytest.mark.asyncio
async def test_pure_history_summary_no_router_or_assessment_and_real_student_evidence(services):
    from tests.test_context_decisions import setup, router, run, Tutor
    n, _, user, chat, aliases = await setup(services)
    mid = uid("message")
    services.db.execute("INSERT INTO messages(id,conversation_id,role,content,blocks,created_at) VALUES(?,?,?,?,?,?)", (mid,chat,"user","أظن أن الفكرة الأولى صحيحة","[]",0))
    routes = router(services, aliases, [])
    class Historian(Tutor):
        async def stream(self,messages,tools):
            self.work.append(messages)
            if len(self.work) == 1:
                yield {"type":"result","message":call("read_conversation_history",{})}
            else:
                yield {"type":"result","message":call("render_answer",{"response_kind":"history_summary","blocks":[{"type":"text","text":"ذكرت اعتقادا في الفكرة الأولى، دون دليل كاف للحكم بأنه إتقان أو خطأ."}],"history_evidence":[{"block_index":0,"message_id":mid,"quote":"أظن أن الفكرة الأولى صحيحة"}]})}
    tutor=Historian([],[])
    services.chat_factory=lambda cfg,key:tutor
    result=await run(services,user,chat,"لخص أخطائي خلال هذه المحادثة")
    assert result["status"] == "COMPLETED"
    assert not routes and not tutor.assessments and len(tutor.work)==2
    metrics=services.db.one("SELECT * FROM context_decisions WHERE run_id=?", (result["id"],))
    assert metrics["decision"] == "history_summary" and metrics["router_requests"]==0
