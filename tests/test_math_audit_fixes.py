"""Offline regressions for the 21-published-turn live audit. No provider calls.

Fixed trusted Python programs in tests are not a host execution fallback for
model code. Passing checks here does not certify future stochastic answers.
"""

import json
import time
from pathlib import Path
import pytest
from pydantic import ValidationError
from bac.agent.answer_quality import (
    normalize_latex,
    normalize_math_text,
    prepare_answer,
    explicit_plot,
)
from bac.agent.models import Answer, ModelConfig
from bac.agent.tools import Tools
from bac.agent.rate_limit import InputPacer, input_pacer, reserve_input
from bac.agent.provider_errors import provider_diagnostic, safe_provider_diagnostic
from bac.library.part_metadata import local_part_metadata
from bac.learning.service import Learning
from bac.core.auth import create_user
from bac.core.db import uid, js
from benchmarks.math_live_support import rate_limit_resume

CHART = {"output": {"status": "computed", "chart": {"title": "local", "series": []}}}


@pytest.mark.parametrize(
    "command", ["mathbb", "infty", "implies", "frac", "ln", "sqrt", "quad", "nearrow"]
)
def test_narrow_math_macro_repair(command):
    assert normalize_latex("\\\\" + command) == "\\" + command
    assert normalize_math_text("$\\\\" + command + "{R}$") == "$\\" + command + "{R}$"


@pytest.mark.parametrize(
    "literal",
    [
        r"\\custom",
        r"\\\frac",
        r"\begin{matrix}a&b\\c&d\end{matrix}",
        "normal \\\\frac text",
        "`$\\\\frac$`",
        "```python\nx = '$\\\\frac$'\n```",
        r"\$ price \\frac",
    ],
)
def test_literal_code_matrix_and_unknown_macros_unchanged(literal):
    assert normalize_math_text(literal) == literal


@pytest.mark.parametrize(
    "q,yes",
    [
        ("ارسم منحنى ln(x)/x", True),
        ("plot ln(x)/x", True),
        ("trace la courbe", True),
        ("لا ترسم منحنى", False),
        ("بدون رسم بياني", False),
        ("كيف أرسم المنحنى؟", False),
        ("how to plot?", False),
        ("اشرح المشتقة", False),
    ],
)
def test_explicit_plot_intent(q, yes):
    assert explicit_plot(q) is yes


def test_real_plot_survives_format_retry_and_arguments_unchanged():
    args = {"blocks": [{"text": "شرح المنحنى"}]}
    repaired = prepare_answer(args, "ارسم المنحنى", {"real": CHART})
    assert args == {"blocks": [{"text": "شرح المنحنى"}]}
    assert repaired["blocks"] == [
        {"type": "text", "text": "شرح المنحنى"},
        {"type": "graph", "result_id": "real"},
    ]
    Answer.model_validate(repaired)
    tools = object.__new__(Tools)
    tools.run_id, tools.question, tools.scientific = (
        None,
        "ارسم المنحنى",
        {"real": CHART},
    )
    tools.sources = {}
    from bac.core.presentation import SourceTextGuard

    tools.source_text_guard = SourceTextGuard()
    result, _ = tools.answer(args)
    assert next(b for b in result.blocks if b.type == "graph").result == CHART


def test_no_synthetic_unsolicited_or_failed_graph_and_no_unknown_field_discard():
    args = {"blocks": [{"text": "شرح"}]}
    for question, scientific in [
        ("اشرح", {"real": CHART}),
        ("ارسم", {}),
        ("ارسم", {"bad": {"output": {"status": "failed", "chart": {"title": "x"}}}}),
    ]:
        assert len(prepare_answer(args, question, scientific)["blocks"]) == 1
    with pytest.raises(ValueError):
        prepare_answer(args, "ارسم", {"a": CHART, "b": CHART})
    with pytest.raises(ValidationError):
        Answer.model_validate(
            prepare_answer(
                {
                    "blocks": [
                        {"type": "graph", "result_id": "r", "result": {"chart": {}}}
                    ]
                },
                "ارسم",
                {"r": CHART},
            )
        )
    with pytest.raises(ValidationError):
        Answer.model_validate(
            prepare_answer(
                {"blocks": [{"text": "x", "secret": "must not silently drop"}]},
                "hi",
                {},
            )
        )


def test_graph_id_repair_still_requires_current_run_provenance():
    tools = object.__new__(Tools)
    tools.run_id, tools.question, tools.scientific = None, "ارسم", {}
    tools.sources = {}
    from bac.core.presentation import SourceTextGuard

    tools.source_text_guard = SourceTextGuard()
    with pytest.raises(ValueError, match="not computed/loaded"):
        tools.answer({"blocks": [{"graph": "invented"}]})


