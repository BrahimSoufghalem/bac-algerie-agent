"""Bounded actionable private feedback; never sent to the student's drawer."""

from pydantic import ValidationError
from fastapi import HTTPException
from bac.science.registry import CONTRACTS

EXAMPLES = {
    "run_python": {
        "code": 'import sympy as sp\nx = sp.symbols("x", real=True)\nf = x**3\nd = sp.diff(f, x)\nemit("derivative", str(d))\ncheck("derivative identity", bool(sp.simplify(d-3*x**2) == 0), "real x; symbolic identity only")',
        "inputs": {},
    },
}


def tool_feedback(name, exc):
    result = {
        "error": "TOOL_INPUT_OR_SOURCE_ERROR",
        "message": str(getattr(exc, "detail", str(exc)))[:500],
        "instruction": (
            "Inspect this error and the tool schema, correct the identified fields/syntax, and "
            "try a materially corrected call. Do not repeat identical invalid inputs. "
            "No successful result/source credit exists for this failed call. "
            "If correction is impossible, give a brief honest clarification/limitation, "
            "never fabricate a graph or an unread lesson."
        ),
    }
    if name in {
        "get_section",
        "get_lesson_full",
        "get_lesson_part",
        "list_lesson_parts",
        "get_document_metadata",
        "get_table_of_contents",
        "search_within_node",
        "get_exam_with_solution",
        "get_exercise_collection",
        "inspect_source_image",
        "read_private_page",
    }:
        if isinstance(exc, HTTPException):
            code = {
                404: "SOURCE_UNAVAILABLE",
                410: "SOURCE_UNAVAILABLE",
                401: "SOURCE_PERMISSION_DENIED",
                403: "SOURCE_PERMISSION_DENIED",
                409: "SOURCE_NOT_READY",
            }.get(exc.status_code)
            if code:
                result["error"] = code
        elif isinstance(exc, ValueError) and str(exc).startswith(
            "Requested node is not a "
        ):
            result["error"] = "SOURCE_KIND_MISMATCH"
    if isinstance(exc, ValidationError):
        result["issues"] = [
            {
                "field": ".".join(str(x) for x in e["loc"]),
                "type": e["type"],
                "message": e["msg"][:160],
            }
            for e in exc.errors(include_input=False, include_url=False)[:8]
        ]
    example_name = name
    if name in CONTRACTS or name == "plot_from_result":
        example_name = "run_python"
        result["replacement_tool"] = "run_python"
        result["instruction"] = (
            "This specialized computation tool is retired. Use ordinary Python via run_python. "
            + result["instruction"]
        )
    if example_name in EXAMPLES:
        result["example"] = EXAMPLES[example_name]
        result["example_note"] = (
            "Illustrative syntax only; these numeric values are not supplied by the student or their source."
        )
    return result
