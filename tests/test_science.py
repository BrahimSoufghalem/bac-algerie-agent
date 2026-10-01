import hashlib
import json
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.agent.engine import AgentEngine
from bac.agent.tools import Tools
from bac.core.auth import create_user
from bac.core.config import Settings
from bac.core.db import js
from bac.science.runner import ScienceRunner
from bac.science.kernel import execute
from tests.test_agent import chat_and_config
from tests.test_api import login


def result(name, args):
    return execute(name, args)


def test_decimal_exact_numeric_and_explicit_tolerances():
    assert result("calculate", {"expression": "0.1+0.2"})["exact"] == "3/10"
    assert result("calculate", {"expression": "sqrt(16)+sin(pi/2)"})["exact"] == "5"
    p = {
        "expression": "m*c*dT",
        "values": {"m": "2", "c": "4200", "dT": "10"},
        "expected": "84000",
    }
    assert result("verify_calculation", p)["status"] == "passed"
    assert result("verify_calculation", p | {"expected": "8400"})["status"] == "failed"
    assert (
        result(
            "verify_calculation",
            {
                "expression": "1/3",
                "expected": "0.3333",
                "absolute_tolerance": 0,
                "relative_tolerance": 0,
            },
        )["status"]
        == "failed"
    )


@pytest.mark.parametrize(
    "expression",
    [
        "__import__('os')",
        "x.__class__",
        'open("/etc/passwd")',
        "[1,2]",
        "lambda x: x",
        "True",
        "1/0",
        "sqrt(-1)",
        "x/x",
    ],
)
def test_expression_danger_undefined_domain_and_boolean_rejected(expression):
    with pytest.raises((ValueError, SyntaxError)):
        result("calculate", {"expression": expression, "values": {"x": "0"}})


def test_equation_substitution_conditions_and_missing_values():
    base = {
        "lhs": "P*V",
        "rhs": "n*R*T",
        "values": {"P": "10", "V": "3", "n": "2", "R": "1", "T": "15"},
    }
    assert result("verify_equation", base)["status"] == "passed"
    constrained = base | {"conditions": [{"lhs": "T", "relation": "gt", "rhs": "20"}]}
    assert result("verify_equation", constrained)["status"] == "failed"
    missing = result("verify_equation", base | {"values": {"P": "10"}})
    assert missing["status"] == "inconclusive" and missing["missing_values"] == [
        "R",
        "T",
        "V",
        "n",
    ]
    with pytest.raises(ValueError):
        result("verify_equation", {"lhs": "x/x", "rhs": "1", "values": {"x": "0"}})


def test_symbolic_derivative_integral_solve_and_domain_preserved():
    assert (
        result("symbolic_math", {"operation": "differentiate", "expression": "x**3"})[
            "result"
        ]
        == "3*x**2"
    )
    assert (
        result("symbolic_math", {"operation": "integrate", "expression": "2*x"})[
            "result"
        ]
        == "x**2"
    )
    solved = result("symbolic_math", {"operation": "solve", "expression": "x**2-4"})
    assert solved["solution_set"] == "{-2, 2}" and all(
        x["substitution_passed"] for x in solved["solutions"]
    )
    assert (
        result(
            "symbolic_math", {"operation": "solve", "expression": "1/x", "other": "0"}
        )["solution_set"]
        == "EmptySet"
    )
    assert (
        result(
            "symbolic_math",
            {"operation": "compare", "expression": "(x+1)**2", "other": "x**2+2*x+1"},
        )["status"]
        == "passed"
    )
    assert (
        result(
            "symbolic_math", {"operation": "compare", "expression": "x/x", "other": "1"}
        )["status"]
        == "inconclusive"
    )
    assert (
        result("symbolic_math", {"operation": "simplify", "expression": "sqrt(x**2)"})[
            "result"
        ]
        == "Abs(x)"
    )
    assert (
        result(
            "symbolic_math",
            {
                "operation": "simplify",
                "expression": "sqrt(x**2)",
                "positive_symbols": ["x"],
            },
        )["result"]
        == "x"
    )
    assert (
        result("symbolic_math", {"operation": "solve", "expression": "x+y"})["status"]
        == "inconclusive"
    )