def note_context(s):
    user = create_user(s.db, "student@test.invalid", "Strong-password-1", "Student")
    chat, cfg, run, current, evidence = [
        uid(x) for x in ("chat", "cfg", "run", "msg", "msg")
    ]
    now = time.time()
    s.db.execute(
        "INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
        (chat, user, "Test", now, now),
    )
    s.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (cfg, "agent", "{}", s.vault.encrypt("fake-not-a-credential"), now),
    )
    for id, role, content, created in [
        (evidence, "user", "My solution is x=2; substituting gives 2*2=4.", now),
        (current, "user", "Explain again; I didn't understand this.", now + 1),
    ]:
        s.db.execute(
            "INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,?,?,?)",
            (id, chat, role, content, created),
        )
    s.db.execute(
        "INSERT INTO agent_runs(id,conversation_id,user_id,message_id,config_id,status,created_at) VALUES(?,?,?,?,?,'RUNNING',?)",
        (run, chat, user, current, cfg, now + 2),
    )
    return (
        s.db.one("SELECT * FROM users WHERE id=?", (user,)),
        chat,
        run,
        current,
        evidence,
    )


def test_mastery_must_be_student_evidence_and_remains_traceable(services):
    s = services
    user, chat, run, current, evidence = note_context(s)
    learning = Learning(s)
    note = {"category": "mastered", "content": "Tentative: solved this substitution."}
    with pytest.raises(ValueError, match="requires evidence"):
        learning.agent_note(user, run, note)
    with pytest.raises(ValueError, match="confusion"):
        learning.agent_note(
            user,
            run,
            note
            | {
                "evidence_message_id": current,
                "evidence_quote": "I didn't understand this.",
            },
        )
    quote = "substituting gives 2*2=4."
    value = learning.agent_note(
        user, run, note | {"evidence_message_id": evidence, "evidence_quote": quote}
    )
    assert (
        s.db.one("SELECT message_id FROM learning_notes WHERE id=?", (value["id"],))[
            "message_id"
        ]
        == evidence
    )
    audit = s.db.one("SELECT details FROM audit WHERE action='learning_note_evidence'")
    details = json.loads(audit["details"])
    assert details["message_id"] == evidence and len(details["quote_sha256"]) == 64
    assert quote not in audit["details"]
    assert (
        learning.agent_note(
            user, run, {"category": "goal", "content": "Practice substitution."}
        )["status"]
        == "saved"
    )


@pytest.mark.parametrize(
    "alter", ["assistant", "inactive", "foreign_chat", "future", "fabricated_quote"]
)
def test_reject_invalid_mastery_proof(services, alter):
    s = services
    user, chat, run, current, evidence = note_context(s)
    quote = "substituting gives 2*2=4."
    if alter == "assistant":
        s.db.execute("UPDATE messages SET role='assistant' WHERE id=?", (evidence,))
    elif alter == "inactive":
        s.db.execute("UPDATE messages SET active=0 WHERE id=?", (evidence,))
    elif alter == "foreign_chat":
        other = uid("chat")
        s.db.execute(
            "INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
            (other, user["id"], "Other", 0, 0),
        )
        s.db.execute(
            "UPDATE messages SET conversation_id=? WHERE id=?", (other, evidence)
        )
    elif alter == "future":
        s.db.execute(
            "UPDATE messages SET created_at=created_at+100 WHERE id=?", (evidence,)
        )
    else:
        quote = "invented student solution"
    with pytest.raises(ValueError, match="exact quote"):
        Learning(s).agent_note(
            user,
            run,
            {
                "category": "mastered",
                "content": "Solved.",
                "evidence_message_id": evidence,
                "evidence_quote": quote,
            },
        )
    assert not s.db.rows("SELECT * FROM learning_notes")


def test_part_metadata_local_not_inherited_and_ignores_fences():
    text = "# [صفحة الكتاب 239 / صفحة PDF 239]\n# المتتالية الهندسية\nProse.\n```yaml\n# fake topic\nsummary: pretend\n```\n## المجموع\ncontent"
    meta = local_part_metadata(
        text,
        {
            "title": "المتتاليات",
            "summary": "كل أنواع المتتاليات",
            "covers": ["arithmetic", "geometric", "recurrence"],
        },
    )
    assert meta["title"] == "المتتالية الهندسية"
    assert meta["covers"] == ["المتتالية الهندسية", "المجموع"]
    assert "arithmetic" not in json.dumps(meta) and "fake topic" not in json.dumps(meta)
    assert (
        meta["content_chars"] == len(text)
        and meta["routing_summary_kind"] == "extractive_local"
    )


