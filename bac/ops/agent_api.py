"""Agent access to current approved publications. No chats, uploads, config or drafts."""

import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from bac.core.db import js
from bac.core.auth import owner
from bac.ops.tokens import issue
from bac.library.service import Library


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=100)
    documents: list[str] = Field(min_length=1, max_length=100)
    days: int = Field(default=30, ge=1, le=365)


def router(s, current):
    r, library = APIRouter(), Library(s)

    def adapt(value):
        if isinstance(value, dict):
            return {
                k: adapt(v)
                for k, v in value.items()
                if k not in ("file", "content_file")
            }
        if isinstance(value, list):
            return [adapt(v) for v in value]
        if isinstance(value, str):
            return value.replace("/api/library/assets/", "/api/agent/assets/")
        return value

    def doc_allowed(id, user):
        if user["role"] == "service" and id not in user["documents"]:
            raise HTTPException(404, "Published document not found")
        return library.get_doc(id, True)

    def node_allowed(id, user):
        row = s.db.one("SELECT document_id FROM published_nodes WHERE id=?", (id,))
        if not row:
            raise HTTPException(404, "Published node not found")
        doc_allowed(row["document_id"], user)

    @r.post("/api/owner/service-tokens")
    def create(p: TokenRequest, user=Depends(current)):
        return issue(s, user, p.label, p.documents, p.days)

    @r.get("/api/owner/service-tokens")
    def list_tokens(user=Depends(current)):
        owner(user)
        rows = s.db.rows(
            "SELECT id,label,documents,expires_at,revoked_at,last_used,created_at FROM service_tokens ORDER BY created_at DESC LIMIT 200"
        )
        for row in rows:
            row["documents"] = json.loads(row["documents"])
            row["scope"] = "published:read"
        return {"items": rows}

    @r.delete("/api/owner/service-tokens/{id}")
    def revoke(id: str, user=Depends(current)):
        import time

        owner(user)
        s.db.execute(
            "UPDATE service_tokens SET revoked_at=? WHERE id=?", (time.time(), id)
        )
        s.db.audit(user["id"], "service_token.revoke", id)
        return {"ok": True}

    @r.get("/api/agent/capabilities")
    def capabilities(user=Depends(current)):
        return {
            "version": "1.0",
            "scope": "published:read",
            "tools": [
                "search",
                "get_table_of_contents",
                "get_lesson",
                "get_part",
                "list_parts",
                "get_bundle",
                "get_page",
                "get_asset",
            ],
            "long_content": "full lossless content up to explicit max_chars; otherwise manifest URL, never truncated",
            "rate_limit_per_minute": 60,
        }

    @r.get("/api/agent/books")
    def books(user=Depends(current)):
        rows = library.list_documents()
        return {
            "items": [
                x
                for x in rows
                if user["role"] != "service" or x["id"] in user["documents"]
            ]
        }

    @r.get("/api/agent/books/{id}")
    def book(id: str, user=Depends(current)):
        doc = doc_allowed(id, user)
        return {"book": doc, "toc": library.nodes(id)}

    @r.get("/api/agent/books/{id}/toc")
    def toc(id: str, kind: str | None = None, user=Depends(current)):
        doc_allowed(id, user)
        return {"items": library.nodes(id, kind)}

    @r.get("/api/agent/search")
    def search(
        q: str = Query(min_length=1, max_length=300),
        book_id: str | None = None,
        user=Depends(current),
    ):
        ids = (
            user["documents"]
            if user["role"] == "service"
            else [d["id"] for d in library.list_documents()]
        )
        if book_id:
            doc_allowed(book_id, user)
            ids = [book_id]
        # Scope BEFORE ranking/top-k; filtering a global top-k would hide permitted matches.
        hits = [h for id in ids for h in library.search(q, {"document_id": id})]
        return {"items": sorted(hits, key=lambda h: h.get("score", 0))[:50]}

    @r.get("/api/agent/nodes/{id}")
    def node(id: str, user=Depends(current)):
        node_allowed(id, user)
        return adapt(library.node(id))

    @r.get("/api/agent/get_lesson/{id}")
    def lesson(
        id: str,
        max_chars: int = Query(default=60000, ge=1000, le=500000),
        user=Depends(current),
    ):
        node_allowed(id, user)
        result = library.node(id)
        if result["node"]["kind"] != "lesson":
            raise HTTPException(422, "An actual lesson is required")
        # Full text is not silently truncated. External agents may request lossless parts.
        payload = adapt(
            result
            | {
                "tool": "get_lesson",
                "book": doc_allowed(result["node"]["document_id"], user),
                "content_complete": True,
                "lesson": result["node"],
                "chapter": next(
                    (a for a in result["ancestors"] if a["kind"] == "chapter"), None
                ),
                "pages": list(
                    range(result["node"]["start_page"], result["node"]["end_page"] + 1)
                ),
            }
        )
        if len(js(payload)) > max_chars:
            return {
                "tool": "get_lesson",
                "node_id": id,
                "title": result["node"]["title"],
                "content": None,
                "content_complete": False,
                "reason": "SOURCE_EXCEEDS_BUDGET",
                "parts_url": "/api/agent/nodes/" + id + "/parts",
                "instruction": "Fetch all lossless parts or raise max_chars. No source text was returned or truncated.",
            }
        return payload

    @r.get("/api/agent/nodes/{id}/bundle")
    def bundle(id: str, user=Depends(current)):
        node_allowed(id, user)
        return adapt(library.bundle(id))

    @r.get("/api/agent/nodes/{id}/parts")
    def parts(id: str, user=Depends(current)):
        node_allowed(id, user)
        return {"items": library.parts(id)}

    @r.get("/api/agent/parts/{id}")
    def part(id: str, user=Depends(current)):
        row = s.db.one("SELECT node_id FROM published_parts WHERE id=?", (id,))
        if not row:
            raise HTTPException(404, "Published part not found")
        node_allowed(row["node_id"], user)
        return adapt(library.part(id))

    @r.get("/api/agent/assets/{id}/metadata")
    def asset_meta(id: str, user=Depends(current)):
        a = library.asset(id)
        doc_allowed(a["document_id"], user)
        return {k: v for k, v in a.items() if k != "file"}

    @r.get("/api/agent/assets/{id}")
    def asset(id: str, user=Depends(current)):
        a = library.asset(id)
        doc_allowed(a["document_id"], user)
        return FileResponse(s.store.path(a["file"]), media_type="image/png")

    @r.get("/api/agent/books/{id}/pages/{page}/json")
    def page_json(
        id: str, page: int, file_id: str | None = None, user=Depends(current)
    ):
        doc_allowed(id, user)
        return library.source_page(id, page, file_id, "json")

    @r.get("/api/agent/books/{id}/pages/{page}")
    def page(id: str, page: int, file_id: str | None = None, user=Depends(current)):
        doc_allowed(id, user)
        return FileResponse(
            s.store.path(library.source_page(id, page, file_id)), media_type="image/png"
        )

    return r
