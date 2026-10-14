"""Offline Run12 wire regressions. Mocks are not live pedagogical certification."""

import copy
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from bac.agent.anthropic import AnthropicChat
from bac.agent.assessment_evidence import prepare_body_choices
from bac.agent.compat import google_answer_tools
from bac.agent.context_decision import (
    AssessmentContractError,
    assessment_tool,
    parse_assessment,
)
from bac.agent.full_index import FullIndexCoordinator, parse_route, router_function
from bac.agent.models import PresentedAnswer
from bac.agent.provider import ModelError, OpenAIChat
from bac.agent.tools import Tools
from bac.core.db import js, uid
from tests.test_context_decisions import (
    Tutor,
    answer,
    call,
    router,
    run,
    setup,
    supported_decision,
)
from tests.test_contract_compatibility import grouped, synthetic
from tests.test_gemini_compat import BASE, response
from tests.test_reference_coverage import actual_tools
from tests.test_shared_generation_contracts import answer_manifest

REPLAY = json.loads(
    (Path(__file__).parent / "fixtures/run12_wire_contracts.json").read_text()
)


def nested(args):
    """Author explicit complete links in a TEST only, never infer them in production."""
    args = (
        grouped(args) if isinstance(args["requirements"], list) else copy.deepcopy(args)
    )
    support = args.pop("coverage")[0]
    for items in args["requirements"].values():
        for item in items:
            item["supports"] = [{k: support[k] for k in ("source_id", "evidence_id")}]
    return args


def test_google_schema_derives_all_provenance_fields_and_response_kinds():
    original = answer_manifest()
    frozen = copy.deepcopy(original)
    canonical = original[0]["function"]["parameters"]
    wire = google_answer_tools(original)[0]["function"]["parameters"]
    assert original == frozen
    assert set(wire["properties"]) == set(canonical["properties"])
    assert wire["required"] == canonical["required"]
    assert (
        wire["properties"]["response_kind"] == canonical["properties"]["response_kind"]
    )
    assert {"checked_claims", "history_evidence"} <= wire["properties"].keys()
    assert not {"checked_claims", "history_evidence"} & set(
        REPLAY["old_google_top_fields"]
    )
    assert "history_summary" not in REPLAY["old_google_response_kinds"]
    assert "history_summary" in wire["properties"]["response_kind"]["enum"]
    for name in ("checked_claims", "history_evidence"):
        item = wire["properties"][name]["items"]
        definition = canonical["$defs"][
            canonical["properties"][name]["items"]["$ref"].split("/")[-1]
        ]
        assert item == definition
        assert (
            wire["properties"][name]["maxItems"]
            == canonical["properties"][name]["maxItems"]
        )
    block = wire["properties"]["blocks"]["items"]
    assert "oneOf" not in js(wire) and "$ref" not in js(wire)
    assert "result" not in block["properties"]
    assert block["properties"]["text"]["maxLength"] == 24000
    assert wire["properties"]["blocks"]["minItems"] == 1
    assert wire["properties"]["blocks"]["maxItems"] == 30
    with pytest.raises(ValidationError):
        PresentedAnswer.model_validate(
            {"blocks": [{"type": "code", "text": "x" * 12001}]}
        )
    with pytest.raises(ValidationError):
        PresentedAnswer.model_validate(
            {"blocks": [{"type": "text", "text": "x", "result_id": "fake"}]}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base", [BASE, "https://api.openai.com/v1", "https://api.deepseek.com/v1"]
)
async def test_actual_openai_wire_preserves_checked_and_history_contract(base):
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        props = body["tools"][0]["function"]["parameters"]["properties"]
        assert {"checked_claims", "history_evidence"} <= props.keys()
        assert "history_summary" in props["response_kind"]["enum"]
        return response(
            "render_answer",
            {
                "response_kind": "history_summary",
                "blocks": [{"type": "text", "text": "Fixture"}],
            },
        )

    events = [
        e
        async for e in OpenAIChat(
            {"base_url": base, "model": "fixture"},
            "fixture-only",
            transport=httpx.MockTransport(handler),
        ).final_stream([], answer_manifest())
    ]
    assert len(sent) == 1 and events[-1]["type"] == "result"


