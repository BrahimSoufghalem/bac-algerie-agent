"""Narrow format repairs, not mathematical certification or relaxed provenance."""

import copy
import re

# Exactly two slashes before a known command, ONLY inside a math zone.
# Three slashes (matrix row boundary + command) and unknown macros are untouched.
COMMANDS = r"(?:mathbb|mathcal|mathbf|mathrm|text|frac|dfrac|tfrac|sqrt|infty|implies|Rightarrow|rightarrow|left|right|quad|qquad|in|notin|neq|ne|leq|geq|le|ge|nearrow|searrow|cdot|times|sum|prod|int|lim|ln|log|sin|cos|tan|exp|alpha|beta|gamma|delta|Delta|theta|lambda|mu|pi|sigma|tau|varepsilon|epsilon)"
DOUBLED = re.compile(r"(?<!\\)\\\\(?=" + COMMANDS + r"\b)")
# Code always wins over math matching. Escaped dollar signs are not delimiters.
ZONES = re.compile(
    r"(`{3,}[^\n]*\n.*?\n`{3,}|`+[^`\n]*`+)|(\$\$[\s\S]*?\$\$|(?<!\\)\$(?!\$)(?:\\.|[^$\n])*?(?<!\\)\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\])",
    re.M | re.S,
)


def normalize_latex(text):
    return DOUBLED.sub(lambda _: "\\", text)


def normalize_math_text(text):
    return ZONES.sub(
        lambda m: m.group(0) if m.group(1) else normalize_latex(m.group(0)), text
    )


def explicit_plot(question):
    q = question.casefold()
    if re.search(
        r"(?:لا\s+(?:ترسم|ترسُم)|بدون\s+رسم|دون\s+رسم|don['’]?t\s+(?:plot|draw)|no\s+(?:plot|graph)|sans\s+(?:graphe|graphique)|ne\s+trace\s+pas)",
        q,
    ):
        return False
    if re.search(
        r"(?:كيف\s+(?:أرسم|ارسم|نرسم)|how\s+(?:to|do\s+i)\s+(?:draw|plot)|comment\s+tracer)",
        q,
    ):
        return False
    return bool(
        re.search(
            r"(?:ارسم|أرسم|رسم\s+(?:المنحنى|منحنى|بياني)|تمثيل\s+بياني|\bplot\b|\bdraw\b.*\b(?:graph|curve)\b|\btrace[rz]?\b.*\b(?:courbe|graphe)\b)",
            q,
        )
    )


def prepare_answer(args, question, scientific):
    if not isinstance(args, dict):
        return args
    value = copy.deepcopy(args)
    blocks = value.get("blocks")
    if not isinstance(blocks, list):
        return value
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        # Only unambiguous legacy shapes; unknown fields are never discarded.
        if set(block) == {"text"}:
            block["type"] = "text"
        elif set(block) == {"latex"}:
            block["type"] = "equation"
        elif set(block) == {"graph"} and isinstance(block["graph"], str):
            blocks[i] = block = {"type": "graph", "result_id": block["graph"]}
        if block.get("type") == "equation" and isinstance(block.get("latex"), str):
            block["latex"] = normalize_latex(block["latex"])
        elif block.get("type") == "text" and isinstance(block.get("text"), str):
            block["text"] = normalize_math_text(block["text"])
        elif block.get("type") == "table":
            for key in ("headers", "rows"):
                cells = block.get(key)
                if isinstance(cells, list):
                    block[key] = [
                        normalize_math_text(c)
                        if isinstance(c, str)
                        else [
                            normalize_math_text(v) if isinstance(v, str) else v
                            for v in c
                        ]
                        if isinstance(c, list)
                        else c
                        for c in cells
                    ]
    # Keep a REAL chart from this run when a format retry drops it. No synthetic data,
    # stale DB lookup, wrong-result replacement, or unsolicited graph is permitted.
    if (
        explicit_plot(question)
        and value.get("response_kind", "teaching") in {"teaching", "calculation"}
        and not any(isinstance(b, dict) and b.get("type") == "graph" for b in blocks)
    ):
        charts = [
            rid
            for rid, result in scientific.items()
            if isinstance(result.get("output"), dict)
            and result["output"].get("status") == "computed"
            and (result["output"].get("chart") or result["output"].get("diagram"))
        ]
        if len(charts) == 1:
            blocks.append({"type": "graph", "result_id": charts[0]})
        elif len(charts) > 1:
            raise ValueError(
                "Requested graph missing: choose the relevant actual result_id; do not discard computed graphs during format repair"
            )
    return value
