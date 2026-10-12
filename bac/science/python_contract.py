"""Ordinary Python input and bounded, untrusted execution output."""

import json
from typing import Any, Literal
from pydantic import Field
from bac.agent.models import Strict
from bac.science.contracts import Plot, Diagram


class PythonCode(Strict):
    code: str = Field(min_length=1, max_length=12000)
    inputs: dict[str, Any] = Field(default_factory=dict, max_length=32)


class ComparisonEvidence(Strict):
    observed: float | int | str | bool
    expected: float | int | str | bool
    relation: Literal[
        "equal", "not_equal", "less", "less_equal", "greater", "greater_equal"
    ] = "equal"
    tolerance: float = Field(default=0, ge=0, le=1)


class PythonCheck(Strict):
    label: str = Field(min_length=1, max_length=160)
    status: Literal["passed", "failed", "inconclusive"]
    details: str = Field(default="", max_length=500)
    evidence: ComparisonEvidence | None = None


class PythonOutput(Strict):
    outputs: dict[str, Any] = Field(default_factory=dict, max_length=32)
    stdout: str = Field(default="", max_length=4096)
    checks: list[PythonCheck] = Field(default_factory=list, max_length=32)


def compare(proof):
    a, b, tolerance, relation = (
        proof["observed"],
        proof["expected"],
        proof["tolerance"],
        proof["relation"],
    )
    if (
        isinstance(a, str)
        or isinstance(b, str)
        or isinstance(a, bool)
        or isinstance(b, bool)
    ):
        if (
            type(a) is not type(b)
            or relation not in {"equal", "not_equal"}
            or tolerance
        ):
            raise ValueError("Invalid comparison types")
        equal = a == b
    else:
        equal = abs(a - b) <= tolerance
    return {
        "equal": lambda: equal,
        "not_equal": lambda: not equal,
        "less": lambda: a < b,
        "less_equal": lambda: a <= b,
        "greater": lambda: a > b,
        "greater_equal": lambda: a >= b,
    }[relation]()


def validate_output(raw):
    # Even the runtime's transport can be replaced by ordinary Python code.
    # Never trust a supplied badge, ID, scope, HTML, result or resource metadata.
    value = PythonOutput.model_validate(raw).model_dump()
    json.dumps(value, allow_nan=False)
    for check in value["checks"]:
        proof = check.get("evidence")
        if proof:
            outcome = compare(proof)
            if check["status"] != ("passed" if outcome else "failed"):
                raise ValueError("Check status disagrees with emitted comparison")
    # Reject non-finite values at every depth.
    json.dumps(value, allow_nan=False)  # Reject non-finite values at every depth.
    output = dict(value)
    for name, schema in (("chart", Plot), ("diagram", Diagram)):
        if name in value["outputs"]:
            data = schema.model_validate(value["outputs"][name]).model_dump()
            if name == "chart" and data["kind"] == "line":
                for series in data["series"]:
                    if any(a >= b for a, b in zip(series["x"], series["x"][1:])):
                        raise ValueError(
                            "Line chart x values must increase; split discontinuities into separate series"
                        )
            output[name] = data
            del output["outputs"][name]
    statuses = {c["status"] for c in value["checks"]}
    output["status"] = (
        "failed"
        if "failed" in statuses
        else "inconclusive"
        if "inconclusive" in statuses
        else "computed"
    )
    output["origin"] = "executed_python"
    output["scope"] = (
        "Actual execution of model-written code and its reported checks only. "
        "Not independent certification of code, assumptions, domain, interpretation or the whole answer."
    )
    return output


DESCRIPTION = """Execute ordinary Python in a fresh isolated container: imports, functions, loops and comprehensions are supported. Use this ONE tool for all programmatically checkable work (arithmetic, equations, domains, derivatives, integrals, limits, units, statistics and plots), not specialized calculator tools. Available: standard library, sympy, numpy, scipy, pint. No network, platform files, secrets or persistent state. Explicit JSON inputs are in inputs; emit("name", JSON_value) returns a result (convert SymPy values with str(), NumPy arrays with .tolist()). print() returns bounded text. check("specific claim", bool_or_None, "assumptions/tolerance") reports only a check your code actually performed; None is inconclusive. For an asserted checked claim, pass evidence={"observed": computed_scalar, "expected": independently_derived_scalar, "relation":"equal", "tolerance":0} to check(...). Other relations: not_equal, less, less_equal, greater, greater_equal. Convert library scalar types to ordinary finite JSON numbers/strings/bools. Use actual computed observations, not constants or print("OK"); compare the claimed interval/domain/units/coordinates to an independent derivation as applicable. Bind this exact check label to the exact public claim using render_answer.checked_claims. Server validation checks emitted comparisons and provenance, NOT independent truth of model-written code. Successful execution is not proof of the whole answer. For graphs emit("chart", {"title":"...","x_label":"...","y_label":"...","kind":"line","series":[{"label":"...","x":[0,1],"y":[0,1]}]}); use 2..401 finite points and 1..4 series; split poles/discontinuities; null y represents a gap. For geometry emit("diagram", bounded JSON geometry), never HTML/SVG or file paths. Reuse the returned result_id in graph/equation blocks; never supply result data to render_answer. Short code and small outputs; execution has time/memory/output limits. No source credit is granted by execution."""