@pytest.mark.asyncio
async def test_actual_anthropic_wire_preserves_same_top_contract():
    def handler(request):
        body = json.loads(request.content)
        props = body["tools"][0]["input_schema"]["properties"]
        assert {"checked_claims", "history_evidence"} <= props.keys()
        assert "history_summary" in props["response_kind"]["enum"]
        events = [
            {"type": "message_start", "message": {"usage": {"input_tokens": 3}}},
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {
                    "type": "tool_use",
                    "id": "terminal",
                    "name": "render_answer",
                    "input": {"blocks": [{"type": "text", "text": "Fixture"}]},
                },
            },
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use"},
                "usage": {"output_tokens": 2},
            },
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join("data: " + js(e) + "\n\n" for e in events),
        )

    items = [
        e
        async for e in AnthropicChat(
            {"base_url": "https://api.anthropic.com/v1", "model": "fixture"},
            "fixture-only",
            transport=httpx.MockTransport(handler),
        ).final_stream([], answer_manifest())
    ]
    assert items[-1]["type"] == "result"


@pytest.mark.parametrize(
    "subject,question,body",
    [
        (
            "mathematics",
            "اشرح الاحتمال",
            "الاحتمال الشرطي يتطلب أن احتمال الحدث المعطى غير معدوم.",
        ),
        ("physics", "اشرح القذف", "حركة القذف تخضع للجاذبية مع إهمال مقاومة الهواء."),
        (
            "electrical_engineering",
            "اشرح المكثفة",
            "المكثفة في دارة مثالية لها ثابت الزمن RC.",
        ),
        (
            "history_geography",
            "اشرح الحرب الباردة",
            "الحرب الباردة صراع دولي في سياق زمني معين.",
        ),
        (
            "arabic",
            "اشرح الإعراب",
            "الإعراب مرتبط بالوظيفة النحوية وموقع الكلمة في الجملة.",
        ),
        (
            "natural_sciences",
            "اشرح الوراثة",
            "الوراثة انتقال الصفات والمورثات في شروط التكاثر.",
        ),
    ],
)
def test_nested_support_is_one_subject_neutral_contract(
    services, subject, question, body
):
    t = actual_tools(services, question, {"s": body})
    t.study_scope.subject = subject
    prepare_body_choices(t)
    schema = assessment_tool(t)["function"]["parameters"]
    assert "coverage" not in schema["properties"]
    item = schema["$defs"]["NamedRequirement"]
    assert set(item["required"]) == {"id", "description", "supports"}
    assert set(schema["$defs"]["RequirementSupport"]["required"]) == {
        "source_id",
        "evidence_id",
    }
    args = nested(synthetic())
    d, _ = parse_assessment(call("assess_context", args), t)
    assert d.decision == "sufficient" and t.covered_sources == {"s"}
    assert {i for s in d.coverage for i in s.requirement_ids} == {"g", "r", "c"}
    assert all(s.quote == body for s in d.coverage)  # server-owned, not retyped
    assert len(d.coverage) == 3
    t.source_evidence.clear()
    prepare_body_choices(t)
    assert assessment_tool(t)["function"]["parameters"] == schema


@pytest.mark.parametrize(
    "fault", ["empty", "unknown", "mismatch", "outside", "gap", "hybrid", "duplicate"]
)
def test_nested_support_never_invents_or_promotes_evidence(services, fault):
    t = actual_tools(
        services,
        "اشرح الاحتمال",
        {"a": "الاحتمال الشرطي يتطلب P(A)>0.", "b": "الاحتمال الشرطي يتطلب P(A)>0."},
    )
    prepare_body_choices(t)
    args = nested(synthetic())
    if fault == "empty":
        args["requirements"]["conditions"][0]["supports"] = []
    if fault == "unknown":
        args["requirements"]["goals"][0]["supports"][0]["evidence_id"] = "R1:E999"
    if fault == "mismatch":
        args["requirements"]["goals"][0]["supports"][0]["evidence_id"] = "R2:E1"
    if fault == "outside":
        args["requirements"]["goals"][0]["supports"][0] = {
            "source_id": "R2",
            "evidence_id": "R2:E1",
        }
    if fault == "gap":
        args["gaps"] = ["Applicable essential condition not supported."]
    if fault == "hybrid":
        args["coverage"] = synthetic()["coverage"]
    if fault == "duplicate":
        args["requirements"]["conditions"][0]["id"] = "g"
    if fault == "hybrid":
        with pytest.raises(AssessmentContractError):
            parse_assessment(call("assess_context", args), t)
    else:
        d, _ = parse_assessment(call("assess_context", args), t)
        assert d.decision == "uncertain"
    assert not t.coverage_validated and not t.references_ready
    assert not t.covered_sources
    if fault in {"empty", "unknown", "mismatch", "outside", "gap"}:
        assert (
            not t.assessment_contract_errors
        )  # actual gap/invalid evidence, no guessed repairs


