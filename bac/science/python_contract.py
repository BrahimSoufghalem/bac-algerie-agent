"""Ordinary Python input and bounded, untrusted execution output."""

import json
from typing import Any, Literal
from pydantic import Field
from bac.agent.models import Strict
from bac.science.contracts import Plot, Diagram


class PythonCode(Strict):
    code: str = Field(min_length=1, max_length=12000)
    inputs: dict[str, Any] = Field(default_factory=dict, max_length=32)


class PythonCheck(Strict):
    label: str = Field(min_length=1, max_length=160)
    status: Literal["passed", "failed", "inconclusive"]
    details: str = Field(default="", max_length=500)


class PythonOutput(Strict):
    outputs: dict[str, Any] = Field(default_factory=dict, max_length=32)
    stdout: str = Field(default="", max_length=4096)
    checks: list[PythonCheck] = Field(default_factory=list, max_length=32)


def validate_output(raw):
    # Even the runtime's transport can be replaced by ordinary Python code.
    # Never trust a supplied badge, ID, scope, HTML, result or resource metadata.
    value = PythonOutput.model_validate(raw).model_dump()
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


DESCRIPTION = """Execute ordinary Python in a fresh isolated container: imports, functions, loops and comprehensions are supported. Use this ONE tool for all programmatically checkable work (arithmetic, equations, domains, derivatives, integrals, limits, units, statistics and plots), not specialized calculator tools. Available: standard library, sympy, numpy, scipy, pint. No network, platform files, secrets or persistent state. Explicit JSON inputs are in inputs; emit("name", JSON_value) returns a result (convert SymPy values with str(), NumPy arrays with .tolist()). print() returns bounded text. check("specific claim", bool_or_None, "assumptions/tolerance") reports only a check your code actually performed; None is inconclusive. Successful execution is not proof of the whole answer. For graphs emit("chart", {"title":"...","x_label":"...","y_label":"...","kind":"line","series":[{"label":"...","x":[0,1],"y":[0,1]}]}); use 2..401 finite points and 1..4 series; split poles/discontinuities; null y represents a gap. For geometry emit("diagram", bounded JSON geometry), never HTML/SVG or file paths. Reuse the returned result_id in graph/equation blocks; never supply result data to render_answer. Short code and small outputs; execution has time/memory/output limits. No source credit is granted by execution."""
