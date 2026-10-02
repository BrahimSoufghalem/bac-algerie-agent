from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.core.auth import create_user


def login(c, email="a@example.com", password="Strong-password-1"):
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200
    return {"X-CSRF-Token": r.json()["csrf"]}


def test_auth_rbac_and_private_conversations(services):
    create_user(services.db, "a@example.com", "Strong-password-1", "A")
    create_user(services.db, "b@example.com", "Strong-password-1", "B")
    app = create_app(services)
    a = TestClient(app)
    b = TestClient(app)
    assert a.get("/api/conversations").status_code == 401
    h = login(a)
    chat = a.post("/api/conversations", json={}, headers=h).json()["id"]
    assert a.get("/api/owner/documents").status_code == 403
    assert a.post("/api/conversations", json={}).status_code == 403
    hb = login(b, "b@example.com")
    assert b.get("/api/conversations/" + chat).status_code == 404
    assert b.delete("/api/conversations/" + chat, headers=hb).status_code == 404
    assert b.get("/api/library/documents").status_code == 404
    assert (
        a.patch(
            "/api/conversations/" + chat, json={"title": "عنوان جديد"}, headers=h
        ).status_code
        == 200
    )


def test_registration_cannot_escalate_role_and_errors_do_not_echo_secrets(services):
    c = TestClient(create_app(services))
    r = c.post(
        "/api/auth/register",
        json={
            "email": "new@example.com",
            "password": "Private-password-123",
            "name": "A",
            "role": "owner",
        },
    )
    assert r.status_code == 422 and "Private-password-123" not in r.text
    r = c.post(
        "/api/auth/register",
        json={
            "email": "new@example.com",
            "password": "Private-password-123",
            "name": "A",
        },
    )
    assert r.status_code == 200 and r.json()["user"]["role"] == "student"


def test_student_cannot_upload_or_get_draft_source(services):
    create_user(services.db, "a@example.com", "Strong-password-1", "A")
    c = TestClient(create_app(services))
    h = login(c)
    assert c.post("/api/owner/documents/upload", headers=h).status_code == 403
    assert c.get("/api/library/assets/missing").status_code == 404
    assert c.get("/api/library/nodes/missing").status_code == 404
