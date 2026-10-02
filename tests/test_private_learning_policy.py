"""Current product policy: sources private, quiet UI, agent-owned notes."""

import time
import pytest
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.agent.tools import Tools
from bac.agent.engine import AgentEngine
from bac.core.db import uid, js
from tests.test_library import seeded, process_and_publish
from tests.test_agent import chat_and_config
from tests.test_learning import setup_client


@pytest.mark.asyncio
async def test_source_routes_hidden_even_with_known_ids_teacher_or_student(services):
    lib, r, owner = seeded(services)
    doc = await process_and_publish(services, lib, r, owner)
    node = lib.nodes(doc["id"], "lesson")[0]["id"]
    asset = lib.node(node)["assets"][0]["id"]
    paths = [
        "/api/library/documents",
        f"/api/library/documents/{doc['id']}",
        f"/api/library/documents/{doc['id']}/toc",
        f"/api/library/documents/{doc['id']}/page/1",
        f"/api/library/documents/{doc['id']}/page/1/json",
        f"/api/library/nodes/{node}",
        f"/api/library/nodes/{node}/parts",
        f"/api/library/nodes/{node}/bundle",
        f"/api/library/lessons/{node}",
        f"/api/library/assets/{asset}",
        f"/api/library/assets/{asset}/metadata",
        "/api/library/search?q=الحرارة",
        "/api/library/parts/known",
        "/api/agent/capabilities",
        "/api/agent/books",
        "/api/agent/search?q=الحرارة",
        f"/api/agent/nodes/{node}",
        f"/api/agent/assets/{asset}",
    ]
    for role in ["student", "teacher"]:
        c, h, user = setup_client(services, email=role + "@private.invalid", role=role)
        for path in paths:
            res = c.get(path)
            assert res.status_code == 404, (role, path, res.text)
            assert doc["id"] not in res.text and node not in res.text
    # The authenticated worker can still privately read and understand the same source.
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    payload = tools.execute("get_lesson_full", {"node_id": node})
    assert payload["sources"]
    tools.execute("inspect_source_image", {"asset_id": asset})
    assert tools.pending_source[1].startswith(b"\xff\xd8")
    with pytest.raises(ValueError, match="private"):
        tools.answer({"blocks": [{"type": "image", "asset_id": asset}]})
    c, h, user = setup_client(services, email="owner2@private.invalid", role="owner")
    assert c.get(f"/api/library/nodes/{node}").status_code == 200
    assert (
        c.post(
            "/api/owner/service-tokens",
            json={"label": "retired", "documents": [doc["id"]]},
            headers=h,
        ).status_code
        == 403
    )
    assert (
        c.get(
            "/api/agent/books", headers={"Authorization": "Bearer mbac_legacy"}
        ).status_code
        == 403
    )


def test_notes_http_read_only_agent_writes_are_owned_and_live(services):
    user, chat = chat_and_config(services)
    e = AgentEngine(services)
    rid = e.enqueue(chat, user, "أحتاج فهم الوحدات")
    e.claim()
    tools = Tools(services, user, chat, rid)
    n = tools.execute(
        "write_learning_note",
        {"category": "weakness", "content": "يحتاج تبسيط تحويل الوحدات."},
    )
    assert (
        services.db.one("SELECT origin FROM learning_notes WHERE id=?", (n["id"],))[
            "origin"
        ]
        == "agent"
    )
    assert tools.execute("list_my_notes", {})["items"][0]["id"] == n["id"]
    from tests.test_api import login

    c = TestClient(create_app(services))
    h = login(c, "student@example.com")
    assert c.get("/api/notes").json()["read_only"] is True
    assert len(c.get("/api/notes").json()["items"]) == 1
    data = {"category": "mastered", "content": "أنا أتقن كل شيء", "consent": True}
    assert c.post("/api/notes", json=data, headers=h).status_code == 403
    assert c.put("/api/notes/" + n["id"], json=data, headers=h).status_code == 403
    assert c.delete("/api/notes/" + n["id"], headers=h).status_code == 403
    tools.execute(
        "write_learning_note",
        {"id": n["id"], "category": "goal", "content": "تدرّج في تحويل الوحدات."},
    )
    other, h2, u2 = setup_client(services, email="other@private.invalid")
    assert other.get("/api/notes").json()["items"] == []
    with pytest.raises(ValueError):
        Tools(services, u2, chat, rid).execute(
            "write_learning_note",
            {"id": n["id"], "category": "goal", "content": "forged"},
        )
    tools.execute("delete_learning_note", {"id": n["id"]})
    assert not c.get("/api/notes").json()["items"]
    services.db.execute("UPDATE agent_runs SET status='COMPLETED' WHERE id=?", (rid,))
    with pytest.raises(ValueError):
        tools.execute(
            "write_learning_note", {"category": "goal", "content": "stale run"}
        )


