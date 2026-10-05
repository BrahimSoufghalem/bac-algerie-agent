from typing import Literal
import asyncio, json, sqlite3, time
import httpx
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field
from bac.core.auth import create_user, owner, verify_password, owned_chat
from bac.agent.models import Strict
from bac.agent.compat import model_identity
from bac.agent.presets import auth_headers
from bac.agent.full_index import supported_router
from bac.learning.service import Learning
from bac.learning.private import PrivateFiles
from bac.learning.contracts import Preferences, Overrides, NoteDecision, AccountLimits
from bac.learning.usage import report
from bac.core.presentation import public_message
from bac.core.activity import attach_activity
from bac.vendor.bookforge.vision.provider import validate_base_url


class Confirm(Strict):
    confirm: bool = False


class DeleteAccount(Strict):
    password: str = Field(min_length=1, max_length=256, repr=False)
    confirm: bool = False


class AccountCreate(Strict):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=256, repr=False)
    role: Literal["student", "teacher"] = "teacher"


def router(s, current):
    r = APIRouter(prefix="/api")
    learn = Learning(s)
    files = PrivateFiles(s)

    @r.get("/preferences")
    def preferences(user=Depends(current)):
        return learn.preferences(user)

    @r.put("/preferences")
    def set_preferences(p: Preferences, user=Depends(current)):
        return learn.set_preferences(user, p.model_dump())

    @r.put("/conversations/{chat}/preferences")
    def overrides(chat: str, p: Overrides, user=Depends(current)):
        return learn.overrides(user, chat, p.model_dump(exclude_none=True))

    @r.get("/notes")
    def notes(user=Depends(current)):
        return {
            "items": [n for n in learn.notes(user) if n.get("origin") == "agent"],
            "read_only": True,
        }

    @r.post("/notes")
    def note(p: NoteDecision, user=Depends(current)):
        raise HTTPException(403, "Educational notes are managed by Masar")

    @r.put("/notes/{id}")
    def edit_note(id: str, p: NoteDecision, user=Depends(current)):
        raise HTTPException(403, "Educational notes are managed by Masar")

    @r.delete("/notes/{id}")
    def delete_note(id: str, user=Depends(current)):
        raise HTTPException(403, "Educational notes are managed by Masar")

    @r.get("/materials")
    def materials(user=Depends(current)):
        return {"items": learn.materials(user)}

    @r.get("/materials/{id}")
    def material(id: str, user=Depends(current)):
        return learn.materials(user, id)

    @r.delete("/materials/{id}")
    def delete_material(id: str, user=Depends(current)):
        learn.materials(user, id)
        s.db.execute(
            "DELETE FROM teaching_materials WHERE id=? AND user_id=?", (id, user["id"])
        )
        return {"ok": True}

    @r.get("/privacy/export")
    def export(user=Depends(current)):
        return JSONResponse(
            learn.export(user),
            headers={
                "Content-Disposition": 'attachment; filename="masar-personal-export.json"'
            },
        )

    @r.get("/conversations/{chat}/export")
    def export_chat(chat: str, user=Depends(current)):
        owned_chat(s.db, chat, user)
        rows = s.db.rows(
            "SELECT id,role,content,blocks,sources,created_at FROM messages WHERE conversation_id=? ORDER BY created_at",
            (chat,),
        )
        return JSONResponse(
            {
                "conversation": chat,
                "messages": attach_activity(
                    s.db, chat, user["id"], [public_message(r) for r in rows]
                ),
            },
            headers={"Content-Disposition": 'attachment; filename="masar-chat.json"'},
        )

    @r.delete("/privacy/account")
    def erase(p: DeleteAccount, user=Depends(current)):
        if not p.confirm or not verify_password(p.password, user["password_hash"]):
            raise HTTPException(403, "Password and explicit confirmation required")
        if (
            user["role"] == "owner"
            or s.db.one("SELECT 1 FROM documents WHERE owner_id=?", (user["id"],))
            or s.db.one("SELECT 1 FROM versions WHERE reviewer_id=?", (user["id"],))
            or s.db.one(
                "SELECT 1 FROM version_files WHERE verified_by=?", (user["id"],)
            )
        ):
            raise HTTPException(
                409,
                "Owner accounts require administrative transfer; cannot erase content ownership",
            )
        if s.db.one(
            "SELECT 1 FROM agent_runs WHERE user_id=? AND status IN ('QUEUED','RUNNING')",
            (user["id"],),
        ):
            learn.cancel(user["id"])
            raise HTTPException(
                409, "Runs cancelled; retry account deletion after workers stop them"
            )
        for chat in s.db.rows(
            "SELECT id FROM conversations WHERE user_id=?", (user["id"],)
        ):
            files.delete_chat(user, chat["id"])
        with s.db.tx() as c:
            c.execute("DELETE FROM conversations WHERE user_id=?", (user["id"],))
            c.execute("DELETE FROM model_usage WHERE user_id=?", (user["id"],))
            c.execute("DELETE FROM users WHERE id=?", (user["id"],))
        res = JSONResponse({"ok": True})
        res.delete_cookie("bac_session")
        return res

    @r.get("/conversations/{chat}/uploads")
    def uploads(chat: str, user=Depends(current)):
        return {"items": files.list(user, chat)}

    @r.post("/conversations/{chat}/upload")
    async def upload(chat: str, file: UploadFile = File(...), user=Depends(current)):
        owned_chat(s.db, chat, user)
        if not s.db.rate("private-upload:" + user["id"], 6, 60):
            raise HTTPException(429, "Upload rate limit")
        try:
            data = await file.read(10 * 1024**2 + 1)
            return await asyncio.to_thread(
                files.add, user, chat, file.filename or "", data
            )
        except (ValueError, __import__("subprocess").SubprocessError, OSError):
            raise HTTPException(
                422, "Invalid private file or rendering resource limit"
            ) from None
        finally:
            await file.close()

    @r.delete("/private/{id}")
    def delete_upload(id: str, user=Depends(current)):
        files.delete(user, id)
        return {"ok": True}

    @r.get("/private/{id}/original")
    def original(id: str, user=Depends(current)):
        row = files.row(user, id)
        return FileResponse(
            s.store.path(row["file"]),
            media_type="application/octet-stream",
            filename=row["name"],
        )

    @r.get("/private/{id}/pages/{page}")
    def page(id: str, page: int, user=Depends(current)):
        p, path = files.page(user, id, page)
        return FileResponse(path, media_type="image/jpeg") if path else JSONResponse(p)

    @r.get("/usage")
    def personal_usage(days: int = 30, user=Depends(current)):
        return report(s, user, days)

    fields = "id,email,name,role,active,daily_limit,daily_tokens,messages_per_minute,max_active_runs,budget_alert,created_at"

    @r.get("/owner/accounts")
    def accounts(q: str = "", offset: int = 0, user=Depends(current)):
        owner(user)
        if len(q) > 100 or not 0 <= offset <= 100000:
            raise HTTPException(422, "Invalid account query")
        return {
            "items": s.db.rows(
                "SELECT "
                + fields
                + " FROM users WHERE email LIKE ? OR name LIKE ? ORDER BY created_at DESC LIMIT 50 OFFSET ?",
                ("%" + q + "%", "%" + q + "%", offset),
            ),
            "offset": offset,
        }

    @r.post("/owner/accounts")
    def create(p: AccountCreate, user=Depends(current)):
        owner(user)
        if "@" not in p.email:
            raise HTTPException(422, "Email required")
        try:
            id = create_user(s.db, p.email, p.password, p.name, p.role)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Account already exists") from None
        s.db.audit(user["id"], "account.create", id, {"role": p.role})
        return {"id": id}

    @r.patch("/owner/accounts/{id}")
    def edit_account(id: str, p: AccountLimits, user=Depends(current)):
        owner(user)
        values = p.model_dump(exclude_unset=True)
        if any(
            values.get(k, "absent") is None
            for k in ("role", "active", "messages_per_minute", "max_active_runs")
        ):
            raise HTTPException(422, "Required limits cannot be null")
        with s.db.tx() as c:
            old = c.execute("SELECT * FROM users WHERE id=?", (id,)).fetchone()
            if not old:
                raise HTTPException(404, "Account not found")
            if (
                old["role"] == "owner"
                and old["active"]
                and (
                    values.get("role", "owner") != "owner"
                    or values.get("active", True) is False
                )
            ):
                if (
                    c.execute(
                        "SELECT count(*) FROM users WHERE role='owner' AND active=1"
                    ).fetchone()[0]
                    <= 1
                ):
                    raise HTTPException(409, "Cannot remove the last active owner")
            if values:
                c.execute(
                    "UPDATE users SET "
                    + ",".join(k + "=?" for k in values)
                    + " WHERE id=?",
                    (*values.values(), id),
                )
                c.execute(
                    "UPDATE agent_runs SET cancel_requested=1 WHERE user_id=? AND status IN ('QUEUED','RUNNING')",
                    (id,),
                )
                if "role" in values or "active" in values:
                    c.execute("DELETE FROM sessions WHERE user_id=?", (id,))
                c.execute(
                    "INSERT INTO audit(actor_id,action,target,details,created_at) VALUES(?,?,?,?,?)",
                    (
                        user["id"],
                        "account.update",
                        id,
                        json.dumps({"old": {k: old[k] for k in values}, "new": values}),
                        time.time(),
                    ),
                )
        return {"ok": True}

    @r.post("/owner/models/{slot}/test")
    async def test_model(slot: str, p: Confirm, user=Depends(current)):
        owner(user)
        if not p.confirm:
            raise HTTPException(422, "Explicit connection-test confirmation required")
        if not s.db.rate("model-test:" + user["id"], 3, 60):
            raise HTTPException(429, "Connection test limit")
        row = s.db.one(
            "SELECT m.* FROM active_models a JOIN model_configs m ON m.id=a.config_id WHERE a.slot=?",
            (slot,),
        )
        if slot == "selector":
            row = s.db.one(
                "SELECT c.* FROM active_selector a JOIN context_selectors c ON c.id=a.config_id WHERE a.singleton=1"
            )
        if not row:
            raise HTTPException(404, "Save model configuration first")
        cfg = json.loads(row["config"])
        if slot == "selector" and not supported_router(cfg):
            raise HTTPException(409, "Reconfigure the retired reference router with an LLM provider")
        base = cfg["base_url"].rstrip("/")
        try:
            if s.connection_transport is None:
                await validate_base_url(base, s.settings.allow_private_model_urls)
            if base.endswith("/chat/completions"):
                base = base[:-17]
            async with httpx.AsyncClient(
                timeout=10,
                transport=s.connection_transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "GET",
                    base + "/models",
                    headers=auth_headers(cfg, s.vault.decrypt(row["encrypted_key"])),
                ) as response:
                    code = response.status_code
                    if code != 200:
                        raise HTTPException(
                            502, "Provider connection response: HTTP_" + str(code)
                        )
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > 256000:
                            raise HTTPException(
                                502, "Provider model list exceeds safe limit"
                            )
                    payload = json.loads(data)
                    catalog = (
                        payload.get("models", [])
                        if isinstance(payload, dict) and cfg.get("protocol") == "google"
                        else payload.get("data", [])
                        if isinstance(payload, dict)
                        else None
                    )
                    if not isinstance(payload, dict) or not isinstance(catalog, list):
                        raise ValueError("Invalid model list")
                    if cfg.get("protocol") == "google":
                        catalog = [
                            {
                                "id": x["name"].removeprefix("models/"),
                                "type": "language",
                            }
                            for x in catalog
                            if isinstance(x, dict) and isinstance(x.get("name"), str)
                        ]
                    found = any(
                        isinstance(x, dict)
                        and isinstance(x.get("id"), str)
                        and (
                            x["id"] == cfg["model"].removeprefix("models/")
                            if cfg.get("protocol") == "google"
                            else model_identity(base, x["id"])
                            == model_identity(base, cfg["model"])
                        )
                        for x in catalog
                    )
        except HTTPException:
            raise
        except (ValueError, httpx.HTTPError):
            raise HTTPException(
                502, "Provider connection failed; no secret/error body is returned"
            ) from None
        s.db.audit(
            user["id"],
            "model.connection_test",
            row["id"],
            {"slot": slot, "model_advertised": found},
        )
        return {
            "connected": True,
            "model_advertised": found,
            "generation_requests": 0,
            "models": [
                {"id": x["id"], "type": x.get("type", "language")}
                for x in catalog
                if isinstance(x, dict)
                and isinstance(x.get("id"), str)
                and __import__("re").fullmatch(r"[a-zA-Z0-9_./:-]{1,180}", x["id"])
            ][:100],
            "warning": "Reachability/authentication/model listing only; vision, tool calling and educational quality were not tested.",
        }

    return r
