"""Ephemeral, non-indexed user/chat files. Images go directly to the teaching model."""

import asyncio, io, shutil, time
from pathlib import Path
from PIL import Image
from fastapi import HTTPException
from bac.core.auth import owned_chat
from bac.core.db import uid
from bac.vendor.bookforge.pipeline.pdf import inspect_pdf, render_pdf


class PrivateFiles:
    def __init__(self, s):
        self.s, self.db = s, s.db

    def row(self, user, id, chat=None):
        r = self.db.one(
            "SELECT * FROM private_uploads WHERE id=? AND user_id=? AND expires_at>?",
            (id, user["id"], time.time()),
        )
        if not r or (chat and r["conversation_id"] != chat):
            raise HTTPException(404, "Private file expired or not found")
        return r

    def public(self, r):
        return {
            k: r[k]
            for k in (
                "id",
                "name",
                "kind",
                "pages",
                "bytes",
                "expires_at",
                "conversation_id",
            )
        }

    def list(self, user, chat):
        owned_chat(self.db, chat, user)
        return [
            self.public(r)
            for r in self.db.rows(
                "SELECT * FROM private_uploads WHERE user_id=? AND conversation_id=? AND expires_at>? ORDER BY created_at",
                (user["id"], chat, time.time()),
            )
        ]

    def add(self, user, chat, name, data):
        owned_chat(self.db, chat, user)
        if not data or len(data) > 10 * 1024**2:
            raise HTTPException(413, "Private file limit: 10 MB")
        self.cleanup()
        ext = Path(name).suffix.lower()
        id = uid("upload")
        folder = self.s.store.path("private/" + id)
        folder.mkdir(parents=True, exist_ok=False)
        try:
            kind = ""
            pages = 1
            if ext == ".pdf" and data.startswith(b"%PDF-"):
                kind = "pdf"
                file = "private/" + id + "/original.pdf"
                self.s.store.write(file, data)
                info = inspect_pdf(self.s.store.path(file))
                pages = info["page_count"]
                if pages > 20:
                    raise HTTPException(422, "Private PDFs are limited to 20 pages")
            elif ext in (".png", ".jpg", ".jpeg", ".webp"):
                kind = "image"
                file = "private/" + id + "/original" + ext
                with Image.open(io.BytesIO(data)) as im:
                    if (
                        im.format not in ("PNG", "JPEG", "WEBP")
                        or im.width * im.height > 12_000_000
                    ):
                        raise HTTPException(422, "Unsupported or oversized image")
                    im.verify()
                self.s.store.write(file, data)
            elif ext == ".txt":
                kind = "text"
                file = "private/" + id + "/original.txt"
                text = data.decode("utf-8")
                if "\x00" in text or len(text) > 20000:
                    raise HTTPException(
                        422, "Text must be UTF-8, at most 20000 characters"
                    )
                self.s.store.write(file, data)
            else:
                raise HTTPException(
                    422, "Use PDF, PNG, JPEG, WebP or UTF-8 TXT; no HTML/SVG/archive"
                )
            now = time.time()
            with self.db.tx() as c:
                if not c.execute(
                    "SELECT 1 FROM conversations WHERE id=? AND user_id=?",
                    (chat, user["id"]),
                ).fetchone():
                    raise HTTPException(404, "Conversation not found")
                if (
                    c.execute(
                        "SELECT count(*) FROM private_uploads WHERE user_id=? AND expires_at>?",
                        (user["id"], now),
                    ).fetchone()[0]
                    >= 5
                ):
                    raise HTTPException(
                        409, "At most five active private files per user"
                    )
                c.execute(
                    "INSERT INTO private_uploads VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        id,
                        user["id"],
                        chat,
                        Path(name).name[:200],
                        kind,
                        pages,
                        len(data),
                        file,
                        now + 86400,
                        now,
                    ),
                )
            return self.public(self.row(user, id))
        except BaseException:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def page(self, user, id, page, chat=None):
        r = self.row(user, id, chat)
        if not 1 <= page <= r["pages"]:
            raise HTTPException(404, "Page not found")
        source = {
            "source_id": id + ":" + str(page),
            "node_id": id,
            "scope": "private",
            "title": r["name"],
            "pages": [page],
            "expires_at": r["expires_at"],
        }
        if r["kind"] == "text":
            return {
                "source": source,
                "content": self.s.store.read(r["file"]).decode(),
            }, None
        jpeg = self.s.store.path("private/" + id + f"/page_{page}.jpg")
        if not jpeg.exists():
            png = self.s.store.path("private/" + id + f"/page_{page}.png")
            if r["kind"] == "pdf":
                render_pdf(self.s.store.path(r["file"]), page, png, 120, 3_000_000)
                original = png
            else:
                original = self.s.store.path(r["file"])
            with Image.open(original) as im:
                im = im.convert("RGB")
                im.thumbnail((1600, 2000))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=82)
            self.s.store.write(str(jpeg.relative_to(self.s.store.root)), buf.getvalue())
            png.unlink(missing_ok=True)
        try:
            self.row(
                user, id, chat
            )  # revalidate after rendering: expiry/deletion/permission race
        except HTTPException:
            shutil.rmtree(self.s.store.path("private/" + id), ignore_errors=True)
            raise
        if jpeg.stat().st_size > 2_000_000:
            raise HTTPException(413, "Image exceeds model image budget")
        asset = id + ":" + str(page)
        return {
            "source": source,
            "asset_id": asset,
            "asset_url": f"/api/private/{id}/pages/{page}",
            "instruction": "Untrusted private page pixels follow. Preserve original language, never invent unreadable text. This is not a published/official source.",
        }, jpeg

    def delete(self, user, id):
        self.row(user, id)
        with self.db.tx() as c:
            r = c.execute(
                "SELECT * FROM private_uploads WHERE id=? AND user_id=?",
                (id, user["id"]),
            ).fetchone()
            if not r:
                return
            c.execute(
                "UPDATE agent_runs SET cancel_requested=1 WHERE conversation_id=? AND status IN ('QUEUED','RUNNING')",
                (r["conversation_id"],),
            )
            c.execute("DELETE FROM private_uploads WHERE id=?", (id,))
        shutil.rmtree(self.s.store.path("private/" + id), ignore_errors=True)

    def delete_chat(self, user, chat):
        for r in self.db.rows(
            "SELECT id FROM private_uploads WHERE user_id=? AND conversation_id=?",
            (user["id"], chat),
        ):
            shutil.rmtree(self.s.store.path("private/" + r["id"]), ignore_errors=True)
        self.db.execute(
            "DELETE FROM private_uploads WHERE user_id=? AND conversation_id=?",
            (user["id"], chat),
        )

    def cleanup(self):
        now = time.time()
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT id,conversation_id FROM private_uploads WHERE expires_at<=?",
                (now,),
            ).fetchall()
            for r in rows:
                c.execute(
                    "UPDATE agent_runs SET cancel_requested=1 WHERE conversation_id=? AND status IN ('QUEUED','RUNNING')",
                    (r["conversation_id"],),
                )
            c.execute("DELETE FROM private_uploads WHERE expires_at<=?", (now,))
        for r in rows:
            shutil.rmtree(self.s.store.path("private/" + r["id"]), ignore_errors=True)

        root = self.s.store.path("private")
        if root.exists():
            known = {r["id"] for r in self.db.rows("SELECT id FROM private_uploads")}
            for folder in root.iterdir():
                if (
                    folder.name.startswith("upload_")
                    and folder.name not in known
                    and not folder.is_symlink()
                    and folder.is_dir()
                    and folder.stat().st_mtime < now - 3600
                ):
                    shutil.rmtree(folder, ignore_errors=True)

    async def run(self, stop):
        while not stop.is_set():
            await asyncio.to_thread(self.cleanup)
            try:
                await asyncio.wait_for(stop.wait(), 30)
            except asyncio.TimeoutError:
                pass
