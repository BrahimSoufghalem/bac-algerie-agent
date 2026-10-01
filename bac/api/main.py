from pathlib import Path
import asyncio, hashlib, json, os, tempfile, time
from fastapi import FastAPI, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field, ConfigDict
from bac.core.services import Services
from bac.core.auth import (
    create_user,
    verify_password,
    hash_password,
    new_session,
    user_from_request,
    public_user,
    owner,
    owned_chat,
)
from bac.core.db import uid, js
from bac.learning.contracts import Overrides
from bac.learning.private import PrivateFiles
from bac.learning.api import router as learning_router
from bac.learning.usage import report
from bac.agent.engine import AgentEngine
from bac.agent.models import ModelConfig
from bac.library.service import Library
from bac.library.contracts import (
    DocumentMetadata,
    SolutionMetadata,
    PageRange,
    SolutionVerification,
)
from bac.vendor.bookforge.vision.provider import validate_base_url

ROOT = Path(__file__).resolve().parents[2]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Credentials(Strict):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256, repr=False)


class Register(Credentials):
    name: str = Field(min_length=1, max_length=100)


class ChatCreate(Strict):
    title: str = Field(default="محادثة جديدة", min_length=1, max_length=150)
    overrides: Overrides = Field(default_factory=Overrides)


class ChatRename(Strict):
    title: str = Field(min_length=1, max_length=150)


class Send(Strict):
    text: str = Field(min_length=1, max_length=8000)
    edit_message_id: str | None = None


class ConfigRequest(Strict):
    config: ModelConfig
    api_key: str = Field(default="", max_length=4096, repr=False)


Metadata = DocumentMetadata


class Review(Strict):
    acknowledge_issues: bool = False
    notes: str = Field(default="", max_length=4000)


class CombinedSolution(Strict):
    metadata: SolutionMetadata
    page_range: PageRange


class StatusUpdate(Strict):
    status: str