def test_actual_run12_declared_but_unlinked_goal_is_repairable_not_accepted(services):
    t = actual_tools(
        services,
        "اشرح المشتقة",
        {
            "s": "المشتقة واتجاه تغير الدالة: يشترط قابلية الاشتقاق على المجال وتغير إشارة المشتقة لتطبيق مبرهنة القيم الحدية."
        },
    )
    prepare_body_choices(t)
    d, _ = parse_assessment(call("assess_context", REPLAY["assessments"][0]["args"]), t)
    assert d.decision == "uncertain" and not t.coverage_validated
    assert "MISSING_CURRENT_GOAL_SUPPORT_LINK" in t.assessment_contract_errors
    reasons = services.db.rows(
        "SELECT details FROM audit WHERE action='context_support_rejected'"
    )
    assert reasons  # internal codes, no student/source text


@pytest.mark.asyncio
async def test_legacy_unlinked_goal_repairs_once_to_nested_then_n_followups_reuse(
    services,
):
    n, _, user, chat, aliases = await setup(services)
    routes = router(services, aliases, [[n]])

    class NestedTutor(Tutor):
        async def decision_stream(self, messages, tools):
            self.assessments.append(messages)
            from tests.test_context_decisions import assessment_state

            state = assessment_state(messages)
            if not state["actual_source_bodies"]:
                args = {
                    "decision": "missing_reference",
                    "source_ids": [],
                    "requirements": {
                        "goals": [],
                        "rules": [],
                        "conditions": [],
                        "prerequisites": [],
                    },
                }
            elif len(self.assessments) == 2:
                args = grouped(supported_decision([n], messages))
                args["coverage"][0]["requirement_ids"] = ["rule"]
            else:
                args = nested(supported_decision([n], messages))
            yield {"type": "result", "message": call("assess_context", args)}

    tutor = NestedTutor([], [answer([n])] * 3)
    services.chat_factory = lambda cfg, key: tutor
    for question in ["اشرح القذف", "وضح نفس الفكرة", "لم أفهم الخطوة الثانية"]:
        result = await run(services, user, chat, question)
        assert result["status"] == "COMPLETED", result
    assert len(routes) == 1 and len(tutor.assessments) == 5 and len(tutor.work) == 3
    repairs = services.db.rows(
        "SELECT * FROM audit WHERE action='context_contract_repair'"
    )
    assert len(repairs) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", ["", "https://private.invalid/S104", "a\nb", 3])
async def test_malformed_clarification_is_bounded_and_never_executes_a_read(
    services, bad
):
    _, _, user, chat, aliases = await setup(services)
    plan = copy.deepcopy(REPLAY["bad_clarification"])
    plan["question"] = bad
    plan["goals"][0]["ids"] = [next(iter(aliases.values()))]
    routes = router(services, aliases, [plan])
    tutor = Tutor([("uncertain", [])], [])
    services.chat_factory = lambda cfg, key: tutor
    result = await run(services, user, chat, "اشرح القذف")
    assert result["status"] == "COMPLETED", result
    assert len(routes) == 1 and not tutor.work
    assert not services.db.rows(
        "SELECT * FROM run_reference_state WHERE run_id=?", (result["id"],)
    )
    assert not services.db.rows(
        "SELECT * FROM loaded_context WHERE conversation_id=?", (chat,)
    )