def test_existing_immutable_part_catalog_upgraded_in_memory(services):
    from bac.agent.full_index import build_catalog

    s = services
    owner = create_user(
        s.db, "owner@test.invalid", "Strong-password-1", "Owner", "owner"
    )
    now = time.time()
    s.db.execute(
        "INSERT INTO documents(id,title,kind,subject,track,source,published_version,owner_id,created_at) VALUES('d','Sequences','book','math','test','markdown','v',?,?)",
        (owner, now),
    )
    s.db.execute(
        "INSERT INTO versions(id,document_id,sequence,bookforge_id,status,created_at) VALUES('v','d',1,'md','PUBLISHED',?)",
        (now,),
    )
    parent = {
        "title": "Sequences",
        "summary": "ALL sequences",
        "covers": ["EVERYTHING"],
        "partial_lesson": True,
    }
    s.store.write(
        "published/part.md", b"# Geometric sequence\n## Sum\nSome actual content."
    )
    s.db.execute(
        "INSERT INTO published_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "part",
            "v",
            "d",
            None,
            "section",
            "Sequences",
            1,
            1,
            1,
            1,
            "published/part.md",
            js(parent),
        ),
    )
    index, mapping = build_catalog(s)
    assert (
        "Geometric sequence" in index
        and "EVERYTHING" not in index
        and "ALL sequences" not in index
    )
    assert mapping["S1"]["metadata"]["routing_summary_kind"] == "extractive_local"
    assert (
        json.loads(s.db.one("SELECT metadata FROM published_nodes")["metadata"])
        == parent
    )
    assert (
        s.store.read("published/part.md")
        == b"# Geometric sequence\n## Sum\nSome actual content."
    )


class Clock:
    def __init__(self):
        self.now, self.waits = 0.0, []

    def time(self):
        return self.now

    async def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds


@pytest.mark.asyncio
async def test_token_aware_pacing_settlement_unknown_and_oversized_request():
    c = Clock()
    p = InputPacer(c.time, c.sleep)
    first = await p.reserve(70, 100)
    p.settle(first, 40)
    await p.reserve(50, 100)
    await p.reserve(20, 100)
    assert c.waits == [60]
    await p.reserve(150, 100)
    assert c.now == 120
    # Above-budget prompt is allowed alone; no truncation or infinite wait.
    assert p.entries[-1][2] == 150
    p.settle(p.entries[-1], None)
    assert p.entries[-1][2] == 150


@pytest.mark.asyncio
async def test_shared_cooldown_and_cancellable_pacing():
    import asyncio

    c = Clock()
    p = InputPacer(c.time, c.sleep)
    p.rate_limited(53.9)
    await p.reserve(1, 100)
    assert c.waits == [53.9]

    async def cancelled(_):
        raise asyncio.CancelledError()

    q = InputPacer(c.time, cancelled)
    await q.reserve(99, 100)
    with pytest.raises(asyncio.CancelledError):
        await q.reserve(10, 100)
    assert len(q.entries) == 1


@pytest.mark.asyncio
async def test_google_native_and_openai_share_rate_budget_no_billing_mutation():
    native = {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-test",
        "input_tokens_per_minute": 12345,
    }
    compat = native | {
        "base_url": native["base_url"] + "/openai",
        "model": "models/gemini-test",
    }
    assert input_pacer(native, "fake")[0] is input_pacer(compat, "fake")[0]
    assert (
        input_pacer(native, "different-fake")[0] is not input_pacer(native, "fake")[0]
    )
    assert input_pacer(native | {"input_tokens_per_minute": 0}, "fake") == (None, 0)
    body = {"content": "نص"}
    copy = dict(body)
    p, r = await reserve_input(native, "fake", body)
    assert body == copy and r[2] > 0
    assert (
        ModelConfig(
            base_url="https://example.org", model="test", input_tokens_per_minute=0
        ).input_tokens_per_minute
        == 0
    )


def test_429_safe_delay_and_hint_no_credentials():
    secret = "synthetic-private-key"
    error = {
        "error": {
            "status": "RESOURCE_EXHAUSTED",
            "message": "input token quota: " + secret,
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "53.9667s",
                }
            ],
        }
    }
    d = provider_diagnostic(429, error, {}, "58")
    assert d["retry_after_seconds"] == 58 and d["hint"] == "PROVIDER_RATE_LIMITED"
    assert secret not in json.dumps(d)
    assert "retry_after_seconds" not in safe_provider_diagnostic(
        {"retry_after_seconds": float("nan")}
    )
    assert "retry_after_seconds" not in safe_provider_diagnostic(
        {"retry_after_seconds": "secret"}
    )
    assert (
        provider_diagnostic(
            429, {"error": {"message": "Please retry in 53.9667s."}}, {}
        )["retry_after_seconds"]
        == 53.9667
    )


