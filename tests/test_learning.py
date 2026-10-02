import io, json, time
from concurrent.futures import ThreadPoolExecutor
import httpx
from PIL import Image
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.agent.engine import AgentEngine
from bac.agent.tools import Tools
from bac.core.auth import create_user
from bac.core.db import DB, uid, js
from bac.learning.service import Learning
from bac.learning.private import PrivateFiles
from bac.learning.contracts import Material
from bac.learning.usage import record, report, check_budget
from bac.agent.provider import ModelError
from tests.test_agent import chat_and_config
from tests.test_api import login
from tests.test_library import seeded


def setup_client(s, role="student", email="a@example.com"):
    id = create_user(s.db, email, "Strong-password-1", "Test", role)
    client = TestClient(create_app(s))
    h = login(client, email)
    return client, h, s.db.one("SELECT * FROM users WHERE id=?", (id,))


def png():
    b = io.BytesIO()
    Image.new("RGB", (320, 500), (110, 180, 220)).save(b, "PNG")
    return b.getvalue()


def test_preferences_and_consent_no_escalation(services):
    c, h, u = setup_client(services)
    p = c.get("/api/preferences").json()
    assert p["include_approved_notes"] is False
    assert (
        c.put("/api/preferences", json=p | {"role": "owner"}, headers=h).status_code
        == 422
    )
    p.update(language="fr", detail="deep", track="علوم تجريبية", subjects=["فيزياء"])
    assert c.put("/api/preferences", json=p, headers=h).status_code == 200
    chat = c.post("/api/conversations", json={}, headers=h).json()["id"]
    assert (
        c.put(
            f"/api/conversations/{chat}/preferences",
            json={"system": "override"},
            headers=h,
        ).status_code
        == 422
    )
    assert (
        c.put(
            f"/api/conversations/{chat}/preferences", json={"language": "ar"}, headers=h
        ).status_code
        == 200
    )
    note = {"category": "goal", "content": "مراجعة الوحدات", "consent": True}
    assert c.post("/api/notes", json=note, headers=h).status_code == 403
    assert c.get("/api/notes").json()["read_only"] is True
    exported = c.get("/api/privacy/export")
    assert (
        exported.status_code == 200
        and "password_hash" not in exported.text
        and "encrypted_key" not in exported.text
    )
    assert exported.json()["notes"] == []


def test_note_proposal_pending_snapshot_and_stale_source(services):
    u, chat = chat_and_config(services)
    engine = AgentEngine(services)
    run = engine.enqueue(chat, u, "Question")
    job = engine.claim()
    learn = Learning(services)
    n = learn.propose(
        u, run, {"category": "weakness", "content": "Tentative difficulty"}
    )
    assert n["status"] == "pending"
    assert json.loads(services.db.one("SELECT notes FROM run_contexts")["notes"]) == []
    approved = learn.save_note(
        u,
        {
            "category": "weakness",
            "content": "I confirm this difficulty",
            "consent": True,
        },
        n["id"],
    )
    assert approved["status"] == "approved"
    assert (
        services.db.one("SELECT cancel_requested FROM agent_runs WHERE id=?", (run,))[
            "cancel_requested"
        ]
        == 1
    )
    services.db.execute("UPDATE agent_runs SET status='CANCELLED' WHERE id=?", (run,))
    prefs = learn.preferences(u)
    prefs["include_approved_notes"] = True
    learn.set_preferences(u, prefs)
    run2 = engine.enqueue(chat, u, "New")
    job2 = engine.claim()
    tools = Tools(services, u, chat, run2)
    context = engine.context(job2, tools, u)
    assert "I confirm this difficulty" not in js(context)
    note2 = learn.propose(u, run2, {"category": "mistake", "content": "proposed"})
    services.db.execute(
        "UPDATE messages SET active=0 WHERE id=?", (job2["message_id"],)
    )
    with pytest.raises(HTTPException) as e:
        learn.save_note(
            u, {"category": "goal", "content": "approve", "consent": True}, note2["id"]
        )
    assert e.value.status_code == 409
    # Context prefix stays stable while settings/approved notes vary.
    assert context[0]["content"] == engine.context(job, tools, u)[0]["content"]
    learn.delete_note(u, n["id"])
    assert n["id"] not in js(learn.notes(u))
    assert "I confirm this difficulty" not in js(
        services.db.rows("SELECT notes FROM run_contexts")
    )


