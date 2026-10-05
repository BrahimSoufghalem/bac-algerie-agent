from fastapi import HTTPException
import hashlib, json, os, time, zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import httpx
import pytest
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.core.auth import create_user, verify_password
from bac.core.services import Services
from bac.ops.backup import backup, restore
from bac.ops.guard import DataGuard
from bac.ops.lifecycle import enqueue_link, MailWorker, use_link
from bac.ops.tokens import issue
from tests.test_api import login
from tests.test_library import seeded, process_and_publish


def account(s, role="student", email="a@example.com"):
    id = create_user(s.db, email, "Strong-password-1", "Account", role)
    return s.db.one("SELECT * FROM users WHERE id=?", (id,))


def mail_config(s):
    s.settings = replace(
        s.settings,
        smtp_host="smtp.example.invalid",
        smtp_from="noreply@example.invalid",
        public_origin="https://masar.example.invalid",
    )


def mail_token(s, email, purpose):
    enqueue_link(s, email, purpose)
    row = s.db.one(
        "SELECT encrypted_message FROM mail_outbox ORDER BY created_at DESC LIMIT 1"
    )
    return json.loads(s.vault.decrypt(row["encrypted_message"]))["url"].rsplit(":", 1)[
        -1
    ]


@pytest.mark.asyncio
async def test_external_source_credentials_retired_even_for_published_documents(
    services,
):
    lib, r, owner = seeded(services)
    await process_and_publish(services, lib, r, owner)
    u = services.db.one("SELECT * FROM users WHERE id=?", (owner,))
    with pytest.raises(HTTPException) as exc:
        issue(services, u, "Agent", [r["document_id"]], 1)
    assert exc.value.status_code == 403
    assert not services.db.rows("SELECT * FROM service_tokens")


def test_legacy_service_token_never_bypasses_source_privacy(services):
    u = account(services, "owner")
    now = time.time()
    services.db.execute(
        "INSERT INTO service_tokens(id,label,token_hash,creator_id,documents,expires_at,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            "legacy",
            "old",
            hashlib.sha256(b"mbac_old").hexdigest(),
            u["id"],
            "[]",
            now + 600,
            now,
        ),
    )
    c = TestClient(create_app(services))
    h = {"Authorization": "Bearer mbac_old"}
    for path in [
        "/api/agent/capabilities",
        "/api/agent/books",
        "/api/agent/search?q=الحرارة",
        "/api/auth/me",
        "/api/notes",
    ]:
        assert c.get(path, headers=h).status_code == 403


def test_password_change_revokes_other_sessions_tokens_and_queued_runs(services):
    u = account(services)
    app = create_app(services)
    a, b = TestClient(app), TestClient(app)
    ha, hb = login(a), login(b)
    chat = a.post("/api/conversations", json={"subject": "physics"}, headers=ha).json()[
        "id"
    ]
    assert (
        a.post(
            "/api/auth/change-password",
            json={"current_password": "wrong", "new_password": "Changed-password-123"},
            headers=ha,
        ).status_code
        == 403
    )
    assert (
        a.post(
            "/api/auth/change-password",
            json={
                "current_password": "Strong-password-1",
                "new_password": "Changed-password-123",
            },
        ).status_code
        == 403
    )
    assert (
        a.post(
            "/api/auth/change-password",
            json={
                "current_password": "Strong-password-1",
                "new_password": "Changed-password-123",
            },
            headers=ha,
        ).status_code
        == 200
    )
    assert b.get("/api/conversations/" + chat).status_code == 401
    assert verify_password(
        "Changed-password-123",
        services.db.one("SELECT password_hash FROM users WHERE id=?", (u["id"],))[
            "password_hash"
        ],
    )
    assert not services.db.rows("SELECT * FROM sessions")
    assert login(b, password="Changed-password-123")
    assert (
        b.post(
            "/api/auth/revoke-sessions",
            json={},
            headers=login(b, password="Changed-password-123"),
        ).status_code
        == 200
    )
    assert b.get("/api/auth/me").status_code == 401
    assert hb