def test_positive_solve_and_multivariable_domains_do_not_fake_pass():
    positive = result(
        "symbolic_math",
        {"operation": "solve", "expression": "x**2-4", "positive_symbols": ["x"]},
    )
    assert positive["solution_set"] == "{2}"
    assert (
        result(
            "symbolic_math", {"operation": "compare", "expression": "y/y", "other": "1"}
        )["status"]
        == "inconclusive"
    )


def test_units_temperature_difference_and_dimensions():
    assert (
        result("convert_units", {"value": "1.2", "from_unit": "MPa", "to_unit": "Pa"})[
            "value"
        ]
        == "1200000.0"
    )
    assert (
        result("convert_units", {"value": "25", "from_unit": "degC", "to_unit": "K"})[
            "value"
        ]
        == "298.15"
    )
    assert (
        result(
            "convert_units", {"value": "10", "from_unit": "delta_degC", "to_unit": "K"}
        )["value"]
        == "10"
    )
    assert (
        result("convert_units", {"value": "36", "from_unit": "km/h", "to_unit": "m/s"})[
            "value"
        ]
        == "10.000000000000000000000000000000000000000000000000"
    )
    assert (
        result("convert_units", {"value": "3", "from_unit": "m", "to_unit": "s"})[
            "status"
        ]
        == "failed"
    )
    with pytest.raises(ValueError):
        result(
            "convert_units", {"value": "25", "from_unit": "degC/s", "to_unit": "K/s"}
        )
    p = {
        "lhs": "P*V",
        "rhs": "n*R*T",
        "units": {"P": "Pa", "V": "L", "n": "mol", "R": "J/(mol*K)", "T": "K"},
    }
    assert result("verify_dimensions", p)["status"] == "passed"
    assert (
        result("verify_dimensions", p | {"units": p["units"] | {"V": "m"}})["status"]
        == "failed"
    )
    assert (
        result(
            "verify_dimensions",
            {"lhs": "x+y", "rhs": "z", "units": {"x": "m", "y": "s", "z": "m"}},
        )["status"]
        == "inconclusive"
    )
    assert (
        result(
            "verify_dimensions",
            {"lhs": "sin(x)", "rhs": "y", "units": {"x": "m", "y": "1"}},
        )["status"]
        == "inconclusive"
    )
    assert (
        result(
            "verify_dimensions",
            {"lhs": "a", "rhs": "b", "units": {"a": "kg", "b": "s"}},
        )["status"]
        == "failed"
    )


def test_numeric_program_outputs_are_real_and_bounded():
    code = 'xs = linspace(0, 2, 21)\nys = []\nfor t in xs:\n    ys = ys + [v*t + 0.5*a*t**2]\nemit("x", xs)\nemit("y", ys)\nemit("mean", sum(ys)/len(ys))'
    r = result("run_scientific_code", {"code": code, "inputs": {"v": 3, "a": 2}})
    assert (
        r["outputs"]["y"][-1] == 10
        and r["iterations"] == 21
        and r["status"] == "computed"
    )
    assert (
        result(
            "run_scientific_code",
            {
                "code": 'x = 2\nif x > 1:\n    y = sqrt(16)\nelse:\n    y = 0\nemit("y", y)'
            },
        )["outputs"]["y"]
        == 4
    )


@pytest.mark.parametrize(
    "code",
    [
        "import os",
        "while True:\n    x = 1",
        'emit("x", open("/etc/passwd"))',
        'emit("x", __import__("socket"))',
        'emit("x", (1).__class__)',
        "x = [0]*1000000000",
        'for x in range(10000000):\n    emit("x", x)',
        "def f():\n    return 1",
        'emit("x", [x for x in range(10)])',
        'emit("x", 10**10000000)',
    ],
)
def test_scientific_program_refuses_capabilities_and_allocation(code):
    with pytest.raises((ValueError, SyntaxError)):
        result("run_scientific_code", {"code": code})


