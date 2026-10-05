"""Immutable onboarding, server-enforced publication scope and linked uploads."""

import json, sqlite3, time
from concurrent.futures import ThreadPoolExecutor
import pymupdf
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.core.auth import create_user
from bac.core.db import uid
from bac.core.study import StudyScope, catalogue, select_track
from bac.library.contracts import DocumentMetadata
from bac.agent.tools import Tools
from bac.agent.engine import AgentEngine
from bac.agent.full_index import build_catalog
from tests.test_library import seeded, process_and_publish
from tests.test_agent import chat_and_config


def student_client(s):
    id = create_user(
        s.db, uid("user") + "@test.invalid", "Strong-password-1", "Student"
    )
    u = s.db.one("SELECT * FROM users WHERE id=?", (id,))
    c = TestClient(create_app(s))
    r = c.post(
        "/api/auth/login", json={"email": u["email"], "password": "Strong-password-1"}
    )
    return c, {"X-CSRF-Token": r.json()["csrf"]}, u


def test_first_login_requires_track_and_never_infers_legacy_preferences(services):
    c, h, u = student_client(services)
    services.db.execute(
        "UPDATE users SET preferences=? WHERE id=?",
        (json.dumps({"track": "science"}), u["id"]),
    )
    assert c.get("/api/auth/me").json()["user"]["study_track"] is None
    assert (
        c.post("/api/conversations", json={"subject": "physics"}, headers=h).status_code
        == 409
    )
    assert (
        c.put("/api/auth/study-track", json={"value": "fake"}, headers=h).status_code
        == 422
    )
    assert (
        c.put(
            "/api/auth/study-track", json={"value": "experimental_sciences"}, headers=h
        ).status_code
        == 200
    )
    assert (
        c.put(
            "/api/auth/study-track", json={"value": "experimental_sciences"}, headers=h
        ).status_code
        == 200
    )
    assert (
        c.put(
            "/api/auth/study-track", json={"value": "mathematics"}, headers=h
        ).status_code
        == 409
    )
    with pytest.raises(sqlite3.IntegrityError):
        services.db.execute("UPDATE users SET study_track=NULL WHERE id=?", (u["id"],))
    assert c.post("/api/conversations", json={}, headers=h).status_code == 422
    assert (
        c.post(
            "/api/conversations", json={"subject": "accounting"}, headers=h
        ).status_code
        == 422
    )
    assert (
        c.post("/api/conversations", json={"subject": "physics"}, headers=h).status_code
        == 200
    )


def test_subject_change_after_any_message_opens_new_chat_preserving_old(services):
    c, h, u = student_client(services)
    select_track(services.db, u, "experimental_sciences")
    old = c.post("/api/conversations", json={"subject": "physics"}, headers=h).json()[
        "id"
    ]
    assert (
        c.put(
            f"/api/conversations/{old}/subject",
            json={"value": "mathematics"},
            headers=h,
        ).json()["id"]
        == old
    )
    services.db.execute(
        "INSERT INTO messages(id,conversation_id,role,content,active,created_at) VALUES(?,?,'user',?,0,?)",
        (uid("m"), old, "old inactive question", time.time()),
    )
    new = c.put(
        f"/api/conversations/{old}/subject", json={"value": "physics"}, headers=h
    ).json()
    assert new["created_new"] and new["id"] != old
    assert c.get(f"/api/conversations/{old}").json()["study_subject"] == "mathematics"
    assert c.get(f"/api/conversations/{new['id']}").json()["messages"] == []
    assert not services.db.rows(
        "SELECT * FROM loaded_context WHERE conversation_id=?", (new["id"],)
    )
    with pytest.raises(sqlite3.IntegrityError):
        services.db.execute(
            "UPDATE conversations SET study_subject='physics' WHERE id=?", (old,)
        )
    assert (
        c.put(
            f"/api/conversations/{old}/subject",
            json={"value": "mathematics"},
            headers=h,
        ).json()["created_new"]
        is False
    )
    # Pre-migration conversation: don't attach a subject to old history.
    legacy = uid("chat")
    services.db.execute(
        "INSERT INTO conversations(id,user_id,title,created_at,updated_at) VALUES(?,?,?,?,?)",
        (legacy, u["id"], "Legacy", time.time(), time.time()),
    )
    services.db.execute(
        "INSERT INTO messages(id,conversation_id,role,content,created_at) VALUES(?,?,'user',?,?)",
        (uid("m"), legacy, "legacy", time.time()),
    )
    assert c.put(
        f"/api/conversations/{legacy}/subject", json={"value": "physics"}, headers=h
    ).json()["created_new"]
    assert c.get(f"/api/conversations/{legacy}").json()["study_subject"] is None


def test_track_first_choice_race_has_only_one_winner(services):
    _, _, u = student_client(services)

    def pick(t):
        try:
            return select_track(services.db, u, t)["study_track"]
        except HTTPException as e:
            return e.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        result = list(pool.map(pick, ["mathematics", "experimental_sciences"]))
    assert result.count(409) == 1