def test_zero_allowance_concurrent_guard_and_role_admin(services):
    c, h, owner = setup_client(services, "owner")
    u, chat = chat_and_config(services)
    assert (
        c.patch(
            "/api/owner/accounts/" + owner["id"], json={"active": False}, headers=h
        ).status_code
        == 409
    )
    assert (
        c.patch(
            "/api/owner/accounts/" + u["id"],
            json={"daily_limit": 0, "daily_tokens": 0},
            headers=h,
        ).status_code
        == 200
    )
    with pytest.raises(HTTPException) as e:
        AgentEngine(services).enqueue(chat, u, "question")
    assert e.value.status_code == 429
    c.patch(
        "/api/owner/accounts/" + u["id"],
        json={"daily_limit": None, "daily_tokens": None},
        headers=h,
    )
    engine = AgentEngine(services)
    chats = [chat]
    for _ in range(3):
        id = uid("chat")
        services.db.execute(
            "INSERT INTO conversations VALUES(?,?,?,?,?,?)",
            (id, u["id"], "Other", "{}", time.time(), time.time()),
        )
        chats.append(id)

    def enqueue(chat):
        try:
            return engine.enqueue(chat, u, "test")
        except HTTPException:
            return None

    with ThreadPoolExecutor(max_workers=4) as pool:
        r = list(pool.map(enqueue, chats))
    assert sum(x is not None for x in r) == 1
    assert (
        c.patch(
            "/api/owner/accounts/" + u["id"], json={"role": "teacher"}, headers=h
        ).status_code
        == 200
    )
    assert (
        services.db.one("SELECT cancel_requested FROM agent_runs")["cancel_requested"]
        == 1
    )
    assert (
        services.db.one("SELECT action FROM audit ORDER BY id DESC")["action"]
        == "account.update"
    )
    assert "preferences" not in c.get("/api/owner/accounts").text


@pytest.mark.parametrize(
    "ext,data", [(".txt", b"Original text"), (".png", png())], ids=["text", "image"]
)
def test_private_files_ownership_chat_expiry_delete_no_shared_index(
    services, ext, data
):
    u, chat = chat_and_config(services)
    private = PrivateFiles(services)
    f = private.add(u, chat, "source" + ext, data)
    other_id = create_user(services.db, "b@example.com", "Strong-password-1", "B")
    other = services.db.one("SELECT * FROM users WHERE id=?", (other_id,))
    with pytest.raises(HTTPException):
        private.row(other, f["id"])
    with pytest.raises(HTTPException):
        private.page(u, f["id"], 1, "foreign-chat")
    result, path = private.page(u, f["id"], 1, chat)
    assert result["source"]["scope"] == "private"
    if ext == ".png":
        assert path.read_bytes().startswith(b"\xff\xd8")
    assert services.db.rows("SELECT * FROM published_nodes") == []
    assert services.extraction_db.rows("SELECT * FROM books") == []
    services.db.execute(
        "UPDATE private_uploads SET expires_at=? WHERE id=?", (time.time() - 1, f["id"])
    )
    with pytest.raises(HTTPException):
        private.page(u, f["id"], 1, chat)
    private.cleanup()
    assert not services.store.path("private/" + f["id"]).exists()


def test_private_pdf_and_limits(services):
    import pymupdf

    u, chat = chat_and_config(services)
    private = PrivateFiles(services)
    doc = pymupdf.open()
    doc.new_page()
    blob = doc.tobytes()
    doc.close()
    f = private.add(u, chat, "p.pdf", blob)
    assert f["pages"] == 1
    _, image = private.page(u, f["id"], 1, chat)
    assert image.exists()
    for name, data in [
        ("bad.svg", b"<svg/>"),
        ("bad.pdf", b"not PDF"),
        ("bad.txt", b"\x00"),
        ("bad.png", b"not png"),
    ]:
        with pytest.raises((HTTPException, ValueError, OSError)):
            private.add(u, chat, name, data)
    for i in range(4):
        private.add(u, chat, str(i) + ".txt", b"x")
    with pytest.raises(HTTPException) as exc:
        private.add(u, chat, "extra.txt", b"x")
    assert exc.value.status_code == 409
    assert len(list(services.store.path("private").iterdir())) == 5


class PrivateScript:
    def __init__(self, upload):
        self.upload, self.step, self.saw_pixels = upload, 0, False

    async def stream(self, messages, tools):
        self.step += 1
        if self.step == 1:
            name, args = "read_private_page", {"upload_id": self.upload, "page": 1}
        else:
            self.saw_pixels = any(
                isinstance(m.get("content"), list)
                and any(x.get("type") == "image_url" for x in m["content"])
                for m in messages
            )
            name, args = (
                "render_answer",
                {
                    "blocks": [
                        {"type": "text", "text": "Read private image"},
                    ],
                    "source_ids": [self.upload + ":1"],
                },
            )
        yield {
            "type": "usage",
            "data": {
                "prompt_tokens": 4,
                "completion_tokens": 3,
                "prompt_tokens_details": {"cached_tokens": 1},
            },
        }
        yield {
            "type": "result",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "p" + str(self.step),
                        "type": "function",
                        "function": {"name": name, "arguments": js(args)},
                    }
                ],
            },
        }


