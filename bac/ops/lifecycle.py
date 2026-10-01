"""Password/verification links and bounded SMTP outbox; secrets never leave user mail."""

import asyncio, hashlib, json, secrets, smtplib, ssl, time
from email.message import EmailMessage
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from bac.core.auth import hash_password, verify_password
from bac.core.db import uid, js

PUBLIC_PATHS = {
    "/api/auth/request-reset",
    "/api/auth/reset",
    "/api/auth/request-verification",
    "/api/auth/verify",
}


class Address(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)


class LinkUse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=128, repr=False)


class Reset(LinkUse):
    password: str = Field(min_length=12, max_length=256, repr=False)


class Change(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(min_length=1, max_length=256, repr=False)
    new_password: str = Field(min_length=12, max_length=256, repr=False)


def invalidate(c, user):
    c.execute("DELETE FROM sessions WHERE user_id=?", (user,))
    c.execute(
        "UPDATE auth_links SET used_at=? WHERE user_id=? AND used_at IS NULL",
        (time.time(), user),
    )
    c.execute(
        "UPDATE service_tokens SET revoked_at=? WHERE creator_id=? AND revoked_at IS NULL",
        (time.time(), user),
    )
    c.execute(
        "UPDATE agent_runs SET cancel_requested=1 WHERE user_id=? AND status IN ('QUEUED','RUNNING')",
        (user,),
    )
    c.execute(
        "UPDATE mail_outbox SET status='CANCELLED',encrypted_message='' WHERE user_id=? AND status='PENDING'",
        (user,),
    )


def enqueue_link(s, email, purpose):
    if not s.settings.smtp_host or not s.settings.public_origin:
        return  # Same generic response for missing/disabled mail. UI exposes config status.
    row = s.db.one(
        "SELECT * FROM users WHERE email=? AND active=1", (email.casefold().strip(),)
    )
    if not row or (purpose == "verify" and row["email_verified"]):
        return
    token, now = secrets.token_urlsafe(48), time.time()
    payload = {
        "to": row["email"],
        "purpose": purpose,
        "url": s.settings.public_origin.rstrip("/") + "/#auth=" + purpose + ":" + token,
    }
    with s.db.tx() as c:
        c.execute(
            "UPDATE auth_links SET used_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL",
            (now, row["id"], purpose),
        )
        c.execute(
            "INSERT INTO auth_links(id,user_id,purpose,token_hash,expires_at,created_at) VALUES(?,?,?,?,?,?)",
            (
                uid("link"),
                row["id"],
                purpose,
                hashlib.sha256(token.encode()).hexdigest(),
                now + 1200,
                now,
            ),
        )
        c.execute(
            "INSERT INTO mail_outbox(id,user_id,encrypted_message,available_at,created_at) VALUES(?,?,?,?,?)",
            (uid("mail"), row["id"], s.vault.encrypt(js(payload)), now, now),
        )


def use_link(s, token, purpose, password=None):
    digest = hash_password(password) if password else None
    now = time.time()
    with s.db.tx() as c:
        row = c.execute(
            "SELECT l.* FROM auth_links l JOIN users u ON u.id=l.user_id WHERE l.token_hash=? AND l.purpose=? AND l.used_at IS NULL AND l.expires_at>? AND u.active=1",
            (hashlib.sha256(token.encode()).hexdigest(), purpose, now),
        ).fetchone()
        if not row:
            raise HTTPException(400, "Invalid or expired link")
        c.execute("UPDATE auth_links SET used_at=? WHERE id=?", (now, row["id"]))
        if purpose == "reset":
            c.execute(
                "UPDATE users SET password_hash=? WHERE id=?", (digest, row["user_id"])
            )
            invalidate(c, row["user_id"])
        else:
            c.execute("UPDATE users SET email_verified=1 WHERE id=?", (row["user_id"],))
    s.db.audit(row["user_id"], "auth." + purpose)


def router(s, current):
    r = APIRouter()

    def rate(request, key):
        addr = request.client.host if request.client else "unknown"
        if not s.db.rate("auth_links:ip:" + addr, 20, 3600) or not s.db.rate(
            "auth_links:" + hashlib.sha256(key.casefold().strip().encode()).hexdigest(),
            3,
            3600,
        ):
            raise HTTPException(429, "Account recovery rate limit")

    @r.get("/api/auth/policy")
    def policy():
        return {
            "mail_configured": bool(s.settings.smtp_host and s.settings.public_origin),
            "require_verified_email": s.settings.require_verified_email,
            "link_lifetime_minutes": 20,
        }

    @r.post("/api/auth/request-reset")
    def request_reset(p: Address, request: Request):
        rate(request, p.email)
        enqueue_link(s, p.email, "reset")
        return {
            "ok": True,
            "message": "If eligible and SMTP is configured, a link will be sent.",
        }

    @r.post("/api/auth/request-verification")
    def request_verify(p: Address, request: Request):
        rate(request, p.email)
        enqueue_link(s, p.email, "verify")
        return {
            "ok": True,
            "message": "If eligible and SMTP is configured, a link will be sent.",
        }

    @r.post("/api/auth/reset")
    def reset(p: Reset, request: Request):
        rate(request, p.token)
        use_link(s, p.token, "reset", p.password)
        return {"ok": True}

    @r.post("/api/auth/verify")
    def verify(p: LinkUse, request: Request):
        rate(request, p.token)
        use_link(s, p.token, "verify")
        return {"ok": True}

    @r.post("/api/auth/change-password")
    def change(p: Change, user=Depends(current)):
        if not s.db.rate("password_change:" + user["id"], 5, 300):
            raise HTTPException(429, "Password change rate limit")
        # Transaction avoids accepting an old password concurrently with recovery.
        digest = hash_password(p.new_password)
        with s.db.tx() as c:
            fresh = c.execute(
                "SELECT password_hash FROM users WHERE id=? AND active=1", (user["id"],)
            ).fetchone()
            if not fresh or not verify_password(
                p.current_password, fresh["password_hash"]
            ):
                raise HTTPException(403, "Invalid current password")
            c.execute(
                "UPDATE users SET password_hash=? WHERE id=?", (digest, user["id"])
            )
            invalidate(c, user["id"])
        s.db.audit(user["id"], "auth.password_change")
        response = JSONResponse({"ok": True, "sign_in_required": True})
        response.delete_cookie("bac_session")
        return response

    @r.post("/api/auth/revoke-sessions")
    def revoke(user=Depends(current)):
        with s.db.tx() as c:
            invalidate(c, user["id"])
        s.db.audit(user["id"], "auth.revoke_all")
        response = JSONResponse({"ok": True, "sign_in_required": True})
        response.delete_cookie("bac_session")
        return response

    return r


class MailWorker:
    def __init__(self, s, sender=None):
        self.s, self.sender = s, sender or self.send

    def send(self, payload):
        cfg = self.s.settings
        msg = EmailMessage()
        msg["From"], msg["To"] = cfg.smtp_from, payload["to"]
        msg["Subject"] = "Masar: " + (
            "Reset password" if payload["purpose"] == "reset" else "Verify email"
        )
        msg.set_content(
            "Single-use link; expires in 20 minutes. Ignore if not requested.\n"
            + payload["url"]
        )
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as client:
            client.ehlo()
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
            if cfg.smtp_user:
                client.login(cfg.smtp_user, cfg.smtp_password)
            client.send_message(msg)

    def once(self):
        now, lease = time.time(), secrets.token_hex(16)
        with self.s.db.tx() as c:
            row = c.execute(
                "SELECT * FROM mail_outbox WHERE (status='PENDING' AND available_at<=?) OR (status='SENDING' AND lease_until<?) ORDER BY created_at LIMIT 1",
                (now, now),
            ).fetchone()
            if not row:
                return False
            row = dict(row)
            c.execute(
                "UPDATE mail_outbox SET status='SENDING',lease_token=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                (lease, now + 60, row["id"]),
            )
        try:
            payload = json.loads(self.s.vault.decrypt(row["encrypted_message"]))
            # An expired/superseded/reset-invalidated link must not be sent.
            token = payload["url"].rsplit(":", 1)[-1]
            valid = self.s.db.one(
                "SELECT 1 FROM auth_links WHERE token_hash=? AND used_at IS NULL AND expires_at>?",
                (hashlib.sha256(token.encode()).hexdigest(), time.time()),
            )
            if not valid:
                status, error, secret = "CANCELLED", None, ""
            else:
                self.sender(payload)
                status, error, secret = "SENT", None, ""
        except Exception as exc:
            status = "FAILED" if row["attempts"] >= 4 else "PENDING"
            error = type(
                exc
            ).__name__  # No message/recipient/token/SMTP password in log.
            secret = "" if status == "FAILED" else row["encrypted_message"]
        self.s.db.execute(
            "UPDATE mail_outbox SET status=?,error=?,encrypted_message=?,available_at=?,lease_token=NULL,lease_until=NULL WHERE id=? AND lease_token=?",
            (
                status,
                error,
                secret,
                now + min(900, 30 * 2 ** row["attempts"]),
                row["id"],
                lease,
            ),
        )
        return True

    async def run(self, stop):
        while not stop.is_set():
            if self.s.settings.smtp_host:
                await asyncio.to_thread(self.once)
            try:
                await asyncio.wait_for(stop.wait(), 2)
            except asyncio.TimeoutError:
                pass