@pytest.mark.asyncio
async def test_scope_blocks_foreign_search_catalog_nodes_parts_assets_and_restored_context(
    services,
):
    lib, r, owner = seeded(services)
    d = await process_and_publish(services, lib, r, owner)
    permitted = lib.nodes(d["id"], "lesson")[0]["id"]
    foreign = []
    for track, subject in [
        ("experimental_sciences", "mathematics"),
        ("mathematics", "physics"),
    ]:
        upload = lib.upload(
            services.store.path("test.pdf"),
            "foreign.pdf",
            {
                "title": "FOREIGN_SECRET",
                "kind": "book",
                "subject": subject,
                "track": track,
            },
            owner,
        )
        other = await process_and_publish(services, lib, upload, owner)
        n = lib.nodes(other["id"], "lesson")[0]["id"]
        foreign.append(
            (other, n, lib.parts(n)[0]["id"], lib.node(n)["assets"][0]["id"])
        )
    u, chat = chat_and_config(services)
    tools = Tools(services, u, chat, "test")
    scope = tools.study_scope
    index, mapping = build_catalog(services, study_scope=scope)
    assert permitted in {n["id"] for n in mapping.values()}
    assert "FOREIGN_SECRET" not in index
    assert len(tools.library.list_documents()) == 1
    assert {n["document_id"] for n in tools.library.search("الحرارة")} == {d["id"]}
    assert not tools.library.search("الحرارة", {"subject": "mathematics"})
    assert tools.library.search("الحرارة", {"subject": "فيزياء", "track": "science"})
    for other, n, part, asset in foreign:
        for fn in [
            lambda: tools.library.get_doc(other["id"], True),
            lambda: tools.library.node(n),
            lambda: tools.library.parts(n),
            lambda: tools.library.part(part),
            lambda: tools.library.asset(asset),
            lambda: tools.library.source_page(other["id"], 1),
        ]:
            with pytest.raises(HTTPException) as e:
                fn()
            assert e.value.status_code == 404
        payload = lib.node(n)
        with pytest.raises(HTTPException):
            tools.remember(payload)
        assert not tools.sources
        services.db.execute(
            "INSERT INTO loaded_context(conversation_id,node_id,version_id,loaded_at) VALUES(?,?,?,?)",
            (chat, n, other["published_version"], time.time()),
        )
    context = AgentEngine(services).context({"conversation_id": chat}, tools, u)
    assert "FOREIGN_SECRET" not in json.dumps(context, ensure_ascii=False)
    assert not tools.sources


def pdf(s, name, pages):
    path = s.store.path(name)
    with pymupdf.open() as d:
        for i in range(pages):
            d.new_page().insert_text((30, 30), name + " " + str(i))
        d.save(path)
    return path


@pytest.mark.parametrize("layout", ["combined", "separate"])
def test_paired_upload_links_one_version_without_claiming_official_solution(
    services, layout
):
    lib, _, owner = seeded(services)
    primary = pdf(services, "statement.pdf", 4)
    answer = pdf(services, "answer.pdf", 2) if layout == "separate" else None
    pack = {"layout": layout, "matching_confirmed": True}
    if layout == "combined":
        pack.update(
            primary_range={"first_page": 1, "last_page": 2},
            solution_range={"first_page": 3, "last_page": 4},
        )
    meta = {
        "title": "Exam",
        "kind": "exam",
        "content_type": "bac_exams",
        "subject": "physics",
        "track": "experimental_sciences",
        "year": "2025",
    }
    result = lib.upload_package(
        primary,
        "statement.pdf",
        meta,
        owner,
        pack,
        answer,
        "answer.pdf" if answer else None,
    )
    v = lib.version(result["version_id"])
    assert result["solution_linked"] and result["solution_status"] == "pending"
    assert len(v["files"]) == 2 and {f["role"] for f in v["files"]} == {
        "primary",
        "solution",
    }
    sol = next(f for f in v["files"] if f["role"] == "solution")
    assert (
        sol["metadata"]["designation"] == "provided"
        and sol["metadata"]["subject"] == "physics"
    )
    assert sol["verification"] == "pending"
    assert (
        v["status"] == "UPLOADED"
        and not lib.get_doc(result["document_id"])["published_version"]
    )