@pytest.mark.asyncio
async def test_private_actual_pixels_credit_and_no_base64_persistence(services):
    u, chat = chat_and_config(services)
    p = PrivateFiles(services)
    f = p.add(u, chat, "source.png", png())
    script = PrivateScript(f["id"])
    services.chat_factory = lambda cfg, key: script
    engine = AgentEngine(services)
    run = engine.enqueue(chat, u, "Read this")
    await engine.process(engine.claim())
    r = services.db.one("SELECT * FROM agent_runs WHERE id=?", (run,))
    assert r["status"] == "COMPLETED", r
    assert script.saw_pixels
    message = services.db.one("SELECT * FROM messages WHERE role='assistant'")
    blocks = json.loads(message["blocks"])
    assert all(b["type"] != "image" for b in blocks)
    assert "base64" not in js(services.db.rows("SELECT * FROM run_events"))
    assert services.db.rows("SELECT * FROM loaded_context") == []
    usage = services.db.rows("SELECT * FROM model_usage")
    assert usage[-1]["feature"] == "private_vision"
    tools = Tools(services, u, chat)
    result, image = p.page(u, f["id"], 1, chat)
    with pytest.raises(ValueError):
        tools.answer(
            {
                "blocks": [{"type": "text", "text": "not loaded"}],
                "source_ids": [f["id"] + ":1"],
            }
        )
    tools.credit_private(result)
    p.delete(u, f["id"])
    with pytest.raises(HTTPException):
        tools.answer(
            {
                "blocks": [{"type": "text", "text": "expired"}],
                "source_ids": [f["id"] + ":1"],
            }
        )


def test_teacher_role_drafts_marks_and_student_private_access(services):
    u, chat = chat_and_config(services)
    engine = AgentEngine(services)
    run = engine.enqueue(chat, u, "Practice")
    engine.claim()
    tools = Tools(services, u, chat, run)
    p = {
        "kind": "self_practice",
        "title": "Practice",
        "answer": {"blocks": [{"type": "text", "text": "Solve x+1=2"}]},
        "rubric": [{"title": "Solve", "maximum": 2}],
        "total": 2,
        "solution": "x=1",
    }
    with pytest.raises(ValueError):
        tools.execute("save_practice_test", p)
    with pytest.raises(ValueError):
        tools.execute("save_teaching_material", p | {"kind": "lesson_plan"})
    services.db.execute("UPDATE users SET role='teacher' WHERE id=?", (u["id"],))
    lesson = tools.execute("save_teaching_material", p | {"kind": "lesson_plan"})
    assert lesson["kind"] == "lesson_plan"
    with pytest.raises(ValueError):
        Material.model_validate(p | {"total": 3})
    with pytest.raises(ValueError):
        Material.model_validate(
            p
            | {
                "kind": "grading",
                "rubric": [{"title": "Solve", "maximum": 2, "awarded": 3}],
            }
        )
    with pytest.raises(ValueError):
        Material.model_validate(p | {"solution": ""})
    other_id = create_user(
        services.db, "other@example.com", "Strong-password-1", "Other"
    )
    other = services.db.one("SELECT * FROM users WHERE id=?", (other_id,))
    with pytest.raises(HTTPException):
        Learning(services).materials(other, lesson["id"])
    # Owner also cannot read another user's private draft.
    services.db.execute("UPDATE users SET role='owner' WHERE id=?", (other_id,))
    with pytest.raises(HTTPException):
        Learning(services).materials(other, lesson["id"])


