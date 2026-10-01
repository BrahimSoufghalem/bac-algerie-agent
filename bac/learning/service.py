"""User-owned preferences, explicitly consented memory and private teaching drafts."""

import json, time
from fastapi import HTTPException
from bac.core.db import uid, js
from bac.core.auth import owned_chat
from bac.learning.contracts import Preferences, Overrides, Note, NoteDecision, Material


class Learning:
    def __init__(self, s):
        self.s, self.db = s, s.db

    def cancel(self, user, chat=None):
        sql = "UPDATE agent_runs SET cancel_requested=1 WHERE user_id=? AND status IN ('QUEUED','RUNNING')"
        self.db.execute(
            sql + (" AND conversation_id=?" if chat else ""),
            (user, chat) if chat else (user,),
        )

    def preferences(self, user):
        return Preferences.model_validate_json(
            self.db.one("SELECT preferences FROM users WHERE id=?", (user["id"],))[
                "preferences"
            ]
        ).model_dump()

    def set_preferences(self, user, values):
        p = Preferences.model_validate(values)
        with self.db.tx() as c:
            c.execute(
                "UPDATE users SET preferences=? WHERE id=?",
                (p.model_dump_json(), user["id"]),
            )
            c.execute(
                "UPDATE agent_runs SET cancel_requested=1 WHERE user_id=? AND status IN ('QUEUED','RUNNING')",
                (user["id"],),
            )
        return p.model_dump()

    def overrides(self, user, chat, values):
        owned_chat(self.db, chat, user)
        p = Overrides.model_validate(values)
        with self.db.tx() as c:
            c.execute(
                "UPDATE conversations SET overrides=?,updated_at=? WHERE id=?",
                (js(p.model_dump(exclude_none=True)), time.time(), chat),
            )
            c.execute(
                "UPDATE agent_runs SET cancel_requested=1 WHERE conversation_id=? AND status IN ('QUEUED','RUNNING')",
                (chat,),
            )
        return p.model_dump(exclude_none=True)

    def snapshot(self, c, user, chat):
        u = dict(c.execute("SELECT * FROM users WHERE id=?", (user,)).fetchone())
        over = json.loads(
            c.execute(
                "SELECT overrides FROM conversations WHERE id=?", (chat,)
            ).fetchone()[0]
        )
        pref = Preferences.model_validate(
            {
                **Preferences.model_validate_json(u["preferences"]).model_dump(),
                **Overrides.model_validate(over).model_dump(exclude_none=True),
            }
        ).model_dump()
        notes = []
        if pref["include_approved_notes"]:
            notes = [
                dict(r)
                for r in c.execute(
                    "SELECT id,category,content,created_at FROM learning_notes WHERE user_id=? AND status='approved' ORDER BY updated_at DESC LIMIT 6",
                    (user,),
                )
            ]
        return pref, notes

    def notes(self, user):
        return self.db.rows(
            "SELECT * FROM learning_notes WHERE user_id=? ORDER BY updated_at DESC LIMIT 100",
            (user["id"],),
        )

    def propose(self, user, run, values):
        p = Note.model_validate(values)
        with self.db.tx() as c:
            r = c.execute(
                "SELECT * FROM agent_runs WHERE id=? AND user_id=? AND status='RUNNING' AND cancel_requested=0",
                (run, user["id"]),
            ).fetchone()
            if not r:
                raise ValueError("Active own run required")
            if (
                c.execute(
                    "SELECT count(*) FROM learning_notes WHERE user_id=?", (user["id"],)
                ).fetchone()[0]
                >= 100
            ):
                raise ValueError("Note limit reached")
            id = uid("note")
            now = time.time()
            c.execute(
                "INSERT INTO learning_notes VALUES(?,?,?,?,?,?,?,?)",
                (
                    id,
                    user["id"],
                    p.category,
                    p.content,
                    "pending",
                    r["message_id"],
                    now,
                    now,
                ),
            )
        return {
            "id": id,
            "status": "pending",
            "instruction": "Suggestion only. User must edit/review and explicitly consent; do not treat as memory yet.",
        }

    def save_note(self, user, values, id=None):
        p = NoteDecision.model_validate(values)
        if not p.consent:
            raise HTTPException(
                422,
                "Explicit consent is required to store an approved educational note",
            )
        with self.db.tx() as c:
            if id:
                row = c.execute(
                    "SELECT * FROM learning_notes WHERE id=? AND user_id=?",
                    (id, user["id"]),
                ).fetchone()
                if not row:
                    raise HTTPException(404, "Note not found")
                if row["status"] == "pending" and (
                    not row["message_id"]
                    or not c.execute(
                        "SELECT 1 FROM messages WHERE id=? AND active=1",
                        (row["message_id"],),
                    ).fetchone()
                ):
                    raise HTTPException(
                        409,
                        "Suggestion source was edited/deleted; create a new manual note if still valid",
                    )
                c.execute(
                    "UPDATE learning_notes SET category=?,content=?,status='approved',updated_at=? WHERE id=?",
                    (p.category, p.content, time.time(), id),
                )
            else:
                if (
                    c.execute(
                        "SELECT count(*) FROM learning_notes WHERE user_id=?",
                        (user["id"],),
                    ).fetchone()[0]
                    >= 100
                ):
                    raise HTTPException(409, "Note limit reached")
                id = uid("note")
                now = time.time()
                c.execute(
                    "INSERT INTO learning_notes VALUES(?,?,?,?,?,?,?,?)",
                    (id, user["id"], p.category, p.content, "approved", None, now, now),
                )
            c.execute(
                "UPDATE agent_runs SET cancel_requested=1 WHERE user_id=? AND status IN ('QUEUED','RUNNING')",
                (user["id"],),
            )
            self.scrub_note_snapshots(c, user["id"], id)
        return {"id": id, "status": "approved"}

    def scrub_note_snapshots(self, c, user, note):
        # Consent withdrawal removes hidden run-context copies, not just the visible note row.
        for r in c.execute(
            "SELECT x.run_id,x.notes FROM run_contexts x JOIN agent_runs a ON a.id=x.run_id WHERE a.user_id=?",
            (user,),
        ).fetchall():
            notes = [n for n in json.loads(r["notes"]) if n["id"] != note]
            c.execute(
                "UPDATE run_contexts SET notes=? WHERE run_id=?",
                (js(notes), r["run_id"]),
            )

    def delete_note(self, user, id):
        with self.db.tx() as c:
            if not c.execute(
                "SELECT 1 FROM learning_notes WHERE id=? AND user_id=?",
                (id, user["id"]),
            ).fetchone():
                raise HTTPException(404, "Note not found")
            c.execute("DELETE FROM learning_notes WHERE id=?", (id,))
            self.scrub_note_snapshots(c, user["id"], id)
            c.execute(
                "UPDATE agent_runs SET cancel_requested=1 WHERE user_id=? AND status IN ('QUEUED','RUNNING')",
                (user["id"],),
            )

    def material(self, tools, values):
        p = Material.model_validate(values)
        user = self.db.one(
            "SELECT role,active FROM users WHERE id=?", (tools.user["id"],)
        )
        if (
            not user
            or not user["active"]
            or (user["role"] not in ("teacher", "owner") and p.kind != "self_practice")
        ):
            raise ValueError("Teacher permission required for this material type")
        answer, sources = tools.answer(p.answer.model_dump())
        data = p.model_dump(exclude={"answer"}) | {
            "blocks": [b.model_dump() for b in answer.blocks],
            "sources": sources,
            "warnings": answer.warnings,
            "generated": True,
            "official": False,
            "review_status": "draft",
        }
        if len(js(data)) > 50000:
            raise ValueError("Material exceeds budget")
        with self.db.tx() as c:
            if not c.execute(
                "SELECT 1 FROM agent_runs WHERE id=? AND user_id=? AND status='RUNNING' AND cancel_requested=0",
                (tools.run_id, tools.user["id"]),
            ).fetchone():
                raise ValueError("Active own run required")
            if (
                c.execute(
                    "SELECT count(*) FROM teaching_materials WHERE user_id=?",
                    (tools.user["id"],),
                ).fetchone()[0]
                >= 100
            ):
                raise ValueError("Material limit reached")
            id = uid("material")
            now = time.time()
            c.execute(
                "INSERT INTO teaching_materials VALUES(?,?,?,?,?,?,?,?)",
                (
                    id,
                    tools.user["id"],
                    tools.run_id,
                    p.kind,
                    p.title,
                    js(data),
                    now,
                    now,
                ),
            )
        return {
            "id": id,
            "kind": p.kind,
            "title": p.title,
            "generated": True,
            "official": False,
            "review_status": "draft",
        }

    def materials(self, user, id=None):
        rows = self.db.rows(
            "SELECT * FROM teaching_materials WHERE user_id=?"
            + (" AND id=?" if id else " ORDER BY updated_at DESC LIMIT 100"),
            (user["id"], id) if id else (user["id"],),
        )
        if id and not rows:
            raise HTTPException(404, "Material not found")
        for r in rows:
            r["payload"] = json.loads(r["payload"])
        return rows[0] if id else rows

    def export(self, user):
        data = {
            "format": "masar-personal-export-v1",
            "user": {k: user[k] for k in ("id", "email", "name", "role")},
            "preferences": self.preferences(user),
            "notes": self.notes(user),
            "materials": self.materials(user),
        }
        chats = self.db.rows(
            "SELECT * FROM conversations WHERE user_id=?", (user["id"],)
        )
        if len(chats) > 500:
            raise HTTPException(
                413, "Export too large; export/delete individual conversations first"
            )
        size = self.db.one(
            "SELECT sum(length(content)+length(blocks)+length(sources)) n FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE user_id=?)",
            (user["id"],),
        )["n"]
        if (size or 0) > 2_000_000:
            raise HTTPException(
                413, "Export too large; export individual conversations first"
            )
        for chat in chats:
            chat["messages"] = self.db.rows(
                "SELECT role,content,blocks,sources,active,created_at FROM messages WHERE conversation_id=? ORDER BY created_at",
                (chat["id"],),
            )
        data["conversations"] = chats
        data["uploads"] = self.db.rows(
            "SELECT id,conversation_id,name,kind,pages,expires_at FROM private_uploads WHERE user_id=? AND expires_at>?",
            (user["id"], time.time()),
        )
        if len(js(data).encode("utf-8")) > 10_000_000:
            raise HTTPException(
                413, "Export exceeds 10 MB; export individual chats first"
            )
        return data
