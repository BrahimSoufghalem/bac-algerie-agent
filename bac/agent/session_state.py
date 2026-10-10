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
    entries, proofs = entries[-MAX_SUMMARY_ENTRIES:], proofs[-MAX_SUMMARY_ENTRIES:]
    summary = {
        "kind": "partial_extractive_history",
        "not_read_evidence": True,
        "not_pending_tasks": True,
        "entries": entries,
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
