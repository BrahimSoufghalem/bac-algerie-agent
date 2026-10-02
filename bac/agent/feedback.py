"""Bounded actionable private feedback; never sent to the student's drawer."""

from pydantic import ValidationError

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
