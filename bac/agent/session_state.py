"""Own-chat, traceable extractive dialogue state; no LLM or extra provider calls.

All summaries are regenerated from active messages: persisted text is never trusted
as policy/evidence and editing/retry/deletion cannot revive an inactive message.
"""

import hashlib
import json
import re
import time

from bac.core.db import js
from bac.core.presentation import public_message
from bac.agent.memory import history_text
from bac.agent.grounding import normalized

MAX_SUMMARY_CHARS = 6000
MAX_SUMMARY_ENTRIES = 12
TERMINAL = {"COMPLETED", "FAILED", "INTERRUPTED", "CANCELLED"}


def excerpt(text, size):
    """Explicitly partial quoted dialogue, not a semantic claim of completeness."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= size:
        return text
    return text[:size].rsplit(" ", 1)[0] + " …"


def public_answer_excerpt(row):
    safe = public_message(row)
    safe["blocks"] = js(safe["blocks"])
    return excerpt(history_text(safe), 180)


def message_digest(row):
    return hashlib.sha256(
        js({k: row.get(k) for k in ("id", "role", "content", "blocks")}).encode()
    ).hexdigest()


def session_summary(db, user_id, chat, exclude_id=None, persist=True):
    if not db.one(
        "SELECT 1 FROM conversations WHERE id=? AND user_id=?", (chat, user_id)
    ):
        return {}
    rows = db.rows(
        "SELECT id,role,content,blocks,created_at,rowid AS seq FROM messages "
        "WHERE conversation_id=? AND active=1 ORDER BY created_at DESC,rowid DESC LIMIT 60",
        (chat,),
    )
    rows.reverse()
    entries, proofs = [], []
    for index, question in enumerate(rows):
        if question["role"] != "user" or question["id"] == exclude_id:
            continue
        run = db.one(
            "SELECT id,status FROM agent_runs WHERE conversation_id=? AND user_id=? AND message_id=? "
            "ORDER BY created_at DESC,rowid DESC LIMIT 1",
            (chat, user_id, question["id"]),
        )
        if run and run["status"] not in TERMINAL:
            continue
        answer = None
        if run and run["status"] == "COMPLETED":
            event = db.one(
                "SELECT payload FROM run_events WHERE run_id=? AND type='answer' ORDER BY id DESC LIMIT 1",
                (run["id"],),
            )
            try:
                answer_id = (
                    json.loads(event["payload"]).get("message_id") if event else None
                )
            except (ValueError, TypeError):
                answer_id = None
            answer = next(
                (r for r in rows if r["id"] == answer_id and r["role"] == "assistant"),
                None,
            )
        elif not run:
            # Legacy published dialogue predating run provenance remains explicitly untracked.
            following = rows[index + 1 :]
            answer = (
                following[0]
                if following and following[0]["role"] == "assistant"
                else None
            )
        entry = {
            "question_message_id": question["id"],
            "answer_message_id": answer["id"] if answer else None,
            "run_id": run["id"] if run else None,
            "status": run["status"] if run else "UNTRACKED",
            "question_excerpt": excerpt(question["content"], 220),
            "answer_excerpt": public_answer_excerpt(answer) if answer else "",
        }
        entries.append(entry)
        proofs.append(
            {
                "question_message_id": question["id"],
                "question_sha256": message_digest(question),
                "answer_message_id": answer["id"] if answer else None,
                "answer_sha256": message_digest(answer) if answer else None,
            }
        )
    total = len(entries)
    early = [
        i
        for i, e in enumerate(entries[:-8])
        if re.search(
            r"خطا|اخطاء|لم افهم|ما فهمتش|مفهمتش|اعتقد|اظن|mistake|confus|wrong|erreur",
            normalized(e["question_excerpt"]),
        )
    ][:4]
    indices = sorted(
        set(
            early
            + list(range(max(0, total - (MAX_SUMMARY_ENTRIES - len(early))), total))
        )
    )
    entries, proofs = [entries[i] for i in indices], [proofs[i] for i in indices]
    summary = {
        "kind": "partial_extractive_history",
        "not_read_evidence": True,
        "not_pending_tasks": True,
        "entries": entries,
        "complete": False,
        "retrieval_tool": "read_conversation_history",
        "observed_exchanges_in_window": total,
    }
    while len(js(summary)) > MAX_SUMMARY_CHARS and entries:
        entries.pop(0)
        proofs.pop(0)
    if persist:
        payload = js({"summary": summary, "message_provenance": proofs})
        # Bounded cache only; no uploaded bytes, library passages or tool/argument history.
        db.execute(
            "INSERT INTO conversation_summaries VALUES(?,?,?) ON CONFLICT(conversation_id) "
            "DO UPDATE SET payload=excluded.payload,updated_at=excluded.updated_at",
            (chat, payload, time.time()),
        )
    return summary


def read_history(tools, before_message_id=None, limit=24, student_only=True):
    db = tools.s.db
    if not db.one(
        "SELECT 1 FROM conversations WHERE id=? AND user_id=?",
        (tools.chat, tools.user["id"]),
    ):
        raise ValueError("History unavailable")
    cursor = None
    if before_message_id:
        row = db.one(
            "SELECT rowid AS seq FROM messages WHERE id=? AND conversation_id=? AND active=1",
            (before_message_id, tools.chat),
        )
        if not row:
            raise ValueError("History cursor unavailable")
        cursor = row["seq"]
    sql = "SELECT id,role,content,blocks,rowid AS seq FROM messages WHERE conversation_id=? AND active=1"
    params = [tools.chat]
    if student_only:
        sql += " AND role='user'"
    if cursor is not None:
        sql += " AND rowid<?"
        params.append(cursor)
    rows = db.rows(sql + " ORDER BY rowid DESC LIMIT ?", (*params, limit + 1))
    more = len(rows) > limit
    rows = rows[:limit]
    items = []
    for row in reversed(rows):
        safe = public_message(row)
        safe["blocks"] = js(safe["blocks"])
        content = history_text(safe)
        tools.history_evidence[row["id"]] = message_digest(row)
        items.append(
            {
                "message_id": row["id"],
                "role": row["role"],
                "content": content[:2400],
                "truncated": len(content) > 2400,
            }
        )
    tools.history_read = True
    # Paging must begin at the latest page and proceed without skipping to claim full coverage.
    if not before_message_id:
        tools.history_scan_mode = student_only
        tools.history_truncated = False
        tools.history_scan_next = rows[-1]["id"] if more else None
        tools.history_complete = not more and not any(i["truncated"] for i in items)
    elif before_message_id == getattr(
        tools, "history_scan_next", None
    ) and student_only == getattr(tools, "history_scan_mode", None):
        tools.history_scan_next = rows[-1]["id"] if more else None
        tools.history_complete = (
            not more
            and not any(i["truncated"] for i in items)
            and not getattr(tools, "history_truncated", False)
        )
    tools.history_truncated = getattr(tools, "history_truncated", False) or any(
        i["truncated"] for i in items
    )
    return {
        "items": items,
        "next_before_message_id": rows[-1]["id"] if more else None,
        "complete": tools.history_complete,
        "not_read_reference_evidence": True,
        "not_verified_mastery": True,
    }


def available_attachments(s, user, chat, run_id):
    """Revalidate enqueue inventory against ownership, chat, expiry and file presence."""
    manifest = s.db.one(
        "SELECT attachment_ids FROM run_input_manifests WHERE run_id=?", (run_id,)
    )
    if not manifest:
        return []  # Legacy runs cannot invent an attachment inventory.
    try:
        ids = json.loads(manifest["attachment_ids"])
    except (ValueError, TypeError):
        return []
    if not isinstance(ids, list):
        return []
    available = []
    for id_ in ids[:5]:
        if not isinstance(id_, str):
            continue
        row = s.db.one(
            "SELECT id,kind,pages,file FROM private_uploads WHERE id=? AND user_id=? "
            "AND conversation_id=? AND expires_at>?",
            (id_, user["id"], chat, time.time()),
        )
        if (
            row
            and row["kind"] in {"image", "pdf", "text"}
            and s.store.path(row["file"]).is_file()
        ):
            available.append(
                {
                    "id": row["id"],
                    "kind": row["kind"],
                    "pages": row["pages"],
                    "read": False,
                }
            )
    return available


# Only references to student-supplied input, NOT drawing requests or book scans.
VISUAL_REFERENCE = re.compile(
    r"(?:في|على|من|لهذه|هذه|هذي|تلك)\s+(?:ال)?(?:صورة|صوره|تصويرة)|"
    r"(?:صورة|صوره|تصويرة)\s+(?:المرفقة|المرفقه|التي\s+(?:أرسلت|ارسلت|رفعت))|"
    r"(?:attached|uploaded|this|that|the)\s+(?:image|photo|picture|screenshot)|"
    r"(?:image|photo|capture)\s+(?:jointe|ci[- ]jointe|envoyée|envoyee)|"
    r"(?:cette|dans la|sur la)\s+(?:image|photo|capture)",
    re.I,
)
BOOK_OR_GENERATE = re.compile(
    r"(?:ارسم|أنشئ|انشئ|ولد|draw|generate|create)\s+.{0,25}(?:صورة|image|picture)|(?:صورة|image|photo).{0,25}(?:كتاب|درس|textbook|book|manuel)",
    re.I,
)


FILE_REFERENCE = re.compile(
    r"(?:في|من|هذا|هدا|هذي|هذه)\s+(?:ال)?(?:ملف|المرفق)|"
    r"(?:ملف|مرفق)\s+(?:المرفق|الذي\s+(?:أرسلت|ارسلت|رفعت))|"
    r"(?:attached|uploaded|this|that)\s+(?:file|document|pdf)|"
    r"(?:fichier|document|pdf)\s+(?:joint|envoyé|envoye)|"
    r"(?:ce|dans le)\s+(?:fichier|document)",
    re.I,
)
EXPLICIT_UPLOAD = re.compile(
    r"المرفق|ارسلت|أرسلت|رفعت|attached|uploaded|joint|envoy", re.I
)


def missing_student_attachment(question, attachments):
    if BOOK_OR_GENERATE.search(question) and not EXPLICIT_UPLOAD.search(question):
        return False
    if VISUAL_REFERENCE.search(question):
        return not any(a["kind"] in {"image", "pdf"} for a in attachments)
    return bool(FILE_REFERENCE.search(question)) and not attachments