def test_real_usage_nulls_pricing_cache_and_budget(services):
    u, chat = chat_and_config(services)
    cfg = {
        "model": "m",
        "input_price_per_million": 2,
        "output_price_per_million": 4,
        "cached_price_per_million": 1,
    }
    record(
        services,
        cfg,
        {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "prompt_tokens_details": {"cached_tokens": 30},
        },
        10,
        user=u["id"],
        config_id="cfg",
    )
    record(
        services,
        cfg,
        {},
        20,
        user=u["id"],
        config_id="cfg",
        status="error",
        feature="private_vision",
    )
    data = report(services, u)
    assert data["missing_usage_calls"] == 1
    first = next(r for r in data["items"] if r["feature"] == "teaching")
    assert abs(first["estimated_cost"] - 0.00025) < 1e-9
    services.db.execute("UPDATE users SET daily_tokens=200 WHERE id=?", (u["id"],))
    with pytest.raises(ModelError, match="UNKNOWN"):
        check_budget(services, u["id"])
    services.db.execute("DELETE FROM model_usage WHERE input_tokens IS NULL")
    check_budget(services, u["id"])
    services.db.execute("UPDATE users SET daily_tokens=100 WHERE id=?", (u["id"],))
    with pytest.raises(ModelError, match="ALLOWANCE"):
        check_budget(services, u["id"])


@pytest.mark.asyncio
async def test_metered_extraction_records_requests_not_cached_artifacts(services):
    from bac.learning.usage import MeteredVision
    from tests.test_library import FakeVision

    lib, r, owner = seeded(services)
    cfg = uid("cfg")
    services.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            cfg,
            "extraction",
            js({"base_url": "https://example.org/v1", "model": "fake"}),
            services.vault.encrypt("fake"),
            time.time(),
        ),
    )
    services.db.execute("INSERT INTO active_models VALUES(?,?)", ("extraction", cfg))
    services.extraction_engine.provider_factory = lambda config, key: MeteredVision(
        services, FakeVision(), config
    )
    lib.process(r["version_id"], owner)
    while job := services.extraction_queue.claim():
        await services.extraction_engine.process(job)
    rows = services.db.rows("SELECT * FROM model_usage WHERE feature='extraction'")
    assert len(rows) == 1 and rows[0]["run_id"] is None and rows[0]["config_id"] == cfg
    lib.version(r["version_id"])
    assert (
        len(services.db.rows("SELECT * FROM model_usage WHERE feature='extraction'"))
        == 1
    )


def test_private_api_csrf_no_store_export_erase(services):
    c, h, u = setup_client(services)
    chat = c.post("/api/conversations", json={}, headers=h).json()["id"]
    assert (
        c.post(
            f"/api/conversations/{chat}/upload", files={"file": ("x.txt", b"private")}
        ).status_code
        == 403
    )
    f = c.post(
        f"/api/conversations/{chat}/upload",
        files={"file": ("x.txt", b"private")},
        headers=h,
    )
    assert f.status_code == 200, f.text
    id = f.json()["id"]
    assert c.get(f"/api/private/{id}/original").headers["cache-control"] == "no-store"
    b, bh, bu = setup_client(services, "teacher", "b@example.com")
    assert b.get(f"/api/private/{id}/original").status_code == 404
    assert (
        c.request(
            "DELETE",
            "/api/privacy/account",
            json={"confirm": True, "password": "wrong"},
            headers=h,
        ).status_code
        == 403
    )
    # httpx's delete convenience method has no json; use request.
    assert (
        c.request(
            "DELETE",
            "/api/privacy/account",
            json={"confirm": True, "password": "Strong-password-1"},
            headers=h,
        ).status_code
        == 200
    )
    assert (
        not services.store.path("private/" + id).exists()
        and services.db.one("SELECT * FROM users WHERE id=?", (u["id"],)) is None
    )


def test_connection_explicit_mock_not_generation_no_key_leak(services):
    c, h, u = setup_client(services, "owner")
    calls = []

    def transport(req):
        calls.append((req.method, str(req.url)))
        assert req.headers["authorization"] == "Bearer private-provider-key"
        return httpx.Response(200, json={"data": [{"id": "known"}]})

    services.connection_transport = httpx.MockTransport(transport)
    config = uid("cfg")
    services.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            config,
            "agent",
            js({"base_url": "https://example.org/v1", "model": "known"}),
            services.vault.encrypt("private-provider-key"),
            time.time(),
        ),
    )
    services.db.execute("INSERT INTO active_models VALUES(?,?)", ("agent", config))
    assert (
        c.post("/api/owner/models/agent/test", json={}, headers=h).status_code == 422
        and calls == []
    )
    response = c.post("/api/owner/models/agent/test", json={"confirm": True}, headers=h)
    assert response.status_code == 200 and response.json()["model_advertised"] is True
    assert calls == [("GET", "https://example.org/v1/models")]
    assert (
        "private-provider-key"
        not in response.text
        + c.get("/api/owner/audit").text
        + c.get("/api/owner/models").text
    )
    assert services.db.rows("SELECT * FROM model_usage") == []