def test_plot_domains_shape_and_source_scope():
    p = {"expression": "1/x", "lower": -1, "upper": 1, "title": "Reciprocal"}
    r = result("plot_function", p)
    assert len(r["chart"]["series"]) == 2
    assert all(x < 0 for x in r["chart"]["series"][0]["x"]) and all(
        x > 0 for x in r["chart"]["series"][1]["x"]
    )
    assert (
        result("plot_function", p | {"expression": "sqrt(x)"})["chart"]["series"][0][
            "x"
        ][0]
        >= 0
    )
    d = {
        "title": "Data",
        "x_label": "time (s)",
        "y_label": "height (m)",
        "kind": "scatter",
        "series": [{"label": "A", "x": [1, 2], "y": [None, 4]}],
    }
    assert result("plot_data", d)["origin"] == "model_supplied_data"
    with pytest.raises(ValueError):
        result(
            "plot_data",
            d | {"kind": "line", "series": [{"label": "a", "x": [2, 1], "y": [1, 2]}]},
        )
    with pytest.raises(ValueError):
        result(
            "plot_data",
            d | {"series": [{"label": "a", "x": [1, 2], "y": [float("inf"), 2]}]},
        )


def test_child_process_isolation_deadline_and_no_unsafe_fallback(tmp_path):
    r = ScienceRunner(Settings())
    out = r.execute("calculate", {"expression": "2+2"})
    assert out["exact"] == "4" and out["limits"]["language"] == "restricted_numeric_AST"
    assert r.execute("calculate", {"expression": 'open("/etc/passwd")'})["error"]
    # A real child is killed by parent deadline, including module startup; no mocked computation.
    very_short = ScienceRunner(replace(Settings(), science_timeout=0.001))
    assert (
        very_short.execute(
            "symbolic_math", {"operation": "integrate", "expression": "exp(x**2)"}
        )["error"]
        == "SCIENTIFIC_TIMEOUT"
    )
    low_memory = ScienceRunner(replace(Settings(), science_memory_mb=16))
    assert (
        low_memory.execute("calculate", {"expression": "2+2"})["error"]
        == "SCIENTIFIC_RESOURCE_OR_PROCESS_LIMIT"
    )
    assert (
        r.execute("plot_data", {"bad": float("nan")})["error"]
        == "SCIENTIFIC_PROCESS_FAILURE"
    )
    assert r.execute("calculate", {"expression": "1+1"})["exact"] == "2"