def test_resume_only_last_unpublished_429_once_and_preserves_original_rows():
    rows = [{"number": 22, "status": "FAILED", "run_id": "r22", "reply": None}]
    requests = [
        {"run_id": "r22", "http_status": 429, "error_message": "retry in 53.9s"}
    ]
    assert rate_limit_resume(rows, requests) == (22, 53.9)
    for changed in [
        rows[-1] | {"status": "COMPLETED"},
        rows[-1] | {"reply": {"content": "published"}},
        rows[-1] | {"previous_attempts": [rows[-1]]},
    ]:
        with pytest.raises(ValueError):
            rate_limit_resume([changed], requests)
    with pytest.raises(ValueError):
        rate_limit_resume(rows, [{"run_id": "r22", "http_status": 401}])
    assert rows[-1]["run_id"] == "r22"


def test_report_nested_python_output_and_resumed_tokens(tmp_path):
    from benchmarks.report_math_live import make_evidence

    raw = tmp_path / "raw"
    raw.mkdir()
    rows = [
        {
            "id": "M22",
            "run_id": "new",
            "status": "COMPLETED",
            "previous_attempts": [{"run_id": "old"}],
            "reply": {"blocks": "[]"},
        }
    ]
    requests = [
        {
            "request_number": 1,
            "stage": "router",
            "run_id": "old",
            "input_tokens": None,
            "output_tokens": None,
        },
        {
            "request_number": 2,
            "stage": "teacher",
            "run_id": "new",
            "input_tokens": 12,
            "output_tokens": 3,
        },
    ]
    tools = [
        {
            "run_id": "new",
            "name": "run_python",
            "result": {
                "result_id": "actual",
                "output": {"status": "computed", "checks": [{"status": "passed"}]},
            },
        },
        {
            "run_id": "old",
            "name": "run_python",
            "result": {"error": "SCIENTIFIC_INPUT_OR_COMPUTATION_ERROR"},
        },
    ]
    for file, data in [
        ("results", rows),
        ("requests", requests),
        ("tool-audit", tools),
    ]:
        (raw / (file + ".json")).write_text(json.dumps(data))
    evidence = make_evidence(tmp_path)
    row = evidence["per_turn"][0]
    assert (
        row["python_attempts"] == 2
        and row["python_computed"] == 1
        and row["check_statuses"]["passed"] == 1
    )
    assert row["python_errors"] == ["SCIENTIFIC_INPUT_OR_COMPUTATION_ERROR"]
    assert row["attempt_count"] == 2 and row["known_usage"]["known_total_tokens"] == 15
    assert (
        row["known_usage"]["unknown_usage_requests"] == 1
        and not evidence["complete_run"]
    )


def test_trusted_regression_counterexamples_not_execution_only_badge():
    from bac.science.python_child import compute
    from bac.science.python_contract import validate_output

    code = """import sympy as sp
x=sp.symbols("x", real=True)
pa, pb = sp.Rational(2,5), sp.Rational(7,10)
pab = pa*pb
check("Independence does not imply equal conditionals", bool(pab/pa != pab/pb), "Positive unequal marginals")
for pa,pb,pab in [(sp.Rational(2,5),sp.Rational(7,10),0),(sp.Rational(1,2),sp.Rational(1,2),sp.Rational(1,4)),(sp.Rational(2,5),sp.Rational(7,10),sp.Rational(1,5))]:
    check("Conditionals equality iff zero intersection or equal positive marginals", bool((pab/pa==pab/pb)==(pab==0 or pa==pb)))
f=(x*x-1)/(x-1)
check("Current rational limit is 2, independent of historical examples", bool(sp.limit(f,x,1)==2), "Original domain excludes x=1")
check("Derivative-zero alone is not extremum", bool(sp.diff(x**3,x).subs(x,0)==0 and (-1)**3<0<1**3))
check("Non-differentiable extremum exists", bool(abs(-1)>abs(0) and abs(1)>abs(0)), "abs has no derivative at 0")
xs=[float(sp.Rational(i,10)) for i in range(1,31)]
import math
ys=[math.log(t)/t for t in xs]
check("Curve coordinates from current formula", all(abs(y-math.log(t)/t)<1e-12 for t,y in zip(xs,ys)), "x>0; tolerance 1e-12")
emit("chart",{"title":"f(x)","x_label":"x","y_label":"y","kind":"line","series":[{"label":"ln(x)/x","x":xs,"y":ys}]})
"""
    out = validate_output(compute({"code": code, "limits": {"output_chars": 16000}}))
    assert out["status"] == "computed" and len(out["checks"]) == 8
    assert all(c["status"] == "passed" for c in out["checks"])
    assert len(out["chart"]["series"][0]["x"]) == 30