def test_legacy_chat_replay_exports_and_results_do_not_leak_sources_or_traces(services):
    c, h, user = setup_client(services)
    chat = c.post("/api/conversations", json={}, headers=h).json()["id"]
    # Seed an old-style answer to check upgrades, not just new rendering.
    legacy = {
        "blocks": [
            {
                "type": "text",
                "text": "شرح عام. get_section /api/library/nodes/node_" + "a" * 32,
            },
            {"type": "image", "asset_id": "asset_" + "b" * 32},
            {"type": "equation", "latex": "x=1", "result_ids": ["science_" + "c" * 32]},
            {
                "type": "verification",
                "result_id": "science_" + "c" * 32,
                "result": {"tool": "calculate", "inputs": {}},
            },
        ],
        "sources": [{"node_id": "node_" + "a" * 32, "title": "SECRET FILE TITLE"}],
    }
    msg = uid("msg")
    services.db.execute(
        "INSERT INTO messages(id,conversation_id,role,content,blocks,sources,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            msg,
            chat,
            "assistant",
            legacy["blocks"][0]["text"],
            js(legacy["blocks"]),
            js(legacy["sources"]),
            time.time(),
        ),
    )
    cfg = uid("cfg")
    services.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (cfg, "agent", "{}", services.vault.encrypt("fake"), time.time()),
    )
    umsg = uid("msg")
    services.db.execute(
        "INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,?,?,?)",
        (umsg, chat, "user", "hello", time.time()),
    )
    rid = uid("run")
    services.db.execute(
        "INSERT INTO agent_runs(id,conversation_id,user_id,message_id,config_id,status,created_at) VALUES(?,?,?,?,?,'COMPLETED',?)",
        (rid, chat, user["id"], umsg, cfg, time.time()),
    )
    for kind, p in [
        ("tool_start", {"name": "get_section", "label": "SECRET TRACE"}),
        ("delta", {"text": "SECRET FILE TITLE"}),
        ("answer", legacy),
        ("error", {"code": "STEP_BUDGET_EXCEEDED", "step_limit": 8}),
    ]:
        services.db.event(rid, kind, p)
    paths = [
        f"/api/conversations/{chat}",
        f"/api/conversations/{chat}/export",
        "/api/privacy/export",
        f"/api/runs/{rid}/events",
    ]
    for path in paths:
        response = c.get(path)
        assert response.status_code == 200
        for private in [
            "SECRET FILE TITLE",
            "SECRET TRACE",
            "get_section",
            "asset_" + "b" * 32,
            "science_" + "c" * 32,
            "node_" + "a" * 32,
            "STEP_BUDGET_EXCEEDED",
            "tool_start",
            "tool_calls",
        ]:
            assert private not in response.text, (path, private)
    run = c.get("/api/runs/" + rid).json()
    assert "steps" not in run and "tool_calls" not in run and "error" not in run
    assert c.get("/api/science/results/known").status_code == 404
    assert c.get("/api/openapi.json").status_code == 404
    assert "tool_calls" not in c.get("/api/usage").text


def test_self_practice_removed_from_schema_tools_and_student_storage(services):
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    defs = js(tools.definitions())
    assert "save_practice_test" not in defs and "self_practice" not in defs
    assert "propose_note" not in defs and "write_learning_note" in defs
    with pytest.raises(ValueError):
        tools.execute("save_practice_test", {})
    from bac.learning.contracts import Material

    with pytest.raises(ValueError):
        Material.model_validate(
            {
                "kind": "self_practice",
                "title": "Old",
                "answer": {"blocks": [{"type": "text", "text": "test"}]},
            }
        )


