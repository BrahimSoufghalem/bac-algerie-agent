"""Public chat projection. Private provenance stays server-side, including old chats."""

import hashlib
import copy
import json
import re

INTERNAL = re.compile(
    r"(?:https?://[^\s\"<>)]*)?/api/(?:library|agent|owner|science)/[^\s\"<>)]*"
    r"|\b(?:book|node|asset|version|science|part|doc)_[a-f0-9]{20,}\S*"
    r"|<!--.*?-->"
    r"|\b(?:essential_context|select_context|render_answer|search_library|get_lesson_full|get_section|get_table_of_contents|"
    r"get_document_metadata|inspect_source_image|verify_calculation|verify_equation|"
    r"verify_dimensions|run_scientific_code|propose_note|write_learning_note|"
    r"save_practice_test|save_teaching_material|symbolic_math|convert_units|plot_function|"
    r"plot_data|plot_from_result|draw_diagram|list_lesson_parts|get_lesson_part|"
    r"get_exam_with_solution|get_exercise_collection|search_within_node|"
    r"list_my_notes|delete_learning_note|list_private_uploads|read_private_page)\b"
    r"|`calculate`|\bcalculate\s*\("
    r"|(?:tool|أداة|الأداة|استخدمت)\s+calculate\b",
    re.I | re.S,
)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)|<img\b[^>]*>|data:image/\S+", re.I)


def text(value):
    return IMAGE.sub("", INTERNAL.sub("", value or "")).strip()


def clean(value):
    if isinstance(value, str):
        return text(value)
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {
            k: clean(v)
            for k, v in value.items()
            if k
            not in (
                "tool",
                "inputs",
                "source_ids",
                "file",
                "content_file",
                "assets",
                "source",
            )
        }
    return value


def public_answer(payload):
    data = copy.deepcopy(payload)
    data["sources"] = []
    blocks = []
    for block in data.get("blocks", []):
        kind = block.get("type")
        if kind in ("image", "verification"):
            continue
        if kind == "equation":
            block["result_ids"] = []
        if kind == "graph":
            output = (block.get("result") or {}).get("output", {})
            # Calculated chart/diagram data is not a source scan or an execution trace.
            block["result_id"] = ""
            block["result"] = {
                "output": {
                    k: output[k] for k in ("chart", "diagram", "origin") if k in output
                }
            }
        for key in ("text", "latex", "caption"):
            if key in block:
                block[key] = text(block[key])
        if kind == "table":
            block["headers"] = [text(v) for v in block.get("headers", [])]
            block["rows"] = [[text(v) for v in row] for row in block.get("rows", [])]
        blocks.append(block)
    data["blocks"] = blocks
    data["warnings"] = [
        "توجد نتيجة غير محسومة؛ راجع المعطيات والافتراضات قبل الاعتماد على الحل."
        if any(word in w for word in ("لم ينجح", "لم يُحسم", "لم ينجح أو"))
        else "راجع المعطيات والافتراضات؛ لا يعدّ هذا تصديقًا على كل الشرح."
        if any(word in w for word in ("فحص", "التحقق", "تحقق"))
        else "هذا شرح تعليمي، وليس حلًا رسميًا معتمدًا."
        if "مصادر منشورة" in w
        else text(w)
        for w in data.get("warnings", [])
    ]
    data["warnings"] = list(dict.fromkeys(data["warnings"]))
    return clean(data)


def public_message(row):
    row = dict(row)
    if row.get("role") != "assistant":
        row["blocks"] = (
            json.loads(row["blocks"])
            if isinstance(row.get("blocks"), str)
            else row.get("blocks", [])
        )
        row["sources"] = []
        return row
    payload = public_answer(
        {
            "blocks": json.loads(row["blocks"])
            if isinstance(row.get("blocks"), str)
            else row.get("blocks", []),
            "sources": [],
        }
    )
    return row | payload | {"content": text(row.get("content"))}


def public_event(kind, payload):
    if kind == "answer":
        return public_answer(payload)
    if kind == "queued":
        return {"label": "جارٍ إعداد الإجابة"}
    if kind == "error":
        return {
            "code": "REQUEST_CANCELLED"
            if payload.get("code") == "CANCELLED"
            else "RESPONSE_UNAVAILABLE",
            "label": "أُوقف الطلب."
            if payload.get("code") == "CANCELLED"
            else "تعذر إكمال الإجابة؛ يمكنك إعادة المحاولة.",
        }
    # Never forward tool traces, step counters, intermediate model text or internal errors.
    return None


class SourceTextGuard:
    """Best-effort exact-copy guard, not a semantic confidentiality proof.

    Ignore punctuation/case/spacing. Block a run of 40 source words even if split
    across answer blocks. Short definitions/formulas are allowed for teaching.
    No raw source text or matching window is logged or returned in errors.
    """

    window = 40

    def __init__(self):
        self.windows = set()

    def signatures(self, value):
        words = re.findall(r"[^\W_]+", value.casefold(), re.UNICODE)
        for i in range(len(words) - self.window + 1):
            yield hashlib.sha256(
                "\x1f".join(words[i : i + self.window]).encode()
            ).digest()

    def remember(self, value):
        self.windows.update(self.signatures(value))

    def copied(self, value):
        return any(s in self.windows for s in self.signatures(value))
