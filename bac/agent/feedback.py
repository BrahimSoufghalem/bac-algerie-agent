"""Bounded actionable private feedback; never sent to the student's drawer."""

from pydantic import ValidationError
from fastapi import HTTPException

EXAMPLES = {
    "plot_function": {
        "expression": "v0y-g*t",
        "variable": "t",
        "values": {"v0y": "10", "g": "9.8"},
        "lower": 0,
        "upper": 2,
        "samples": 41,
        "title": "Illustrative vertical velocity",
        "x_label": "time (s)",
        "y_label": "velocity (m/s)",
    },
    "plot_data": {
        "title": "Illustrative velocity",
        "x_label": "time (s)",
        "y_label": "velocity (m/s)",
        "kind": "line",
        "series": [{"label": "v", "x": [0, 1, 2], "y": [10, 0.2, -9.6]}],
    },
    "run_scientific_code": {
        "code": 'ts = linspace(0, 2, 21)\nys = []\nfor t in ts:\n    ys = ys + [v0y - g*t]\nemit("time", ts)\nemit("velocity", ys)',
        "inputs": {"v0y": 10, "g": 9.8},
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
    if name in EXAMPLES:
        result["example"] = EXAMPLES[name]
        result["example_note"] = (
            "Illustrative syntax only; these numeric values are not supplied by the student or their source."
        )
    return result