def test_long_exact_private_passages_are_blocked_across_blocks(services):
    from bac.core.presentation import SourceTextGuard

    private = " ".join(f"كلمة{i}" for i in range(65))
    guard = SourceTextGuard()
    guard.remember(private)
    assert guard.copied(private.replace(" ", "،\n"))
    assert not guard.copied("تعريف قصير ثم شرح جديد بمعطيات مختلفة")
    assert not guard.copied(" ".join(private.split()[:20]))
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    tools.source_text_guard.remember(private)
    words = private.split()
    with pytest.raises(ValueError, match="own words"):
        tools.answer(
            {
                "blocks": [
                    {"type": "text", "text": " ".join(words[:32])},
                    {"type": "text", "text": " ".join(words[32:])},
                ]
            }
        )
    with pytest.raises(ValueError, match="own words"):
        tools.answer(
            {"blocks": [{"type": "text", "text": "شرح"}], "warnings": [private]}
        )
    with pytest.raises(ValueError, match="tool names"):
        tools.answer(
            {"blocks": [{"type": "text", "text": "شرح"}], "warnings": ["get_section"]}
        )
    answer, _ = tools.answer(
        {"blocks": [{"type": "text", "text": "شرح الفكرة بأسلوب جديد"}]}
    )
    assert answer.blocks[0].text == "شرح الفكرة بأسلوب جديد"


def test_upgrade_retires_source_tokens_and_practice_without_erasing_other_data(
    tmp_path,
):
    import sqlite3
    from pathlib import Path
    from bac.core.db import DB

    root = Path(__file__).resolve().parents[1]
    database = tmp_path / "legacy.sqlite3"
    c = sqlite3.connect(database)
    c.execute("PRAGMA foreign_keys=ON")
    c.execute(
        "CREATE TABLE migrations(version INTEGER PRIMARY KEY,applied_at REAL NOT NULL)"
    )
    for script in sorted((root / "migrations").glob("00[1-5]_*.sql")):
        c.executescript(script.read_text())
        c.execute(
            "INSERT INTO migrations VALUES(?,?)", (int(script.name[:3]), time.time())
        )
    c.execute(
        "INSERT INTO users(id,email,password_hash,name,role,created_at) VALUES(?,?,?,?,?,?)",
        (
            "legacy",
            "legacy@test.invalid",
            "not-a-login-hash",
            "Legacy",
            "owner",
            time.time(),
        ),
    )
    c.execute(
        "INSERT INTO learning_notes VALUES(?,?,?,?,?,?,?,?)",
        (
            "note",
            "legacy",
            "goal",
            "Old manually edited note",
            "approved",
            None,
            time.time(),
            time.time(),
        ),
    )
    for kind in ["self_practice", "lesson_plan"]:
        c.execute(
            "INSERT INTO teaching_materials VALUES(?,?,?,?,?,?,?,?)",
            (
                kind,
                "legacy",
                None,
                kind,
                "Old material",
                "{}",
                time.time(),
                time.time(),
            ),
        )
    c.execute(
        "INSERT INTO service_tokens VALUES(?,?,?,?,?,?,?,?,?)",
        (
            "token",
            "Retired",
            "not-a-real-token-hash",
            "legacy",
            "[]",
            time.time() + 1000,
            None,
            None,
            time.time(),
        ),
    )
    c.commit()
    c.close()
    db = DB(database)
    db.migrate()  # Idempotent, including API/worker restart.
    assert db.one("SELECT * FROM learning_notes")["origin"] == "legacy_user"
    assert [r["kind"] for r in db.rows("SELECT * FROM teaching_materials")] == [
        "lesson_plan"
    ]
    assert db.one("SELECT * FROM service_tokens")["revoked_at"] is not None
    assert db.one("SELECT * FROM users")["name"] == "Legacy"
    assert len(db.rows("SELECT * FROM migrations")) == 6


def test_all_internal_tool_identifiers_are_hidden_but_ordinary_english_is_kept():
    from bac.core.presentation import text, INTERNAL

    for name in [
        "draw_diagram",
        "plot_from_result",
        "list_lesson_parts",
        "read_private_page",
        "get_exam_with_solution",
        "symbolic_math",
        "delete_learning_note",
    ]:
        assert INTERNAL.search(name)
        assert name not in text("Internal " + name)
    assert INTERNAL.search("tool calculate")
    assert (
        text("We calculate speed from distance and time.")
        == "We calculate speed from distance and time."
    )