@pytest.mark.parametrize("purpose", ["reset", "verify"])
def test_auth_links_single_use_expiry_purpose_and_outbox_secret_scrub(
    services, purpose
):
    u = account(services)
    mail_config(services)
    token = mail_token(services, u["email"], purpose)
    assert token not in json.dumps(services.db.rows("SELECT * FROM auth_links"))
    assert token not in json.dumps(services.db.rows("SELECT * FROM mail_outbox"))
    sent = []
    assert MailWorker(services, sent.append).once()
    assert token in sent[0]["url"]
    assert (
        services.db.one("SELECT status,encrypted_message FROM mail_outbox")[
            "encrypted_message"
        ]
        == ""
    )
    with pytest.raises(Exception):
        use_link(
            services,
            token,
            "reset" if purpose == "verify" else "verify",
            "Changed-password-123",
        )
    use_link(
        services, token, purpose, "Changed-password-123" if purpose == "reset" else None
    )
    with pytest.raises(Exception):
        use_link(
            services,
            token,
            purpose,
            "Changed-password-123" if purpose == "reset" else None,
        )
    if purpose == "verify":
        assert (
            services.db.one("SELECT email_verified FROM users WHERE id=?", (u["id"],))[
                "email_verified"
            ]
            == 1
        )
    token2 = mail_token(services, u["email"], "reset")
    services.db.execute("UPDATE auth_links SET expires_at=0")
    with pytest.raises(Exception):
        use_link(services, token2, "reset", "Changed-password-123")


def test_mail_retry_bounded_safe_errors_and_superseded_links(services):
    u = account(services)
    mail_config(services)
    mail_token(services, u["email"], "reset")
    mail_token(services, u["email"], "reset")
    calls = []
    worker = MailWorker(services, calls.append)
    assert worker.once() and not calls  # old token is cancelled, not sent.

    def fail(_):
        raise OSError("secret-SMTP-password-and-link")

    worker.sender = fail
    for _ in range(5):
        services.db.execute(
            "UPDATE mail_outbox SET available_at=0 WHERE status='PENDING'"
        )
        assert worker.once()
    rows = services.db.rows("SELECT * FROM mail_outbox")
    assert "secret-SMTP" not in json.dumps(rows)
    assert (
        rows[-1]["status"] == "FAILED"
        and rows[-1]["attempts"] == 5
        and rows[-1]["encrypted_message"] == ""
    )


def test_recovery_generic_and_verified_policy_real_endpoints(services):
    u = account(services)
    mail_config(services)
    services.settings = replace(services.settings, require_verified_email=True)
    c = TestClient(create_app(services))
    assert (
        c.post(
            "/api/auth/login",
            json={"email": u["email"], "password": "Strong-password-1"},
        ).status_code
        == 403
    )
    body = c.post("/api/auth/request-reset", json={"email": u["email"]}).json()
    assert (
        c.post("/api/auth/request-reset", json={"email": "absent@example.com"}).json()
        == body
    )
    assert "token" not in json.dumps(body)
    token = mail_token(services, u["email"], "verify")
    assert c.post("/api/auth/verify", json={"token": token}).status_code == 200
    h = login(c)
    token = mail_token(services, u["email"], "reset")
    assert (
        c.post(
            "/api/auth/reset", json={"token": token, "password": "Changed-password-123"}
        ).status_code
        == 200
    )
    assert c.get("/api/auth/me", headers=h).status_code == 401
    assert (
        c.post(
            "/api/auth/reset", json={"token": token, "password": "Changed-password-123"}
        ).status_code
        == 400
    )