def test_result_provenance_graph_link_and_no_forged_badges(services):
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    r = tools.execute("verify_calculation", {"expression": "2+2", "expected": "5"})
    a, _ = tools.answer(
        {"blocks": [{"type": "verification", "result_id": r["result_id"]}]}
    )
    assert a.blocks[0].result["output"]["status"] == "failed"
    assert any("لم ينجح" in x for x in a.warnings)
    with pytest.raises(ValueError):
        tools.answer({"blocks": [{"type": "verification", "result_id": "fake"}]})
    with pytest.raises(ValueError):
        tools.answer(
            {
                "blocks": [
                    {
                        "type": "verification",
                        "result_id": r["result_id"],
                        "result": {"status": "passed"},
                    }
                ]
            }
        )
    with pytest.raises(ValueError):
        tools.answer({"blocks": [{"type": "graph", "result_id": r["result_id"]}]})
    with pytest.raises(ValueError):
        tools.answer(
            {"blocks": [{"type": "equation", "latex": "2+2=5", "result_ids": ["fake"]}]}
        )
    code = tools.execute(
        "run_scientific_code",
        {
            "code": 'x = linspace(0, 2, 21)\ny = []\nfor t in x:\n    y = y + [t*t]\nemit("x", x)\nemit("y", y)'
        },
    )
    graph = tools.execute(
        "plot_from_result",
        {
            "result_id": code["result_id"],
            "x_output": "x",
            "y_output": "y",
            "title": "computed",
            "x_label": "x",
            "y_label": "x²",
        },
    )
    assert graph["output"]["chart"]["series"][0]["y"] == code["output"]["outputs"]["y"]
    assert graph["output"]["parent_result_id"] == code["result_id"]
    answer, _ = tools.answer(
        {"blocks": [{"type": "graph", "result_id": graph["result_id"]}]}
    )
    assert answer.blocks[0].result["output"]["chart"]["series"][0]["y"][-1] == 4
    with pytest.raises(ValueError):
        Tools(services, user, chat).answer(
            {"blocks": [{"type": "graph", "result_id": graph["result_id"]}]}
        )
    with pytest.raises(ValueError):
        tools.execute(
            "plot_from_result",
            {
                "result_id": "fake",
                "x_output": "x",
                "y_output": "y",
                "title": "x",
                "x_label": "x",
                "y_label": "y",
            },
        )


def test_scientific_results_private_api_integrity_and_delete(services):
    user, chat = chat_and_config(services)
    t = Tools(services, user, chat)
    r = t.execute("calculate", {"expression": "1+1"})
    c = TestClient(create_app(services))
    assert c.get("/api/science/results/" + r["result_id"]).status_code == 401
    h = login(c, "student@example.com")
    assert (
        c.get("/api/science/results/" + r["result_id"]).json()["output"]["exact"] == "2"
    )
    create_user(services.db, "other@example.com", "Strong-password-1", "Other")
    other = TestClient(create_app(services))
    login(other, "other@example.com")
    assert other.get("/api/science/results/" + r["result_id"]).status_code == 404
    services.db.execute(
        "UPDATE scientific_results SET output=? WHERE id=?", ("{}", r["result_id"])
    )
    assert c.get("/api/science/results/" + r["result_id"]).status_code == 409
    assert c.delete("/api/conversations/" + chat, headers=h).status_code == 200
    assert not services.db.rows("SELECT * FROM scientific_results")


