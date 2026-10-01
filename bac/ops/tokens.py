"""Revocable read-only credentials; never reuse a browser/owner principal."""

import hashlib, json, secrets, time
from fastapi import HTTPException
from bac.core.db import uid, js


def issue(s, user, label, documents, days):
    if user["role"] != "owner":
        raise HTTPException(403, "Owner permission required")
    if not label.strip():
        raise HTTPException(422, "Nonempty label required")
    documents = list(dict.fromkeys(documents))
    if not documents:  # Explicit choice required; empty never means all.
        raise HTTPException(422, "Select at least one published document")
    from bac.library.service import Library

    for doc in documents:
        Library(s).get_doc(doc, True)
    id, token, now = uid("token"), "mbac_" + secrets.token_urlsafe(48), time.time()
    with s.db.tx() as c:
        if (
            c.execute(
                "SELECT count(*) FROM service_tokens WHERE creator_id=? AND revoked_at IS NULL AND expires_at>?",
                (user["id"], now),
            ).fetchone()[0]
            >= 25
        ):
            raise HTTPException(409, "At most 25 active service tokens")
        c.execute(
            "INSERT INTO service_tokens(id,label,token_hash,creator_id,documents,expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
            (
                id,
                label.strip(),
                hashlib.sha256(token.encode()).hexdigest(),
                user["id"],
                js(documents),
                now + days * 86400,
                now,
            ),
        )
    s.db.audit(
        user["id"], "service_token.issue", id, {"documents": documents, "days": days}
    )
    return {
        "id": id,
        "token": token,
        "expires_at": now + days * 86400,
        "scope": "published:read",
        "documents": documents,
    }


def authenticate(request):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or len(header) > 256:
        raise HTTPException(401, "Invalid service credential")
    db = request.app.state.db
    r = db.one(
        "SELECT t.* FROM service_tokens t JOIN users u ON u.id=t.creator_id WHERE t.token_hash=? AND t.revoked_at IS NULL AND t.expires_at>? AND u.active=1 AND u.role='owner'",
        (hashlib.sha256(header[7:].encode()).hexdigest(), time.time()),
    )
    if not r:
        raise HTTPException(401, "Expired or revoked service credential")
    if request.method != "GET" or not request.url.path.startswith("/api/agent/"):
        raise HTTPException(403, "Service credentials can only read /api/agent/*")
    if not db.rate("service:" + r["id"], 60, 60):
        raise HTTPException(429, "Service token rate limit: 60 requests/minute")
    db.execute(
        "UPDATE service_tokens SET last_used=? WHERE id=?", (time.time(), r["id"])
    )
    return {"id": r["id"], "role": "service", "documents": json.loads(r["documents"])}