def test_email_validation_and_unconfigured_smtp(services):
    for email, name in [
        ("x@y", "A"),
        ("bad\r\n@example.com", "A"),
        ("good@example.com", "  "),
    ]:
        with pytest.raises(ValueError):
            create_user(services.db, email, "Strong-password-1", name)
    account(services)
    c = TestClient(create_app(services))
    assert c.get("/api/auth/policy").json()["mail_configured"] is False
    assert (
        c.post("/api/auth/request-reset", json={"email": "a@example.com"}).status_code
        == 200
    )
    assert not services.db.rows("SELECT * FROM mail_outbox")


@pytest.mark.asyncio
async def test_actual_chunked_request_bytes_capped_and_host_origin_enforced(services):
    app = create_app(services)

    async def chunks():
        yield b'{"email":"'
        yield b"x" * 300000
        yield b'"}'

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://testserver"
    ) as c:
        r = await c.post(
            "/api/auth/request-reset",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 413
    services.settings = replace(
        services.settings, trusted_hosts=("masar.example.invalid",)
    )
    c = TestClient(create_app(services), base_url="http://other.invalid")
    assert c.get("/health").status_code == 400
    c = TestClient(create_app(services))
    services.settings = replace(services.settings, trusted_hosts=())
    # Existing origin check with a valid session.
    c = TestClient(create_app(services))
    account(services)
    h = login(c)
    assert (
        c.post(
            "/api/conversations",
            json={},
            headers=h | {"Origin": "https://evil.invalid"},
        ).status_code
        == 403
    )


@pytest.mark.asyncio
async def test_full_backup_restore_preserves_approved_source_two_keys_and_auth(
    services, tmp_path
):
    lib, r, u = seeded(services)
    await process_and_publish(services, lib, r, u)
    marker = services.vault.encrypt("test-vault-secret")
    services.store.write("private/retained.txt", b"private-test-only")
    root = services.store.root
    target = tmp_path.parent / (tmp_path.name + "-backup.zip")
    with pytest.raises(RuntimeError):
        backup(root, target)
    services.close()
    result = backup(root, target)
    assert result["files"] >= 4 and os.stat(target).st_mode & 0o777 == 0o600
    dest = tmp_path.parent / (tmp_path.name + "-restored")
    restore(target, dest)
    restored = Services(replace(services.settings, data_dir=dest))
    try:
        assert restored.vault.decrypt(marker) == "test-vault-secret"
        assert (dest / "extraction/.encryption.key").read_bytes() == (
            root / "extraction/.encryption.key"
        ).read_bytes()
        from bac.library.service import Library

        new = Library(restored)
        lesson = new.nodes(r["document_id"], "lesson")[0]
        assert "الحرارة تنتقل" in new.node(lesson["id"])["content"]
        assert restored.store.read("private/retained.txt") == b"private-test-only"
        assert login(TestClient(create_app(restored)), "owner@example.com")
        with pytest.raises(ValueError):
            restore(target, dest)
    finally:
        restored.close()


@pytest.mark.parametrize(
    "badname", ["../escape", "/absolute", "a\\b", "C:drive", "a/../../evil"]
)
def test_restore_rejects_unsafe_paths(tmp_path, badname):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr(badname, "bad")
    with pytest.raises(ValueError):
        restore(archive, tmp_path / "dest")
    assert not (tmp_path / "dest").exists()


def test_restore_rejects_corruption_missing_key_duplicates_symlink_and_zip_bomb(
    services, tmp_path
):
    root = services.store.root
    services.close()
    archive = tmp_path.parent / (tmp_path.name + "-ok.zip")
    backup(root, archive)
    with zipfile.ZipFile(archive) as z:
        source = {i.filename: z.read(i) for i in z.infolist()}
    for name in ("corrupt", "missing", "duplicate", "symlink", "large"):
        out = tmp_path / (name + ".zip")
        with zipfile.ZipFile(out, "w") as z:
            for path, data in source.items():
                if name == "missing" and path == "extraction/.encryption.key":
                    continue
                z.writestr(
                    path,
                    b"altered"
                    if name == "corrupt" and path == "platform.sqlite3"
                    else data,
                )
            if name == "duplicate":
                z.writestr("platform.sqlite3", b"duplicate")
            if name == "symlink":
                i = zipfile.ZipInfo("link")
                i.external_attr = 0o120777 << 16
                z.writestr(i, "../../outside")
        with pytest.raises((ValueError, zipfile.BadZipFile)):
            restore(
                out,
                tmp_path / (name + "-restored"),
                max_bytes=10 if name == "large" else 5 * 1024**3,
            )


def test_lifecycle_lock_exclusive_and_shared_cross_process(tmp_path):
    import subprocess, sys

    with DataGuard(tmp_path):
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                'from bac.ops.guard import DataGuard; from pathlib import Path; DataGuard(Path(__import__("sys").argv[1]),exclusive=True)',
                str(tmp_path),
            ],
            capture_output=True,
        )
        assert proc.returncode != 0 and b"Data is in use" in proc.stderr
    with DataGuard(tmp_path, exclusive=True):
        with pytest.raises(RuntimeError):
            DataGuard(tmp_path)