@pytest.mark.asyncio
async def test_malformed_clarification_with_fabricated_id_still_rejected(services):
    _, _, user, chat, aliases = await setup(services)
    plan = copy.deepcopy(REPLAY["bad_clarification"])
    plan["goals"][0]["ids"] = ["S999999"]
    routes = router(services, aliases, [plan])
    services.chat_factory = lambda cfg, key: Tutor([("uncertain", [])], [])
    result = await run(services, user, chat, "اشرح القذف")
    assert result["status"] == "FAILED" and result["error"] == "INVALID_INDEX_ROUTE"
    assert len(routes) == 1
    with pytest.raises(ModelError):
        parse_route(plan, set(aliases.values()))


@pytest.mark.asyncio
async def test_exact_recorded_m19_noread_plan_has_safe_repair_and_metered_usage(
    services,
):
    _, _, user, chat, aliases = await setup(services)
    row = services.db.one("SELECT * FROM context_selectors")
    router(services, aliases, [REPLAY["bad_clarification"]])
    coordinator = FullIndexCoordinator(services, row)
    from bac.agent.engine import AgentEngine

    rid = AgentEngine(services).enqueue(chat, user, "اشرح القذف")
    result = await coordinator.decision(
        {"id": rid, "user_id": user["id"]}, "", {}, router_function(), {"S104"}
    )
    assert result["status"] == "clarify" and result["selected_ids"] == []
    assert result["question"].endswith("؟") and result["goals"] == []
    audit = services.db.one(
        "SELECT details FROM audit WHERE action='router_clarification_repaired' AND target=?",
        (rid,),
    )
    assert json.loads(audit["details"]) == {
        "reason_codes": ["INVALID_CLARIFICATION_QUESTION"]
    }

    usage = services.db.one("SELECT * FROM model_usage WHERE run_id=?", (rid,))
    assert usage["status"] == "safe_clarification"
    assert usage["input_tokens"] == 100 and usage["output_tokens"] == 20


@pytest.mark.asyncio
async def test_m24_mixed_history_and_teaching_on_actual_google_wire(services):
    n, _, user, chat, aliases = await setup(services)
    Tools(services, user, chat).load(n)
    mid = uid("message")
    quote = "أظن أن الفكرة الأولى صحيحة"
    services.db.execute(
        "INSERT INTO messages(id,conversation_id,role,content,blocks,created_at) VALUES(?,?,?,?,?,?)",
        (mid, chat, "user", quote, "[]", 0),
    )
    routes = router(services, aliases, [])
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if (
            body.get("tool_choice", {}).get("function", {}).get("name")
            == "assess_context"
        ):
            schema = body["tools"][0]["function"]["parameters"]
            assert "coverage" not in schema["properties"]
            return response(
                "assess_context", nested(supported_decision([n], body["messages"]))
            )
        manifest = {t["function"]["name"]: t["function"] for t in body["tools"]}
        assert not {"write_learning_note", "delete_learning_note"} & manifest.keys()
        assert (
            "history_evidence" in manifest["render_answer"]["parameters"]["properties"]
        )
        assert "implication, converse" in body["messages"][0]["content"]
        if len(requests) == 2:
            return response("read_conversation_history", {"student_only": True})
        return response(
            "render_answer",
            {
                "response_kind": "teaching",
                "source_ids": [n],
                "blocks": [
                    {
                        "type": "text",
                        "text": "ذكرت اعتقادا دون دليل كاف للحكم بإتقانك؛ نقترح مثالا جديدا لفهم الفكرة.",
                    }
                ],
                "history_evidence": [
                    {"block_index": 0, "message_id": mid, "quote": quote}
                ],
            },
        )

    services.chat_factory = lambda cfg, key: OpenAIChat(
        cfg | {"base_url": BASE},
        "fixture-only",
        transport=httpx.MockTransport(handler),
    )
    result = await run(services, user, chat, "لخص أخطائي خلال المحادثة ثم اقترح تمرينا")
    assert result["status"] == "COMPLETED", result
    assert len(requests) == 3 and not routes
    assert not services.db.rows(
        "SELECT * FROM learning_notes WHERE user_id=?", (user["id"],)
    )
    assert (
        len(
            services.db.rows(
                "SELECT * FROM model_usage WHERE run_id=?", (result["id"],)
            )
        )
        == 3
    )
    public = js(
        services.db.rows(
            "SELECT content,blocks FROM messages WHERE conversation_id=? AND role='assistant'",
            (chat,),
        )
    )
    assert mid not in public and n not in public and "history_evidence" not in public