@pytest.mark.asyncio
async def test_actual_agent_science_tools_records_sse_replay_and_no_fake_pass(services):
    user, chat = chat_and_config(services)

    class ScriptedScience:
        def __init__(self):
            self.step = 0

        async def stream(self, messages, definitions):
            self.step += 1
            if self.step == 1:
                name, args = (
                    "verify_calculation",
                    {"expression": "2+2", "expected": "5"},
                )
            else:
                r = json.loads(messages[-1]["content"])
                name, args = (
                    "render_answer",
                    {
                        "blocks": [
                            {"type": "text", "text": "النتيجة المقترحة غير صحيحة."},
                            {"type": "verification", "result_id": r["result_id"]},
                            {
                                "type": "text",
                                "text": "الصحيح هو 4، ولا توجد مراجعة رسمية.",
                            },
                        ]
                    },
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

    services.chat_factory = lambda cfg, key: ScriptedScience()
    e = AgentEngine(services)
    run = e.enqueue(chat, user, "تحقق")
    await e.process(e.claim())
    assert (
        services.db.one("SELECT status FROM agent_runs WHERE id=?", (run,))["status"]
        == "COMPLETED"
    )
    record = services.db.one("SELECT * FROM scientific_results")
    assert record["run_id"] == run
    assert (
        hashlib.sha256(record["output"].encode()).hexdigest() == record["output_sha256"]
    )
    saved = json.loads(
        services.db.one("SELECT blocks FROM messages WHERE role='assistant'")["blocks"]
    )
    assert saved[1]["result"]["output"]["status"] == "failed"
    events = services.db.rows("SELECT * FROM run_events WHERE run_id=?", (run,))
    end = next(json.loads(x["payload"]) for x in events if x["type"] == "tool_end")
    assert end["success"] is False and "تعذر" in end["label"]
    client = TestClient(create_app(services))
    login(client, "student@example.com")
    replay = client.get("/api/runs/" + run + "/events")
    assert replay.status_code == 200 and '"status":"failed"' in replay.text
    assert (
        client.get("/api/conversations/" + chat).json()["messages"][-1]["blocks"]
        == saved
    )


def test_budget_and_cancelled_runs_never_credit_scientific_result(services):
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    services.settings = replace(services.settings, max_tool_chars=1000)
    tools = Tools(services, user, chat)
    assert tools.execute(
        "run_scientific_code", {"code": 'emit("data", linspace(0, 2, 401))'}
    )["error"]
    assert not tools.scientific and not services.db.rows(
        "SELECT * FROM scientific_results"
    )
    services.settings = replace(services.settings, max_tool_chars=22000)
    e = AgentEngine(services)
    run = e.enqueue(chat, user, "test")
    e.claim()
    services.db.execute("UPDATE agent_runs SET cancel_requested=1 WHERE id=?", (run,))
    tools = Tools(services, user, chat, run)
    assert (
        tools.execute("calculate", {"expression": "2+2"})["error"]
        == "SCIENTIFIC_RUN_NO_LONGER_ACTIVE"
    )
    assert not tools.scientific


def test_diagram_geometry_is_finite_bounded_and_not_arbitrary_svg():
    p = {
        "title": "Force vectors",
        "x_min": -2,
        "x_max": 2,
        "y_min": -2,
        "y_max": 2,
        "elements": [
            {"kind": "circle", "x": 0, "y": 0, "radius": 0.5},
            {"kind": "vector", "x": 0, "y": 0, "x2": 1, "y2": 1, "label": "F"},
        ],
    }
    diagram = result("draw_diagram", p)
    assert (
        diagram["origin"] == "provided_geometry"
        and len(diagram["diagram"]["elements"]) == 2
    )
    for element in [
        {"kind": "circle", "x": 0, "y": 0, "radius": 3},
        {"kind": "vector", "x": 0, "y": 0},
        {"kind": "point", "x": 0, "y": 0, "svg": "<script>"},
    ]:
        with pytest.raises(ValueError):
            result("draw_diagram", p | {"elements": [element]})


def test_failed_verification_cannot_be_silently_hidden(services):
    user, chat = chat_and_config(services)
    t = Tools(services, user, chat)
    r = t.execute("verify_calculation", {"expression": "2+2", "expected": "5"})
    answer, _ = t.answer(
        {"blocks": [{"type": "text", "text": "I will omit the failed check"}]}
    )
    assert (
        answer.blocks[-1].type == "verification"
        and answer.blocks[-1].result_id == r["result_id"]
    )


def test_unreachable_program_branches_and_step_limit_are_rejected():
    with pytest.raises(ValueError):
        result(
            "run_scientific_code",
            {"code": 'x=0\nif x>1:\n    open("/etc/passwd")\nemit("x",x)'},
        )
    with pytest.raises(ValueError, match="LIMIT"):
        result(
            "run_scientific_code",
            {
                "code": 'for x in range(401):\n    for y in range(401):\n        z=x+y\nemit("z",z)'
            },
        )


def test_precision_does_not_erase_small_absolute_errors_in_large_numbers():
    p = {
        "expression": "1e99+1",
        "expected": "1e99",
        "absolute_tolerance": 0,
        "relative_tolerance": 0,
    }
    r = result("verify_calculation", p)
    assert r["status"] == "failed" and float(r["absolute_error"]) == 1
    check = result(
        "verify_equation",
        {
            "lhs": "1",
            "rhs": "1",
            "conditions": [{"lhs": "1e99+1", "relation": "eq", "rhs": "1e99"}],
        },
    )
    assert check["status"] == "failed"