def test_atomic_recovery_concurrency_one_success(services):
    u = account(services)
    mail_config(services)
    token = mail_token(services, u["email"], "reset")

    def attempt(_):
        try:
            use_link(services, token, "reset", "Changed-password-123")
            return "ok"
        except Exception:
            return "denied"

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(attempt, range(4))).count("ok") == 1


@pytest.mark.asyncio
async def test_isolated_load_probe_claims_no_duplicate_and_no_http_errors():
    from bac.ops.load import benchmark

    r = await benchmark(requests=40, concurrency=4, runs=12)
    assert (
        r["http_errors"]
        == r["duplicate_claims"]
        == r["missing_jobs"]
        == r["paid_calls"]
        == 0
    )


def test_crash_orphan_cleanup_preserves_fresh_inflight_directory(services):
    from bac.learning.private import PrivateFiles

    old = services.store.path("private/upload_old")
    old.mkdir(parents=True)
    fresh = services.store.path("private/upload_fresh")
    fresh.mkdir()
    os.utime(old, (time.time() - 7200, time.time() - 7200))
    PrivateFiles(services).cleanup()
    assert not old.exists() and fresh.exists()


@pytest.mark.asyncio
async def test_opt_in_provider_smoke_two_calls_no_retry_no_secret_report(tmp_path):
    from PIL import Image
    from bac.ops.evaluate_provider import evaluate

    image = tmp_path / "page.png"
    Image.new("RGB", (200, 300), "white").save(image)
    calls = []

    def respond(req):
        calls.append(json.loads(req.content))
        msg = (
            {
                "content": json.dumps(
                    {
                        "pdf_page": 1,
                        "width": 200,
                        "height": 300,
                        "languages": ["ar"],
                        "elements": [
                            {
                                "id": "p",
                                "type": "paragraph",
                                "order": 0,
                                "text": "حرارة",
                                "bbox": [1, 1, 50, 50],
                            }
                        ],
                    }
                )
            }
            if len(calls) == 1
            else {
                "content": None,
                "tool_calls": [
                    {
                        "id": "t",
                        "type": "function",
                        "function": {
                            "name": "render_answer",
                            "arguments": json.dumps(
                                {
                                    "text": "الناتج 24 J",
                                    "source_ids": ["fixture-source"],
                                }
                            ),
                        },
                    }
                ],
            }
        )
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": msg}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    out = tmp_path / "result.json"
    result = await evaluate(
        image,
        out,
        "secret-test-key",
        "https://example.invalid/v1",
        "mock",
        transport=httpx.MockTransport(respond),
    )
    assert (
        len(calls) == result["generation_calls"] == 2
        and result["automatic_retries"] == 0
    )
    assert (
        result["checks"]["vision"]["schema_valid"]
        and result["checks"]["teaching"]["tool_call_valid"]
    )
    assert "secret-test-key" not in out.read_text()
    calls.clear()

    def failing(req):
        calls.append(1)
        return httpx.Response(429)

    result = await evaluate(
        image,
        out,
        "secret-test-key",
        "https://example.invalid/v1",
        "mock",
        transport=httpx.MockTransport(failing),
    )
    assert len(calls) == 2 and result["checks"]["vision"]["error"] == "HTTP_429"