def test_migrations_concurrent_startup(tmp_path):
    path = tmp_path / "fresh.sqlite3"
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: DB(path), range(4)))
    assert len(DB(path).rows("SELECT * FROM migrations")) == 6


@pytest.mark.parametrize(
    "kind",
    [
        "lesson_plan",
        "exercise_set",
        "exam",
        "grading",
        "reference_review",
    ],
)
def test_all_teacher_material_modes_same_engine(services, kind):
    u, chat = chat_and_config(services)
    services.db.execute("UPDATE users SET role='teacher' WHERE id=?", (u["id"],))
    u = services.db.one("SELECT * FROM users WHERE id=?", (u["id"],))
    engine = AgentEngine(services)
    run = engine.enqueue(chat, u, "Draft")
    engine.claim()
    tools = Tools(services, u, chat, run)
    material = {
        "kind": kind,
        "title": kind,
        "answer": {"blocks": [{"type": "text", "text": "Generated educational draft"}]},
        "rubric": [
            {
                "title": "criterion",
                "maximum": 2,
                "awarded": 1 if kind == "grading" else None,
            }
        ],
        "total": 2,
        "solution": "Separate generated solution",
    }
    saved = tools.execute("save_teaching_material", material)
    payload = Learning(services).materials(u, saved["id"])["payload"]
    assert (
        payload["official"] is False
        and payload["review_status"] == "draft"
        and payload["kind"] == kind
    )


def test_file_cache_metrics_not_provider_cache(services):
    cache = services.library_cache
    services.store.write("test.txt", b"full content")
    assert cache.read("test.txt", services.store) == "full content"
    assert cache.read("test.txt", services.store) == "full content"
    metrics = cache.metrics()
    assert (
        metrics["hits"] == 1
        and metrics["misses"] == 1
        and "not provider" in metrics["scope"]
    )
    cache.clear()
    assert cache.metrics()["entries"] == 0


def test_account_erasure_completed_run_notes_materials_and_files(services):
    u, chat = chat_and_config(services)
    engine = AgentEngine(services)
    run = engine.enqueue(chat, u, "Test")
    engine.claim()
    learn = Learning(services)
    learn.propose(u, run, {"category": "goal", "content": "Pending"})
    services.db.execute(
        "INSERT INTO teaching_materials VALUES(?,?,?,?,?,?,?,?)",
        (
            "legacy",
            u["id"],
            run,
            "self_practice",
            "Legacy",
            "{}",
            time.time(),
            time.time(),
        ),
    )
    PrivateFiles(services).add(u, chat, "x.txt", b"private")
    services.db.execute("UPDATE agent_runs SET status='COMPLETED' WHERE id=?", (run,))
    c = TestClient(create_app(services))
    h = login(c, "student@example.com")
    r = c.request(
        "DELETE",
        "/api/privacy/account",
        json={"confirm": True, "password": "Strong-password-1"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert (
        services.db.rows("SELECT * FROM agent_runs") == []
        and services.db.rows("SELECT * FROM learning_notes") == []
        and services.db.rows("SELECT * FROM teaching_materials") == []
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, 100])
async def test_budget_checked_before_each_actual_provider_call(services, limit):
    u, chat = chat_and_config(services)
    services.db.execute("UPDATE users SET daily_tokens=? WHERE id=?", (limit, u["id"]))

    class UnknownUsage:
        calls = 0

        async def stream(self, messages, definitions):
            self.calls += 1
            yield {
                "type": "result",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "one",
                            "type": "function",
                            "function": {
                                "name": "list_private_uploads",
                                "arguments": "{}",
                            },
                        }
                    ],
                },
            }

    provider = UnknownUsage()
    services.chat_factory = lambda cfg, key: provider
    engine = AgentEngine(services)
    run = engine.enqueue(chat, u, "Question")
    await engine.process(engine.claim())
    row = services.db.one("SELECT * FROM agent_runs WHERE id=?", (run,))
    assert row["status"] == "FAILED"
    assert provider.calls == (0 if limit == 0 else 1)
    assert row["error"] == (
        "TOKEN_ALLOWANCE_REACHED" if limit == 0 else "TOKEN_BUDGET_USAGE_UNKNOWN"
    )


def test_export_budget_counts_utf8_bytes_not_only_characters(services, monkeypatch):
    u, chat = chat_and_config(services)
    learn = Learning(services)
    monkeypatch.setattr(
        learn, "materials", lambda user: [{"content": "🙂" * 2_500_001}]
    )
    with pytest.raises(HTTPException) as exc:
        learn.export(u)
    assert exc.value.status_code == 413