def create_app(services=None):
    s = services or Services()
    app = FastAPI(
        title="Masar BAC Agent",
        version="0.4.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.services = s
    app.state.db = s.db
    library = Library(s)
    agent = AgentEngine(s)
    dummy = hash_password("Unusable-random-dummy-identity")
    app.state.library = library
    app.state.agent = agent

    @app.middleware("http")
    async def protect(request, call_next):
        path = request.url.path
        if path.startswith("/api/") and path not in (
            "/api/auth/login",
            "/api/auth/register",
        ):
            try:
                request.state.user = user_from_request(request)
            except HTTPException as e:
                return JSONResponse({"detail": e.detail}, e.status_code)
        if (
            path.startswith("/api/owner/")
            and getattr(request.state, "user", {}).get("role") != "owner"
        ):
            return JSONResponse({"detail": "Owner permission required"}, 403)
        if path.endswith("/upload"):
            try:
                length = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Invalid length"}, 400)
            cap = 11 * 1024**2 if path.startswith("/api/conversations/") else s.settings.max_upload_mb * 1024**2 + 1024**2
            if length > cap:
                return JSONResponse({"detail": "File too large"}, 413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        # KaTeX renders vetted numeric style attributes; scripts remain same-origin and never inline.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
        )
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse(
            {
                "detail": "Invalid request",
                "fields": [".".join(map(str, e["loc"])) for e in exc.errors()],
            },
            422,
        )

    def current(request: Request):
        return request.state.user

    app.include_router(learning_router(s, current))

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/auth/register")
    def register(p: Register, request: Request):
        address = request.client.host if request.client else "unknown"
        if not s.db.rate("register:" + address, 5, 3600):
            raise HTTPException(429, "Registration rate limit")
        if "@" not in p.email:
            raise HTTPException(422, "Valid email required")
        try:
            id = create_user(s.db, p.email, p.password, p.name)
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        except __import__("sqlite3").IntegrityError:
            raise HTTPException(
                409, "Registration not available for this address"
            ) from None
        token, csrf = new_session(s.db, id, s.settings)
        res = JSONResponse(
            {
                "user": public_user(s.db.one("SELECT * FROM users WHERE id=?", (id,))),
                "csrf": csrf,
            }
        )
        res.set_cookie(
            "bac_session",
            token,
            httponly=True,
            secure=s.settings.secure_cookies,
            samesite="strict",
            max_age=s.settings.session_hours * 3600,
        )
        return res

    @app.post("/api/auth/login")
    def login(p: Credentials, request: Request):
        address = request.client.host if request.client else "unknown"
        key = hashlib.sha256((address + ":" + p.email.casefold()).encode()).hexdigest()
        if not s.db.rate("login:" + key, 10, 300):
            raise HTTPException(429, "Too many sign-in attempts")
        row = s.db.one(
            "SELECT * FROM users WHERE email=?", (p.email.casefold().strip(),)
        )
        valid = verify_password(p.password, row["password_hash"] if row else dummy)
        if not row or not valid or not row["active"]:
            raise HTTPException(401, "Invalid credentials")
        token, csrf = new_session(s.db, row["id"], s.settings)
        res = JSONResponse({"user": public_user(row), "csrf": csrf})
        res.set_cookie(
            "bac_session",
            token,
            httponly=True,
            secure=s.settings.secure_cookies,
            samesite="strict",
            max_age=s.settings.session_hours * 3600,
        )
        return res

    @app.get("/api/auth/me")
    def me(user=Depends(current)):
        return {"user": public_user(user), "csrf": user["csrf"]}

    @app.post("/api/auth/logout")
    def logout(user=Depends(current)):
        s.db.execute("DELETE FROM sessions WHERE token_hash=?", (user["token_hash"],))
        res = JSONResponse({"ok": True})
        res.delete_cookie("bac_session")
        return res

    @app.get("/api/conversations")
    def conversations(q: str = "", user=Depends(current)):
        if len(q) > 200:
            raise HTTPException(422, "Query too long")
        return {
            "items": s.db.rows(
                "SELECT id,title,created_at,updated_at FROM conversations WHERE user_id=? AND title LIKE ? ORDER BY updated_at DESC LIMIT 100",
                (user["id"], "%" + q + "%"),
            )
        }

    @app.post("/api/conversations")
    def create(p: ChatCreate, user=Depends(current)):
        id = uid("chat")
        s.db.execute(
            "INSERT INTO conversations VALUES(?,?,?,?,?,?)",
            (id, user["id"], p.title, js(p.overrides.model_dump(exclude_none=True)), time.time(), time.time()),
        )
        return {"id": id, "title": p.title}

    @app.get("/api/conversations/{id}")
    def chat(id: str, user=Depends(current)):
        c = owned_chat(s.db, id, user)
        messages = s.db.rows(
            "SELECT * FROM messages WHERE conversation_id=? AND active=1 ORDER BY created_at",
            (id,),
        )
        for m in messages:
            m["blocks"] = json.loads(m["blocks"])
            m["sources"] = json.loads(m["sources"])
        return {
            **c,
            "messages": messages,
            "active_run": s.db.one(
                "SELECT id,status FROM agent_runs WHERE conversation_id=? AND status IN ('QUEUED','RUNNING')",
                (id,),
            ),
        }

    @app.patch("/api/conversations/{id}")
    def rename(id: str, p: ChatRename, user=Depends(current)):
        owned_chat(s.db, id, user)
        s.db.execute(
            "UPDATE conversations SET title=?,updated_at=? WHERE id=?",
            (p.title, time.time(), id),
        )
        return {"ok": True}

    @app.delete("/api/conversations/{id}")
    def delete(id: str, user=Depends(current)):
        owned_chat(s.db, id, user)
        if s.db.one(
            "SELECT 1 FROM agent_runs WHERE conversation_id=? AND status IN ('RUNNING','QUEUED')",
            (id,),
        ):
            raise HTTPException(409, "Cancel the active run first")
        PrivateFiles(s).delete_chat(user, id)
        s.db.execute("DELETE FROM conversations WHERE id=?", (id,))
        return {"ok": True}

    @app.post("/api/conversations/{id}/messages")
    def send(id: str, p: Send, user=Depends(current)):
        owned_chat(s.db, id, user)
        if not s.db.rate("messages:" + user["id"], user["messages_per_minute"], 60):
            raise HTTPException(429, "Message rate limit")
        return {"run_id": agent.enqueue(id, user, p.text, p.edit_message_id)}

    @app.post("/api/conversations/{id}/retry")
    def retry(id: str, user=Depends(current)):
        owned_chat(s.db, id, user)
        m = s.db.one(
            "SELECT content FROM messages WHERE conversation_id=? AND role='user' AND active=1 ORDER BY created_at DESC LIMIT 1",
            (id,),
        )
        if not m:
            raise HTTPException(409, "No message to retry")
        if not s.db.rate("messages:" + user["id"], user["messages_per_minute"], 60):
            raise HTTPException(429, "Message rate limit")
        return {"run_id": agent.enqueue(id, user, m["content"], retry=True)}

    def run_owned(id, user):
        r = s.db.one(
            "SELECT * FROM agent_runs WHERE id=? AND user_id=?", (id, user["id"])
        )
        if not r:
            raise HTTPException(404, "Run not found")
        return r

    @app.get("/api/runs/{id}")
    def get_run(id: str, user=Depends(current)):
        r = run_owned(id, user)
        return {
            k: r[k]
            for k in (
                "id",
                "status",
                "error",
                "steps",
                "tool_calls",
                "created_at",
                "finished_at",
            )
        }

    @app.get("/api/science/results/{id}")
    def scientific_result(id: str, user=Depends(current)):
        r = s.db.one(
            "SELECT * FROM scientific_results WHERE id=? AND user_id=?",
            (id, user["id"]),
        )
        if not r:
            raise HTTPException(404, "Scientific result not found")
        owned_chat(s.db, r["conversation_id"], user)
        if hashlib.sha256(r["output"].encode()).hexdigest() != r["output_sha256"]:
            raise HTTPException(409, "Scientific record integrity mismatch")
        return {
            "result_id": r["id"],
            "tool": r["tool"],
            "inputs": json.loads(r["inputs"]),
            "output": json.loads(r["output"]),
            "run_id": r["run_id"],
            "created_at": r["created_at"],
        }

    @app.post("/api/runs/{id}/cancel")
    def cancel(id: str, user=Depends(current)):
        r = run_owned(id, user)
        if r["status"] == "QUEUED":
            s.db.execute(
                "UPDATE agent_runs SET status='CANCELLED',cancel_requested=1,finished_at=? WHERE id=?",
                (time.time(), id),
            )
            s.db.event(
                id,
                "error",
                {"code": "CANCELLED", "label": "أُلغيت المهمة قبل إرسالها للنموذج"},
            )
        elif r["status"] == "RUNNING":
            s.db.execute("UPDATE agent_runs SET cancel_requested=1 WHERE id=?", (id,))
        return {"ok": True}

    @app.get("/api/runs/{id}/events")
    async def events(id: str, request: Request, after: int = 0, user=Depends(current)):
        run_owned(id, user)
        try:
            cursor = max(after, int(request.headers.get("last-event-id", "0")))
        except ValueError:
            raise HTTPException(422, "Invalid event cursor")
        if cursor < 0:
            raise HTTPException(422, "Invalid event cursor")

        async def stream():
            nonlocal cursor
            while True:
                if await request.is_disconnected():
                    return
                session = s.db.one(
                    "SELECT expires_at FROM sessions WHERE token_hash=?",
                    (user["token_hash"],),
                )
                if not session or session["expires_at"] <= time.time():
                    return
                rows = s.db.rows(
                    "SELECT * FROM run_events WHERE run_id=? AND id>? ORDER BY id LIMIT 100",
                    (id, cursor),
                )
                for row in rows:
                    cursor = row["id"]
                    yield f"id: {cursor}\nevent: {row['type']}\ndata: {row['payload']}\n\n"
                r = s.db.one("SELECT status FROM agent_runs WHERE id=?", (id,))
                if not r or (r["status"] not in ("QUEUED", "RUNNING") and not rows):
                    return
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"X-Accel-Buffering": "no"},
        )

    @app.get("/api/owner/models")
    def models(user=Depends(current)):
        owner(user)
        return {
            "items": [
                {
                    **json.loads(r["config"]),
                    "slot": r["slot"],
                    "id": r["id"],
                    "key_saved": bool(r["encrypted_key"]),
                }
                for r in s.db.rows(
                    "SELECT m.* FROM active_models a JOIN model_configs m ON m.id=a.config_id"
                )
            ]
        }

    @app.put("/api/owner/models/{slot}")
    async def model(slot: str, p: ConfigRequest, user=Depends(current)):
        owner(user)
        if slot not in ("agent", "extraction"):
            raise HTTPException(422, "Invalid model slot")
        try:
            await validate_base_url(
                p.config.base_url, s.settings.allow_private_model_urls
            )
        except ValueError as e:
            raise HTTPException(422, str(e)) from None
        existing = s.db.one(
            "SELECT m.* FROM active_models a JOIN model_configs m ON m.id=a.config_id WHERE a.slot=?",
            (slot,),
        )
        if not p.api_key and not existing:
            raise HTTPException(422, "API key is required for the first configuration")
        secret = s.vault.encrypt(p.api_key) if p.api_key else existing["encrypted_key"]
        id = uid("cfg")
        with s.db.tx() as c:
            c.execute(
                "INSERT INTO model_configs VALUES(?,?,?,?,?)",
                (id, slot, p.config.model_dump_json(), secret, time.time()),
            )
            c.execute("INSERT OR REPLACE INTO active_models VALUES(?,?)", (slot, id))
        s.db.audit(
            user["id"], "model.configure", id, {"slot": slot, "model": p.config.model}
        )
        return {"id": id, "key_saved": True}

    @app.get("/api/owner/documents")
    def owner_docs(user=Depends(current)):
        owner(user)
        return {
            "items": [
                {
                    **d,
                    "versions": s.db.rows(
                        "SELECT id,sequence,status FROM versions WHERE document_id=? ORDER BY sequence DESC",
                        (d["id"],),
                    ),
                }
                for d in s.db.rows(
                    "SELECT * FROM documents WHERE status!='DELETED' ORDER BY created_at DESC LIMIT 100"
                )
            ]
        }

    @app.post("/api/owner/documents/upload")
    async def upload(
        metadata: str = Form(...),
        file: UploadFile = File(...),
        document_id: str | None = Form(None),
        user=Depends(current),
    ):
        owner(user)
        temp = None
        try:
            p = Metadata.model_validate_json(metadata)
            if not (file.filename or "").lower().endswith(".pdf"):
                raise HTTPException(422, "PDF required")
            incoming = s.store.path("incoming")
            incoming.mkdir(exist_ok=True)
            fd, name = tempfile.mkstemp(dir=incoming)
            temp = Path(name)
            length = 0
            with os.fdopen(fd, "wb") as f:
                while chunk := await file.read(1024 * 1024):
                    length += len(chunk)
                    if length > s.settings.max_upload_mb * 1024**2:
                        raise HTTPException(413, "File too large")
                    f.write(chunk)
            return await asyncio.to_thread(
                library.upload,
                temp,
                file.filename,
                p.model_dump(),
                user["id"],
                document_id,
            )
        except HTTPException:
            raise
        except (ValueError, __import__("subprocess").SubprocessError):
            raise HTTPException(
                422,
                "Invalid metadata or PDF; encrypted/corrupt/resource limit exceeded",
            ) from None
        finally:
            if temp:
                temp.unlink(missing_ok=True)
            await file.close()

    def selected_file(v, file_id, page=None):
        f = (
            next((f for f in v["files"] if f["id"] == file_id), None)
            if file_id
            else next(f for f in v["files"] if f["role"] == "primary")
        )
        if not f or (
            page is not None and not f["first_page"] <= page <= f["last_page"]
        ):
            raise HTTPException(404, "Source file/page not found")
        return f

    @app.post("/api/owner/versions/{id}/clone")
    def clone(id: str, user=Depends(current)):
        owner(user)
        return library.clone(id, user["id"])

    @app.patch("/api/owner/versions/{id}/metadata")
    def update_metadata(id: str, p: DocumentMetadata, user=Depends(current)):
        owner(user)
        return library.update_metadata(id, p.model_dump(), user["id"])

    @app.patch("/api/owner/versions/{id}/files/{file_id}/range")
    def file_range(id: str, file_id: str, p: PageRange, user=Depends(current)):
        owner(user)
        return library.set_range(id, file_id, p.model_dump(), user["id"])

    @app.post("/api/owner/versions/{id}/solution/upload")
    async def upload_solution(
        id: str,
        metadata: str = Form(...),
        file: UploadFile = File(...),
        user=Depends(current),
    ):
        owner(user)
        temp = None
        try:
            p = SolutionMetadata.model_validate_json(metadata)
            if not (file.filename or "").lower().endswith(".pdf"):
                raise HTTPException(422, "PDF required")
            incoming = s.store.path("incoming")
            incoming.mkdir(exist_ok=True)
            fd, name = tempfile.mkstemp(dir=incoming)
            temp = Path(name)
            length = 0
            with os.fdopen(fd, "wb") as out:
                while chunk := await file.read(1024 * 1024):
                    length += len(chunk)
                    if length > s.settings.max_upload_mb * 1024**2:
                        raise HTTPException(413, "File too large")
                    out.write(chunk)
            return await asyncio.to_thread(
                library.attach_solution,
                id,
                p.model_dump(),
                user["id"],
                temp,
                file.filename,
            )
        except HTTPException:
            raise
        except (ValueError, __import__("subprocess").SubprocessError):
            raise HTTPException(422, "Invalid solution metadata/PDF") from None
        finally:
            if temp:
                temp.unlink(missing_ok=True)
            await file.close()

    @app.post("/api/owner/versions/{id}/solution/range")
    def solution_range(id: str, p: CombinedSolution, user=Depends(current)):
        owner(user)
        return library.attach_solution(
            id,
            p.metadata.model_dump(),
            user["id"],
            page_range=p.page_range.model_dump(),
        )

    @app.post("/api/owner/versions/{id}/solution/verify")
    def solution_verify(id: str, p: SolutionVerification, user=Depends(current)):
        owner(user)
        return library.verify_solution(id, p.model_dump(), user["id"])

    @app.delete("/api/owner/versions/{id}/solution")
    def solution_remove(id: str, user=Depends(current)):
        owner(user)
        return library.remove_solution(id, user["id"])

    @app.get("/api/owner/versions/{id}")
    def version(id: str, user=Depends(current)):
        owner(user)
        return library.version(id)

    @app.post("/api/owner/versions/{id}/process")
    def process(id: str, user=Depends(current)):
        owner(user)
        return library.process(id, user["id"])

    @app.post("/api/owner/versions/{id}/retry/{status}")
    def retry_pages(id: str, status: str, user=Depends(current)):
        owner(user)
        v = library.version(id)
        if v["status"] in ("REVIEWED", "PUBLISHED"):
            raise HTTPException(409, "Create a new version to change reviewed content")
        try:
            raw_status = {"failed": "FAILED", "suspicious": "NEEDS_REVIEW"}[status]
            n = sum(
                s.extraction_queue.retry_pages(bid, raw_status)
                for bid in dict.fromkeys(f["bookforge_id"] for f in v["files"])
            )
        except (ValueError, KeyError):
            raise HTTPException(409, "Invalid retry or extraction state") from None
        return {"scheduled": n}

    @app.get("/api/owner/versions/{id}/page/{page}")
    def preview(id: str, page: int, file_id: str | None = None, user=Depends(current)):
        owner(user)
        v = library.version(id)
        f = selected_file(v, file_id, page)
        frozen = library.approved_page(v, f["id"], page)
        if frozen is not None:
            return {
                "page": page,
                "status": frozen["status"],
                "quality": frozen["quality"],
                "content": s.store.read(frozen["content_file"]).decode()
                if frozen.get("content_file")
                else None,
                "json": json.loads(s.store.read(frozen["json_file"]))
                if frozen.get("json_file")
                else None,
                "immutable_preview": True,
            }
        p = s.extraction_db.one(
            "SELECT * FROM pages WHERE book_id=? AND pdf_page=?",
            (f["bookforge_id"], page),
        )
        if not p:
            raise HTTPException(404, "Page not found")
        return {
            "page": page,
            "status": p["status"],
            "quality": json.loads(p["quality"]),
            "content": s.extraction_store.read(p["artifact_dir"] + "/page.md").decode()
            if p["artifact_dir"]
            else None,
            "json": json.loads(
                s.extraction_store.read(p["artifact_dir"] + "/page.json")
            )
            if p["artifact_dir"]
            else None,
        }

    @app.get("/api/owner/versions/{id}/page/{page}/image")
    async def preview_image(
        id: str, page: int, file_id: str | None = None, user=Depends(current)
    ):
        owner(user)
        v = library.version(id)
        f = selected_file(v, file_id, page)
        frozen = library.approved_page(v, f["id"], page)
        if frozen is not None:
            if not frozen["image_file"]:
                raise HTTPException(404, "Approved source image unavailable")
            return FileResponse(
                s.store.path(frozen["image_file"]), media_type="image/png"
            )
        b = s.extraction_db.one("SELECT * FROM books WHERE id=?", (f["bookforge_id"],))
        p = s.extraction_db.one(
            "SELECT * FROM pages WHERE book_id=? AND pdf_page=?", (b["id"], page)
        )
        if not p:
            raise HTTPException(404, "Page not found")
        from bac.vendor.bookforge.library.uploads import ensure_rendered

        rel = await asyncio.to_thread(
            ensure_rendered, b, p, s.extraction_store, s.extraction_settings
        )
        return FileResponse(s.extraction_store.path(rel), media_type="image/png")

    @app.post("/api/owner/versions/{id}/review")
    def review(id: str, p: Review, user=Depends(current)):
        owner(user)
        return library.review(id, user["id"], p.acknowledge_issues, p.notes)

    @app.post("/api/owner/versions/{id}/publish")
    def publish(id: str, user=Depends(current)):
        owner(user)
        return library.publish(id, user["id"])

    @app.patch("/api/owner/documents/{id}/status")
    def status(id: str, p: StatusUpdate, user=Depends(current)):
        owner(user)
        library.get_doc(id)
        if p.status not in ("ACTIVE", "ARCHIVED"):
            raise HTTPException(422, "Valid states: ACTIVE/ARCHIVED")
        s.db.execute("UPDATE documents SET status=? WHERE id=?", (p.status, id))
        library.cache.clear()
        s.db.audit(user["id"], "document.status", id, {"status": p.status})
        return {"ok": True}

    @app.get("/api/library/documents")
    def docs(
        subject: str | None = None,
        track: str | None = None,
        kind: str | None = None,
        year: str | None = None,
        session: str | None = None,
        exam_type: str | None = None,
        user=Depends(current),
    ):
        return {
            "items": library.list_documents(
                {
                    "subject": subject,
                    "track": track,
                    "kind": kind,
                    "year": year,
                    "session": session,
                    "exam_type": exam_type,
                }
            )
        }

    @app.get("/api/library/documents/{id}")
    def document(id: str, user=Depends(current)):
        return {"document": library.get_doc(id, True), "toc": library.nodes(id)}

    @app.get("/api/library/documents/{id}/toc")
    def toc(id: str, kind: str | None = None, user=Depends(current)):
        return {"items": library.nodes(id, kind)}

    @app.get("/api/library/nodes/{id}")
    def node(id: str, user=Depends(current)):
        return library.node(id)

    @app.get("/api/library/search")
    def search(
        q: str,
        subject: str | None = None,
        track: str | None = None,
        document_id: str | None = None,
        kind: str | None = None,
        year: str | None = None,
        session: str | None = None,
        exam_type: str | None = None,
        user=Depends(current),
    ):
        if not 1 <= len(q) <= 300:
            raise HTTPException(422, "Invalid query")
        return {
            "items": library.search(
                q,
                {
                    "subject": subject,
                    "track": track,
                    "document_id": document_id,
                    "kind": kind,
                    "year": year,
                    "session": session,
                    "exam_type": exam_type,
                },
            )
        }

    @app.get("/api/library/assets/{id}")
    def asset(id: str, user=Depends(current)):
        a = s.db.one(
            "SELECT a.* FROM published_assets a JOIN documents d ON d.id=a.document_id WHERE a.id=? AND d.status='ACTIVE' AND d.published_version=a.version_id",
            (id,),
        )
        if not a:
            raise HTTPException(404, "Published asset not found")
        return FileResponse(s.store.path(a["file"]), media_type="image/png")

    @app.get("/api/library/documents/{id}/page/{page}")
    def source_page(
        id: str, page: int, file_id: str | None = None, user=Depends(current)
    ):
        return FileResponse(
            s.store.path(library.source_page(id, page, file_id)), media_type="image/png"
        )

    @app.get("/api/library/documents/{id}/page/{page}/json")
    def source_json(
        id: str, page: int, file_id: str | None = None, user=Depends(current)
    ):
        return library.source_page(id, page, file_id, "json")

    @app.get("/api/library/nodes/{id}/parts")
    def parts(id: str, user=Depends(current)):
        return {"items": library.parts(id)}

    @app.get("/api/library/parts/{id}")
    def part(id: str, user=Depends(current)):
        return library.part(id)

    @app.get("/api/library/nodes/{id}/bundle")
    def bundle(id: str, user=Depends(current)):
        return library.bundle(id)

    @app.get("/api/library/lessons/{id}")
    def lesson(id: str, user=Depends(current)):
        p = library.node(id)
        if p["node"]["kind"] != "lesson":
            raise HTTPException(422, "An actual lesson is required")
        return p

    @app.get("/api/library/assets/{id}/metadata")
    def asset_metadata(id: str, user=Depends(current)):
        a = library.asset(id)
        return {k: v for k, v in a.items() if k != "file"}

    @app.get("/api/owner/usage")
    def usage(days: int = 30, user=Depends(current)):
        owner(user)
        return report(s, days=days) | {"file_cache": s.library_cache.metrics()}

    @app.get("/api/owner/audit")
    def audit(user=Depends(current)):
        owner(user)
        return {"items": s.db.rows("SELECT * FROM audit ORDER BY id DESC LIMIT 100")}

    @app.get("/api/openapi.json")
    def openapi(user=Depends(current)):
        return app.openapi()

    @app.get("/")
    def home():
        if not (ROOT / "dist/index.html").exists():
            raise HTTPException(
                503, "Build frontend with npm run build, or use Vite development server"
            )
        return FileResponse(ROOT / "dist/index.html")

    if (ROOT / "dist/assets").exists():
        app.mount(
            "/assets",
            StaticFiles(directory=ROOT / "dist/assets"),
            name="frontend-assets",
        )
    return app