def test_login_session_refuses_stale_password_hash_after_password_reset(services):
    from bac.core.auth import new_session, hash_password

    u = account(services)
    services.db.execute(
        "UPDATE users SET password_hash=? WHERE id=?",
        (hash_password("Changed-password-123"), u["id"]),
    )
    with pytest.raises(Exception):
        new_session(
            services.db, u["id"], services.settings, expected_hash=u["password_hash"]
        )
    assert not services.db.rows("SELECT * FROM sessions")


@pytest.mark.asyncio
async def test_agent_oversize_manifest_never_returns_truncated_text(services):
    lib, r, o = seeded(services)
    await process_and_publish(services, lib, r, o)
    c = TestClient(create_app(services))
    login(c, "owner@example.com")
    node = lib.nodes(r["document_id"], "lesson")[0]["id"]
    result = c.get("/api/agent/get_lesson/" + node + "?max_chars=1000").json()
    assert (
        result["content_complete"] is False
        and result["content"] is None
        and result["parts_url"].endswith("/parts")
    )
    full = c.get("/api/agent/get_lesson/" + node + "?max_chars=60000").json()
    assert (
        full["content_complete"] is True
        and full["pages"] == [1]
        and full["chapter"] is None
    )


def test_real_production_uvicorn_factory_starts_and_protects_library(tmp_path):
    import socket, subprocess, sys, urllib.request, urllib.error

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    env.update(
        {
            "DATA_DIR": str(tmp_path),
            "SECURE_COOKIES": "false",
            "TRUSTED_HOSTS": "",
            "SMTP_HOST": "",
            "REQUIRE_VERIFIED_EMAIL": "false",
        }
    )
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "bac.api.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ready = False
        for _ in range(100):
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/health", timeout=0.5
                ) as r:
                    ready = r.status == 200
                if ready:
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        assert ready, "Real documented production entry point must start"
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/agent/books", timeout=2
            )
        assert err.value.code == 401
        with pytest.raises(RuntimeError):
            DataGuard(tmp_path, exclusive=True)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    with DataGuard(tmp_path, exclusive=True):
        pass


def test_external_client_serialized_budget_and_no_duplicate_part_content():
    from examples.agent_client import LibraryClient

    client = LibraryClient(
        "https://library.example.invalid", "test-token", max_context_chars=1000
    )

    def fake(path, **params):
        if "/get_lesson/" in path:
            return {"content_complete": False, "parts_url": "/api/agent/nodes/l/parts"}
        if path.endswith("/parts"):
            return {"items": [{"id": "p1"}, {"id": "p2"}]}
        return {
            "node": {"id": "l"},
            "document": {"id": "b"},
            "content": path.rsplit("/", 1)[-1],
            "assets": [{"id": "a"}],
            "sources": [{"source_id": path.rsplit("/", 1)[-1]}],
        }

    client.get = fake
    try:
        result = client.get_lesson("l")
        assert result["content"] == "p1\n\np2" and result["part_ids"] == ["p1", "p2"]
        assert len(result["assets"]) == 1 and "parts" not in result
        assert len(json.dumps(result, ensure_ascii=False)) <= 1000
        client.get = lambda *a, **k: {
            "content_complete": True,
            "content": "short",
            "metadata": "x" * 1000,
        }
        with pytest.raises(ValueError):
            client.get_lesson("l")
    finally:
        client.close()