def test_paired_preflight_and_failure_rollback_preserve_old_versions(
    services, monkeypatch
):
    lib, r, owner = seeded(services)
    primary = pdf(services, "p.pdf", 2)
    answer = pdf(services, "a.pdf", 1)
    meta = {"kind": "exam", "subject": "physics", "track": "experimental_sciences"}
    before = services.db.rows("SELECT id FROM versions")
    for pack, sol in [
        ({"layout": "separate", "matching_confirmed": True}, None),
        ({"layout": "combined", "matching_confirmed": True}, None),
        ({"layout": "separate", "matching_confirmed": False}, answer),
        ({"layout": "separate", "matching_confirmed": True}, primary),
        ({"layout": "none"}, answer),
    ]:
        with pytest.raises(HTTPException):
            lib.upload_package(primary, "p.pdf", meta, owner, pack, sol, "a.pdf")
        assert services.db.rows("SELECT id FROM versions") == before
    bad = services.store.path("bad.pdf")
    bad.write_text("not a PDF")
    with pytest.raises(Exception):
        lib.upload_package(
            primary,
            "p.pdf",
            meta,
            owner,
            {"layout": "separate", "matching_confirmed": True},
            bad,
            "bad.pdf",
        )
    assert services.db.rows("SELECT id FROM versions") == before

    def fail(*a, **k):
        raise RuntimeError("injected failure")

    monkeypatch.setattr(lib, "attach_solution", fail)
    for existing in [None, r["document_id"]]:
        with pytest.raises(RuntimeError):
            lib.upload_package(
                primary,
                "p.pdf",
                meta,
                owner,
                {"layout": "separate", "matching_confirmed": True},
                answer,
                "a.pdf",
                existing,
            )
        assert services.db.rows("SELECT id FROM versions") == before
        assert len(services.db.rows("SELECT id FROM documents")) == 1


@pytest.mark.asyncio
async def test_router_keeps_book_hierarchy_but_only_titles_for_nonbooks(services):
    lib, r, owner = seeded(services)
    await process_and_publish(services, lib, r, owner)
    for category, kind in [
        ("school_tests", "exam"),
        ("exercises", "exercise_collection"),
        ("bac_exams", "exam"),
    ]:
        upload = lib.upload(
            services.store.path("test.pdf"),
            category + ".pdf",
            {
                "title": "FILE_TITLE_" + category,
                "kind": kind,
                "content_type": category,
                "subject": "physics",
                "track": "science",
            },
            owner,
        )
        await process_and_publish(services, lib, upload, owner)
    index, mapping = build_catalog(services)
    assert "الدرس الأول: الحرارة" in index
    for cat in ["school_tests", "exercises", "bac_exams"]:
        assert index.count("FILE_TITLE_" + cat) == 1
        assert "|" + cat + "|" in index
    assert len(mapping) == sum(len(lib.nodes(d["id"])) for d in lib.list_documents())


def test_predefined_metadata_and_preferences_cannot_override_scope(services):
    c, h, u = student_client(services)
    select_track(services.db, u, "experimental_sciences")
    chat = c.post("/api/conversations", json={"subject": "physics"}, headers=h).json()[
        "id"
    ]
    assert (
        c.put("/api/preferences", json={"track": "mathematics"}, headers=h).status_code
        == 409
    )
    assert (
        c.put(
            f"/api/conversations/{chat}/preferences",
            json={"subjects": ["mathematics"]},
            headers=h,
        ).status_code
        == 409
    )
    assert StudyScope(services.db, u, chat).subject == "physics"
    with pytest.raises(ValueError):
        DocumentMetadata(kind="book", subject="made-up", track="science")
    assert len(catalogue()["tracks"]) == 6 and len(catalogue()["content_types"]) == 4
    # Existing preferences cannot mislead teacher prompt scope either.
    services.db.execute(
        "UPDATE users SET preferences=? WHERE id=?",
        (json.dumps({"track": "mathematics", "subjects": ["accounting"]}), u["id"]),
    )
    from bac.learning.service import Learning

    with services.db.tx() as conn:
        pref, _ = Learning(services).snapshot(conn, u["id"], chat)
    assert pref["track"] == "علوم تجريبية" and pref["subjects"] == ["العلوم الفيزيائية"]


def test_multipart_pair_api_and_invalid_second_pdf_leave_no_partial_document(services):
    lib, _, owner = seeded(services)
    from tests.test_api import login

    c = TestClient(create_app(services))
    h = login(c, "owner@example.com")
    primary = pdf(services, "p-api.pdf", 2)
    answer = pdf(services, "a-api.pdf", 1)
    data = {
        "metadata": json.dumps(
            {
                "kind": "exam",
                "content_type": "school_tests",
                "subject": "physics",
                "track": "experimental_sciences",
            }
        ),
        "package": json.dumps({"layout": "separate", "matching_confirmed": True}),
    }
    before = services.db.rows("SELECT id FROM documents")
    r = c.post(
        "/api/owner/documents/upload",
        data=data,
        files={
            "file": ("p.pdf", primary.read_bytes(), "application/pdf"),
            "solution_file": ("bad.pdf", b"not a pdf", "application/pdf"),
        },
        headers=h,
    )
    assert (
        r.status_code == 422 and services.db.rows("SELECT id FROM documents") == before
    )
    r = c.post(
        "/api/owner/documents/upload",
        data=data,
        files={
            "file": ("p.pdf", primary.read_bytes(), "application/pdf"),
            "solution_file": ("a.pdf", answer.read_bytes(), "application/pdf"),
        },
        headers=h,
    )
    assert r.status_code == 200 and r.json()["solution_linked"]
    assert len(lib.version(r.json()["version_id"])["files"]) == 2
    assert not list(services.store.path("incoming").iterdir())
