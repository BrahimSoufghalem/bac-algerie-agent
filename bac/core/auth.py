import hashlib, hmac, secrets, time
from fastapi import HTTPException, Request
from bac.core.db import uid


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return "scrypt$" + salt.hex() + "$" + digest.hex()


def verify_password(password, stored):
    try:
        _, salt, digest = stored.split("$")
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32
        )
        return hmac.compare_digest(actual.hex(), digest)
    except (ValueError, TypeError):
        return False


def create_user(db, email, password, name, role="student"):
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must contain 12–256 characters")
    id = uid("user")
    db.execute(
        "INSERT INTO users(id,email,password_hash,name,role,created_at) VALUES(?,?,?,?,?,?)",
        (
            id,
            email.casefold().strip(),
            hash_password(password),
            name.strip(),
            role,
            time.time(),
        ),
    )
    return id


def new_session(db, user, settings):
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions VALUES(?,?,?,?)",
        (
            hashlib.sha256(token.encode()).hexdigest(),
            user,
            csrf,
            time.time() + settings.session_hours * 3600,
        ),
    )
    return token, csrf


def user_from_request(request: Request):
    token = request.cookies.get("bac_session", "")
    row = request.app.state.db.one(
        "SELECT u.*,s.csrf,s.token_hash FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.active=1",
        (hashlib.sha256(token.encode()).hexdigest(), time.time()),
    )
    if not row:
        raise HTTPException(401, "Authentication required")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        given = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(given, row["csrf"]):
            raise HTTPException(403, "Invalid CSRF token")
        if request.headers.get("origin") and request.headers["origin"].rstrip(
            "/"
        ) != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Invalid origin")
    return row


def public_user(row):
    return {k: row[k] for k in ("id", "email", "name", "role", "preferences")}


def owner(user):
    if user["role"] != "owner":
        raise HTTPException(403, "Owner permission required")


def owned_chat(db, chat, user):
    row = db.one(
        "SELECT * FROM conversations WHERE id=? AND user_id=?", (chat, user["id"])
    )
    if not row:
        raise HTTPException(404, "Conversation not found")
    return row