def test_policy_current_claim_domain_graph_and_student_proof():
    import yaml

    prompt = yaml.safe_load(Path("config/agent.yaml").read_text())["system"]
    for required in [
        "Current corrections override old givens",
        "all required rules/conditions/dependencies",
        "multi-subject platform",
        "checked_claims",
        "preserve its actual result_id",
        "exact evidence_quote",
        "STUDENT solution",
        "Matplotlib is not installed",
    ]:
        assert required in prompt


@pytest.mark.asyncio
async def test_openai_adapter_paces_records_actual_and_sets_429_cooldown(monkeypatch):
    import httpx
    import bac.agent.provider as adapter
    from bac.agent.provider import OpenAIChat, ModelError

    c = Clock()
    pacer = InputPacer(c.time, c.sleep)
    reserved = []

    async def reservation(*args):
        entry = await pacer.reserve(100, 1000)
        reserved.append(entry)
        return pacer, entry

    monkeypatch.setattr(adapter, "reserve_input", reservation)
    cfg = {"base_url": "https://fixture.invalid/v1", "model": "offline"}
    success = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            },
        )
    )
    events = [
        e
        async for e in OpenAIChat(cfg, "fake", transport=success).stream(
            [{"role": "user", "content": "hi"}], []
        )
    ]
    assert (
        reserved[0][2] == 12
        and next(e for e in events if e["type"] == "usage")["data"]["prompt_tokens"]
        == 12
    )
    limited = httpx.MockTransport(
        lambda _: httpx.Response(
            429,
            headers={"retry-after": "54"},
            json={"error": {"status": "RESOURCE_EXHAUSTED", "message": "quota"}},
        )
    )
    with pytest.raises(ModelError, match="HTTP_429") as error:
        async for _ in OpenAIChat(cfg, "fake", transport=limited).stream(
            [{"role": "user", "content": "hi"}], []
        ):
            pass
    assert error.value.diagnostic["retry_after_seconds"] == 54
    assert pacer.cooldown_until == 54 and reserved[-1][2] == 100
    assert len(reserved) == 2  # No hidden retry.


@pytest.mark.asyncio
async def test_native_router_paces_and_sets_429_cooldown(monkeypatch):
    import httpx
    import bac.agent.full_index as adapter
    from bac.agent.provider import ModelError

    c = Clock()
    pacer = InputPacer(c.time, c.sleep)

    async def reservation(*args):
        return pacer, await pacer.reserve(100, 1000)

    monkeypatch.setattr(adapter, "reserve_input", reservation)
    cfg = {"base_url": adapter.BASE, "model": "gemini-test", "protocol": "google"}
    limited = httpx.MockTransport(
        lambda _: httpx.Response(
            429,
            json={
                "error": {
                    "status": "RESOURCE_EXHAUSTED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.RetryInfo",
                            "retryDelay": "90s",
                        }
                    ],
                }
            },
        )
    )
    with pytest.raises(ModelError, match="HTTP_429"):
        await adapter.call_router_llm(
            cfg, "fake", "system", {}, adapter.ROUTE_FUNCTION, transport=limited
        )
    assert pacer.cooldown_until == 90 and len(pacer.entries) == 1


def test_google_render_schema_remains_flat_and_explicit_no_http400_union():
    from bac.agent.compat import google_answer_tools
    from bac.agent.models import PresentedAnswer

    tool = {
        "type": "function",
        "function": {
            "name": "render_answer",
            "description": "Publish",
            "parameters": PresentedAnswer.model_json_schema(),
        },
    }
    schema = google_answer_tools([tool])[0]["function"]["parameters"]

    def keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(keys(v) for v in value.values()))
        if isinstance(value, list):
            return set().union(*(keys(v) for v in value))
        return set()

    assert not {"oneOf", "discriminator"} & keys(schema)
    block = schema["properties"]["blocks"]["items"]
    assert block["required"] == ["type"] and "result" not in block["properties"]
    assert "EVERY block" in block["properties"]["type"]["description"]
    assert "not source objects" in schema["properties"]["source_ids"]["description"]
