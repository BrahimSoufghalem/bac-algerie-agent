"""Deterministic public work summaries; never model reasoning or raw tool traces."""

import json
from collections import defaultdict

LABELS = {
    "select_context": ("review", "مراجعة المعلومات"),
    "essential_context": ("review", "مراجعة المعلومات"),
    "search_library": ("review", "مراجعة المعلومات"),
    "get_document_metadata": ("review", "مراجعة المعلومات"),
    "get_table_of_contents": ("review", "مراجعة المعلومات"),
    "get_lesson_full": ("review", "مراجعة المعلومات"),
    "get_section": ("review", "مراجعة المعلومات"),
    "get_lesson_part": ("review", "مراجعة المعلومات"),
    "list_lesson_parts": ("review", "مراجعة المعلومات"),
    "search_within_node": ("review", "مراجعة المعلومات"),
    "get_exam_with_solution": ("review", "مراجعة المعلومات"),
    "get_exercise_collection": ("review", "مراجعة المعلومات"),
    "inspect_source_image": ("review", "فهم المعطيات"),
    "list_private_uploads": ("review", "مراجعة المعطيات المرفقة"),
    "read_private_page": ("review", "فهم المعطيات المرفقة"),
    "run_python": ("math", "حساب القيم ومراجعتها"),
    "calculate": ("math", "حساب القيم"),
    "symbolic_math": ("math", "معالجة العلاقات الرياضية"),
    "convert_units": ("math", "مراجعة الوحدات"),
    "run_scientific_code": ("math", "حساب القيم"),
    "verify_calculation": ("check", "مراجعة النتيجة المحددة"),
    "verify_equation": ("check", "مراجعة العلاقة الرياضية"),
    "verify_dimensions": ("check", "مراجعة الأبعاد"),
    "plot_function": ("diagram", "إعداد رسم توضيحي"),
    "plot_data": ("diagram", "إعداد رسم توضيحي"),
    "plot_from_result": ("diagram", "إعداد رسم توضيحي"),
    "draw_diagram": ("diagram", "إعداد رسم توضيحي"),
    "save_teaching_material": ("organize", "تنظيم المسودة التعليمية"),
}
PUBLIC_EVENTS = {
    "queued",
    "model_start",
    "finalizing",
    "tool_start",
    "tool_end",
    "answer",
    "error",
    "source_reloaded",
    "answer_rejected",
}
EVENT_SQL = "('queued','model_start','finalizing','tool_start','tool_end','answer','error','source_reloaded','answer_rejected')"
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}


class Activity:
    def __init__(self, run_id):
        self.run_id = run_id
        self.status = "queued"
        self.items = []
        self.pending = defaultdict(list)
        self.phase = None
        self.models = 0

    def add_item(self, id, kind, label, state="running"):
        item = {"id": str(id), "kind": kind, "label": label, "state": state}
        self.items.append(item)
        return item

    def settle_phase(self):
        if self.phase and self.phase["state"] == "running":
            self.phase["state"] = "done"

    def feed(self, row):
        kind, id = row["type"], row["id"]
        if kind not in PUBLIC_EVENTS:
            return
        try:
            p = json.loads(row["payload"])
        except (ValueError, TypeError):
            p = {}
        if not isinstance(p, dict):
            p = {}
        if kind == "queued":
            self.phase = self.add_item(id, "prepare", "انتظار البدء")
        elif kind == "model_start":
            self.settle_phase()
            self.models += 1
            self.status = "running"
            self.phase = self.add_item(
                id, "prepare", "فهم السؤال" if self.models == 1 else "إعداد الإجابة"
            )
        elif kind == "finalizing":
            self.settle_phase()
            self.phase = self.add_item(id, "prepare", "صياغة الرد")
        elif kind == "source_reloaded":
            self.add_item(id, "review", "مراجعة المعلومات السابقة", "done")
        elif kind == "answer_rejected":
            if self.phase:
                self.phase["state"] = "unavailable"
            self.add_item(id, "check", "مراجعة جاهزية الرد", "unavailable")
        elif kind == "tool_start":
            self.settle_phase()
            name = p.get("name", "") if isinstance(p.get("name", ""), str) else ""
            category, label = LABELS.get(name, ("organize", "متابعة إعداد الإجابة"))
            self.pending[name].append(self.add_item(id, category, label))
            self.status = "running"
        elif kind == "tool_end":
            name = p.get("name", "") if isinstance(p.get("name", ""), str) else ""
            waiting = self.pending[name]
            if waiting:
                waiting.pop(0)["state"] = (
                    "done" if p.get("success") is True else "unavailable"
                )
        elif kind == "answer":
            self.settle_phase()
            self.status = "completed"
            self.add_item(id, "complete", "اكتمال الرد", "done")
        elif kind == "error":
            self.status = "cancelled" if p.get("code") == "CANCELLED" else "unavailable"
            self.add_item(
                id,
                "complete",
                "أُوقف الطلب" if self.status == "cancelled" else "تعذّر إكمال الرد",
                "unavailable",
            )
            for item in self.items:
                if item["state"] == "running":
                    item["state"] = "stopped"

    def snapshot(self, terminal=None):
        items = [dict(item) for item in self.items]
        status = self.status
        if terminal in TERMINAL:
            status = (
                "completed"
                if terminal == "COMPLETED"
                else "cancelled"
                if terminal == "CANCELLED"
                else "unavailable"
            )
            # Do not falsely mark an invocation complete if no end event was recorded.
            for item in items:
                if item["state"] == "running":
                    item["state"] = "stopped"
        return {"run_id": self.run_id, "status": status, "items": items}


def run_activity(db, run):
    projection = Activity(run["id"])
    for row in db.rows(
        f"SELECT id,type,payload FROM run_events WHERE run_id=? AND type IN {EVENT_SQL} ORDER BY id",
        (run["id"],),
    ):
        projection.feed(row)
    return projection.snapshot(run["status"])


def attach_activity(db, chat, user_id, messages):
    """Attach by actual answer-event message ID, never by current/latest run alone."""
    by_id = {m.get("id"): m for m in messages}
    runs = db.rows(
        "SELECT id,status,message_id FROM agent_runs WHERE conversation_id=? AND user_id=? ORDER BY created_at",
        (chat, user_id),
    )
    rows = db.rows(
        f"SELECT e.id,e.run_id,e.type,e.payload FROM run_events e JOIN agent_runs r ON r.id=e.run_id WHERE r.conversation_id=? AND r.user_id=? AND e.type IN {EVENT_SQL} ORDER BY e.id",
        (chat, user_id),
    )
    events = defaultdict(list)
    for row in rows:
        events[row["run_id"]].append(row)
    latest = {run["message_id"]: run["id"] for run in runs}
    for run in runs:
        projection = Activity(run["id"])
        answer_id = None
        for row in events[run["id"]]:
            projection.feed(row)
            if row["type"] == "answer":
                try:
                    answer_id = json.loads(row["payload"]).get("message_id")
                except (ValueError, TypeError, AttributeError):
                    pass
        if answer_id in by_id and by_id[answer_id]["role"] == "assistant":
            by_id[answer_id]["activity"] = projection.snapshot(run["status"])
        elif run["message_id"] in by_id:
            question = by_id[run["message_id"]]
            summary = projection.snapshot(run["status"])
            if run["id"] != latest[run["message_id"]]:
                question.setdefault("previous_activities", []).append(summary)
            elif run["status"] != "COMPLETED":
                question["unanswered_activity"] = summary
    return messages