@pytest.mark.parametrize(
    "tool,args",
    [
        ("write_learning_note", {"content": "Unrequested observation"}),
        ("delete_learning_note", {"id": "unrequested-note"}),
    ],
)
def test_history_review_cannot_mutate_notes_even_with_fabricated_tool_call(
    services, tool, args
):
    t = actual_tools(services, "لخص أخطائي خلال المحادثة", {})
    t.history_summary_requested = True
    with pytest.raises(ValueError, match="read-only"):
        t.execute(tool, args)
    assert not services.db.rows(
        "SELECT * FROM learning_notes WHERE user_id=?", (t.user["id"],)
    )


def test_m03_recorded_computation_does_not_prove_false_converse():
    # Authored fixed counterexamples, NOT execution of recorded model code.
    # Non-strict local maximum/minimum definitions admit a constant function.
    # This test diagnoses the recorded claim; it is not a prose truth oracle.
    import sympy as sp

    x = sp.symbols("x", real=True)
    derivative = sp.diff(x**3, x)
    assert derivative == 3 * x**2 and derivative.subs(x, 0) == 0
    assert (-1) ** 3 < 0 < 1**3  # stationary point is not automatically an extremum
    f = sp.Integer(7)
    assert sp.diff(f, x) == 0  # no derivative sign change at any point
    assert all(
        f.subs(x, a) <= f.subs(x, 0) and f.subs(x, a) >= f.subs(x, 0)
        for a in [-1, 0, 1]
    )
    assert REPLAY["M03_false_rule"] == "يجب أن تتغير إشارة المشتقة"


@pytest.mark.asyncio
async def test_google_python_claim_binding_survives_wire_and_server_validation(
    services, monkeypatch
):
    from bac.science.python_runner import PythonRunner

    n, _, user, chat, aliases = await setup(services)
    Tools(services, user, chat).load(n)
    routes = router(services, aliases, [])
    label = "نتيجة الحساب 5."

    def execute(self, args):
        return {
            "status": "computed",
            "outputs": {"sum": 5},
            "checks": [
                {
                    "label": label,
                    "status": "passed",
                    "evidence": {
                        "observed": 5,
                        "expected": 5,
                        "relation": "equal",
                        "tolerance": 0,
                    },
                },
            ],
            "stdout": "",
        }

    monkeypatch.setattr(
        PythonRunner, "execute", execute
    )  # Never execute model code on host.
    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if (
            body.get("tool_choice", {}).get("function", {}).get("name")
            == "assess_context"
        ):
            return response(
                "assess_context", nested(supported_decision([n], body["messages"]))
            )
        render = next(
            t["function"]
            for t in body["tools"]
            if t["function"]["name"] == "render_answer"
        )
        assert "checked_claims" in render["parameters"]["properties"]
        if len(requests) == 2:
            return response("run_python", {"code": 'emit("sum", 2+3)'})
        result = json.loads(
            next(
                m["content"] for m in reversed(body["messages"]) if m["role"] == "tool"
            )
        )
        return response(
            "render_answer",
            {
                "response_kind": "teaching",
                "source_ids": [n],
                "blocks": [{"type": "text", "text": label}],
                "checked_claims": [
                    {
                        "block_index": 0,
                        "claim": label,
                        "result_id": result["result_id"],
                        "check_index": 0,
                    }
                ],
            },
        )

    services.chat_factory = lambda cfg, key: OpenAIChat(
        cfg | {"base_url": BASE},
        "fixture-only",
        transport=httpx.MockTransport(handler),
    )
    result = await run(services, user, chat, "احسب وتحقق من المثال في الدرس")
    assert result["status"] == "COMPLETED", result
    assert len(requests) == 3 and not routes
    assert (
        len(
            services.db.rows(
                "SELECT * FROM scientific_results WHERE run_id=?", (result["id"],)
            )
        )
        == 1
    )
    assert (
        len(
            services.db.rows(
                "SELECT * FROM model_usage WHERE run_id=?", (result["id"],)
            )
        )
        == 3
    )
