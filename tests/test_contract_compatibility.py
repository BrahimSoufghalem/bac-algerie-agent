"""PR36 wire regressions and bounded flow tests, without live API calls."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from bac.agent.assessment_evidence import prepare_body_choices
from bac.agent.context_decision import (
    AssessmentContractError, assessment_tool, parse_assessment,
)
from bac.agent.engine import AgentEngine
from bac.agent.tools import Tools
from tests.test_context_decisions import (
    answer, assessment_state, call, router, run, setup, supported_decision,
)
from tests.test_reference_coverage import actual_tools

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/pr36_contract_replay.json").read_text()
)


def grouped(args):
    args = deepcopy(args)
    groups = {"goals": [], "rules": [], "conditions": [], "prerequisites": []}
    names = {"goal": "goals", "rule": "rules", "condition": "conditions",
             "prerequisite": "prerequisites"}
    for item in args["requirements"]:
        groups[names[item["kind"]]].append(
            {"id": item["id"], "description": item["description"]}
        )
    args["requirements"] = groups
    return args


def synthetic():
    return {
        "decision": "sufficient", "source_ids": ["R1"], "gaps": [],
        "requirements": {
            "goals": [{"id": "g", "description": "Current requested objective"}],
            "rules": [{"id": "r", "description": "Applicable rule"}],
            "conditions": [{"id": "c", "description": "Necessary condition"}],
            "prerequisites": [],
        },
        "coverage": [{
            "source_id": "R1", "evidence_id": "R1:E1",
            "goal": "Applicable rule supports the current goal under its conditions",
            "role": "current_goal", "requirement_ids": ["g", "r", "c"],
        }],
    }


@pytest.mark.parametrize("subject,question,body", [
    ("mathematics", "اشرح الاحتمال", "الاحتمال الشرطي يقتضي أن احتمال الحدث المعطى غير معدوم."),
    ("physics", "اشرح حركة القذف", "حركة القذف تخضع للجاذبية مع إهمال مقاومة الهواء."),
    ("electrical_engineering", "اشرح المكثفة", "المكثفة في دارة كهربائية مثالية لها ثابت زمن RC."),
    ("history_geography", "اشرح الحرب الباردة", "الحرب الباردة صراع دولي بين معسكرين في سياق زمني محدد."),
    ("arabic", "اشرح الإعراب", "الإعراب يعتمد على الوظيفة النحوية وموقع الكلمة في الجملة."),
    ("natural_sciences", "اشرح الوراثة", "الوراثة ترتبط بالمورثات وشروط التكاثر وانتقال الصفات."),
])
def test_named_groups_use_same_closed_contract_for_all_subjects(
    services, subject, question, body
):
    t = actual_tools(services, question, {"s": body})
    t.study_scope.subject = subject
    prepare_body_choices(t)
    before = assessment_tool(t)
    schema = before["function"]["parameters"]
    grouped_schema = schema["$defs"]["RequirementGroups"]
    assert set(grouped_schema["required"]) == {
        "goals", "rules", "conditions", "prerequisites"
    }
    assert "kind" not in schema["$defs"]["NamedRequirement"]["properties"]
    d, _ = parse_assessment(call("assess_context", synthetic()), t)
    assert d.decision == "sufficient"
    assert [x.kind for x in d.requirements] == ["goal", "rule", "condition"]
    assert t.covered_sources == {"s"}
    t.source_evidence.clear()
    prepare_body_choices(t)
    assert before == assessment_tool(t)  # No dynamic alias enums/cache churn.


@pytest.mark.parametrize("record", FIXTURE["assessments"], ids=lambda r: r["case_id"])
def test_actual_run10_contract_failures_are_separated_from_real_body_gaps(
    services, record
):
    t = actual_tools(
        services, "اشرح الاحتمال",
        # Synthetic unrelated bodies, but all recorded aliases/passages genuinely
        # exist. Otherwise an earlier unknown-span rejection masks the shape fault.
        {f"s{i}": (
            "المشتقة واتجاه تغير دالة وقيمها الحدية وشروطها على مجال تعريفها. " * 35
            + "\n\n"
        ) * 8 for i in range(3)},
    )
    prepare_body_choices(t)
    args = deepcopy(record["args"])
    if record["case_id"] == "M06":
        with pytest.raises(AssessmentContractError, match="INVALID_CONTEXT_DECISION"):
            parse_assessment(call("assess_context", args), t)
        assert not t.coverage_validated
        return
    d, _ = parse_assessment(call("assess_context", args), t)
    assert not t.coverage_validated
    assert d.decision == "uncertain"  # Synthetic body cannot authorize unrelated teaching.
    kinds = {r["kind"] for r in args["requirements"]}
    if "goal" not in kinds:
        assert "MISSING_CURRENT_GOAL_REQUIREMENT" in t.assessment_contract_errors
    if "rule" not in kinds:
        assert "MISSING_APPLICABLE_RULE_REQUIREMENT" in t.assessment_contract_errors
    if kinds >= {"goal", "rule"}:
        assert not t.assessment_contract_errors  # Real topic mismatch, not format repair.


def test_real_missing_dependency_does_not_become_a_format_error(services):
    t = actual_tools(services, "اشرح الاحتمال", {"s": "الاحتمال الشرطي يفترض P(A)>0."})
    prepare_body_choices(t)
    args = synthetic()
    args["requirements"]["prerequisites"] = [
        {"id": "missing", "description": "Missing indispensable earlier rule"}
    ]
    d, _ = parse_assessment(call("assess_context", args), t)
    assert d.decision == "uncertain"
    assert not t.assessment_contract_errors
    assert not t.references_ready and not t.coverage_validated


def test_unknown_source_or_passage_not_corrected_or_given_read_credit(services):
    t = actual_tools(services, "اشرح الاحتمال", {"s": "الاحتمال الشرطي يفترض P(A)>0."})
    prepare_body_choices(t)
    for field, value in [("source_id", "R999"), ("evidence_id", "R1:E999")]:
        args = synthetic()
        args["coverage"][0][field] = value
        d, _ = parse_assessment(call("assess_context", args), t)
        assert d.decision == "uncertain"
        assert not t.assessment_contract_errors and not t.coverage_validated


class RepairTutor:
    """Synthetic actual-body decisions; only failure shape comes from run10."""

    def __init__(self, node, *, duplicate=False, recover=True):
        self.node, self.duplicate, self.recover = node, duplicate, recover
        self.assessments, self.work = [], []

    async def decision_stream(self, messages, tools):
        self.assessments.append(messages)
        state = assessment_state(messages)
        if not state["actual_source_bodies"]:
            args = {"decision": "missing_reference", "source_ids": [],
                    "requirements": {"goals": [], "rules": [], "conditions": [],
                                     "prerequisites": []},
                    "coverage": [], "gaps": ["Applicable source not loaded."]}
        else:
            args = grouped(supported_decision([self.node], messages))
            if not (state.get("assessment_contract_feedback") and self.recover):
                if self.duplicate:
                    args["source_ids"] *= 2
                else:
                    args["requirements"]["goals"] = []
                    for support in args["coverage"]:
                        support["requirement_ids"] = ["rule"]
        yield {"type": "usage", "data": {"prompt_tokens": 41, "completion_tokens": 9}}
        yield {"type": "result", "message": call("assess_context", args)}

    async def stream(self, messages, tools):
        self.work.append(messages)
        yield {"type": "result", "message": answer([self.node])}


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate", [False, True])
async def test_format_repair_then_n_followups_never_reload_index_by_default(
    services, duplicate
):
    s = services
    node, _, user, chat, aliases = await setup(s)
    routes = router(s, aliases, [[node]])
    tutor = RepairTutor(node, duplicate=duplicate)
    s.chat_factory = lambda cfg, key: tutor
    for i in range(3):
        state = await run(s, user, chat, "اشرح القذف" if not i else "وضح نفس الفكرة")
        assert state["status"] == "COMPLETED", state
    assert len(routes) == 1
    assert len(tutor.assessments) == 3 + 2 + 2
    assert len(tutor.work) == 3
    assert len(s.db.rows("SELECT * FROM audit WHERE action='context_contract_repair'")) == 3
    assert all(
        not json.loads(m["content"].split("\n", 1)[1]).get("complete_book_index")
        for messages in tutor.assessments for m in messages[1:]
    )
    assert not s.db.rows("SELECT * FROM run_events WHERE type='error'")


@pytest.mark.asyncio
async def test_repeated_bad_contract_stops_once_safely_not_a_router_loop(services):
    s = services
    node, _, user, chat, aliases = await setup(s)
    routes = router(s, aliases, [[node]])
    tutor = RepairTutor(node, recover=False)
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, user, chat, "اشرح القذف")
    assert state["status"] == "COMPLETED", state
    assert len(routes) == 1 and len(tutor.assessments) == 3 and not tutor.work
    event = s.db.one("SELECT payload FROM run_events WHERE run_id=? AND type='answer'",
                     (state["id"],))
    message_id = json.loads(event["payload"])["message_id"]
    row = s.db.one("SELECT content FROM messages WHERE id=?", (message_id,))
    assert "لم تتوفر معلومات كافية" in row["content"]


@pytest.mark.asyncio
async def test_exhausted_assessment_budget_never_starts_a_fourth_call(services):
    t = actual_tools(services, "اشرح الاحتمال", {"s": "الاحتمال الشرطي يفترض P(A)>0."})
    t.assessment_count = 3
    engine = AgentEngine(services)
    d = await engine.assess_context({"id": "offline", "user_id": t.user["id"]},
                                   t, None, {}, [])
    assert d.decision == "uncertain" and not t.coverage_validated
    assert t.assessment_count == 3


@pytest.mark.asyncio
async def test_python_print_feedback_arrives_before_final_round_then_bound_claim(
    services, monkeypatch
):
    from bac.science.python_runner import PythonRunner

    s = services
    node, _, user, chat, aliases = await setup(s)
    Tools(s, user, chat).load(node)
    routes = router(s, aliases, [])
    label = "نتيجة الحساب 5."

    def execute(self, args):
        checks = [] if args["code"].startswith("print") else [
            {"label": label, "status": "passed", "evidence": {
                "observed": 5, "expected": 5, "relation": "equal", "tolerance": 0
            }}
        ]
        return {"status": "computed", "outputs": {"sum": 5}, "checks": checks,
                "stdout": "5\n"}

    monkeypatch.setattr(PythonRunner, "execute", execute)  # No local host execution.

    class CheckedTutor(RepairTutor):
        async def decision_stream(self, messages, tools):
            self.assessments.append(messages)
            yield {"type": "result", "message": call(
                "assess_context", grouped(supported_decision([node], messages))
            )}

        async def stream(self, messages, tools):
            self.work.append(messages)
            count = len(self.work)
            if count == 1:
                message = call("run_python", {"code": "print(2+3)"})
            elif count == 2:
                last = json.loads(next(m["content"] for m in reversed(messages)
                                       if m["role"] == "tool"))
                assert "answer_contract_feedback" in last
                assert last["output"]["status"] == "computed"
                message = call("run_python", {"code": "check('sum', True)"})
            else:
                last = json.loads(next(m["content"] for m in reversed(messages)
                                       if m["role"] == "tool"))
                assert "answer_contract_feedback" not in last
                message = call("render_answer", {
                    "source_ids": [node], "response_kind": "teaching",
                    "blocks": [{"type": "text", "text": label}],
                    "checked_claims": [{"block_index": 0, "claim": label,
                                       "result_id": last["result_id"], "check_index": 0}],
                })
            yield {"type": "result", "message": message}

    tutor = CheckedTutor(node)
    s.chat_factory = lambda cfg, key: tutor
    state = await run(s, user, chat, "احسب وتحقق من المثال في الدرس")
    assert state["status"] == "COMPLETED", state
    assert len(tutor.work) == 3 and not routes
    assert len(s.db.rows("SELECT * FROM scientific_results WHERE run_id=?",
                        (state["id"],))) == 2
    # Feedback remains private; persisted outputs do not claim whole-answer verification.
    event = s.db.one("SELECT payload FROM run_events WHERE run_id=? AND type='answer'",
                     (state["id"],))
    message_id = json.loads(event["payload"])["message_id"]
    message = s.db.one("SELECT content FROM messages WHERE id=?", (message_id,))
    assert message["content"] == label