"""Offline contract/integration tests. No remote provider or paid calls."""

import hashlib, json, time
from dataclasses import replace
from pathlib import Path
import pymupdf as fitz
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.core.auth import create_user
from bac.core.db import DB, uid, js
from bac.agent.tools import Tools
from bac.agent.engine import AgentEngine
from bac.library.service import Library
from bac.library.parts import element_groups, legacy_blocks
from bac.vendor.bookforge.models.page import PageDocument
from tests.test_api import login
from tests.test_agent import chat_and_config
from tests.test_library import seeded, process_and_publish

META = {
    "title": "امتحان تجريبي",
    "kind": "exam",
    "subject": "physics",
    "track": "science",
    "year": "2025",
    "session": "June",
    "exam_type": "BAC",
    "source": "Synthetic test, not official",
}
SOL = {
    k: v
    for k, v in META.items()
    if k in ("subject", "track", "year", "session", "exam_type", "source")
} | {"designation": "provided"}
VERIFY = {
    "matching_confirmed": True,
    "source_confirmed": True,
    "evidence": "All problem statements, identities and solution numbering compared manually in this synthetic test.",
}


def pdf(s, name="exam.pdf", pages=2):
    path = s.store.path(name)
    with fitz.open() as d:
        for i in range(pages):
            d.new_page().insert_text((30, 30), f"{name} page {i + 1}")
        d.save(path)
    return path


class BundleVision:
    async def extract(self, image, page, width, height):
        return PageDocument(
            pdf_page=page,
            width=width,
            height=height,
            languages=["en", "ar"],
            printed_page=str(page + 10),
            elements=[
                {
                    "id": "heading",
                    "type": "heading",
                    "order": 0,
                    "text": f"Exercise {page}",
                    "structure_type": "lesson",
                },
                {
                    "id": "text",
                    "type": "paragraph",
                    "order": 1,
                    "text": f"Exact source page {page}. لا تلخّص.",
                },
                {
                    "id": "fig",
                    "type": "figure",
                    "order": 2,
                    "bbox": [5, 5, 100, 100],
                    "caption": f"Original figure {page}",
                },
                {
                    "id": "table",
                    "type": "table",
                    "order": 3,
                    "bbox": [5, 100, 150, 200],
                    "headers": ["Quantity", "Value"],
                    "rows": [["T", "25 °C"]],
                },
                {"id": "eq", "type": "equation", "order": 4, "latex": "PV=nRT"},
            ],
        ), {}


async def extract(s, lib, r, owner, vision=None):
    cid = uid("cfg")
    s.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            cid,
            "extraction",
            js({"base_url": "https://example.org/v1", "model": "offline-fixture"}),
            s.vault.encrypt("offline-key"),
            time.time(),
        ),
    )
    s.db.execute(
        "INSERT OR REPLACE INTO active_models VALUES(?,?)", ("extraction", cid)
    )
    s.extraction_engine.provider_factory = lambda cfg, key: vision or BundleVision()
    lib.process(r["version_id"], owner)
    while job := s.extraction_queue.claim():
        await s.extraction_engine.process(job)


def owner(s):
    return create_user(s.db, "owner@example.com", "Strong-password-1", "Owner", "owner")


@pytest.mark.asyncio
async def test_exam_exact_atomic_bundle_matching_and_frozen_files(services):
    s = services
    u = owner(s)
    lib = Library(s)
    r = lib.upload(pdf(s), "exam.pdf", META, u)
    lib.attach_solution(r["version_id"], SOL, u, pdf(s, "solution.pdf"), "solution.pdf")
    await extract(s, lib, r, u)
    with pytest.raises(HTTPException):
        lib.review(r["version_id"], u, True, "Not verified")
    lib.verify_solution(r["version_id"], VERIFY, u)
    lib.review(r["version_id"], u, True, "Reviewed")
    d = lib.publish(r["version_id"], u)
    nodes = lib.nodes(d["id"])
    assert len(nodes) == 1 and nodes[0]["kind"] == "exam"
    b = lib.bundle(nodes[0]["id"])
    assert (
        b["solution_status"] == "owner_verified"
        and "Exact source page 2" in b["solution"]["content"]
    )
    assert len(b["sources"]) == 2 and len({x["file_id"] for x in b["sources"]}) == 2
    assert len(b["assets"]) == 8 and len({x["id"] for x in b["assets"]}) == 8
    for f in lib.version(r["version_id"])["files"]:
        frozen = s.db.one("SELECT * FROM published_files WHERE id=?", (f["id"],))
        assert (
            hashlib.sha256(s.store.read(frozen["source_pdf"])).hexdigest()
            == f["sha256"]
        )
        p = lib.source_page(d["id"], 1, f["id"], "json")
        assert (
            p["json"]["elements"][-1]["latex"] == "PV=nRT"
            and p["page"]["printed_page"] == "11"
        )
    assert lib.node(nodes[0]["id"])["tables"][0]["metadata"]["rows"] == [["T", "25 °C"]]
    user, chat = chat_and_config(s)
    t = Tools(s, user, chat)
    assert (
        t.execute("get_section", {"node_id": nodes[0]["id"]})["error"]
        == "ATOMIC_BUNDLE_REQUIRED"
    )
    result = t.execute("get_exam_with_solution", {"node_id": nodes[0]["id"]})
    assert len(t.sources) == 2 and result["solution"]
    t.answer(
        {
            "blocks": [{"type": "text", "text": "from source"}],
            "source_ids": [x["source_id"] for x in result["sources"]],
        }
    )
    # Reprocessing mutation cannot alter a frozen solution or page JSON.
    raw = s.extraction_db.one(
        "SELECT artifact_dir FROM pages WHERE book_id=? AND pdf_page=1",
        (lib.version(r["version_id"])["files"][1]["bookforge_id"],),
    )
    s.extraction_store.write(raw["artifact_dir"] + "/page.json", b"{}")
    assert lib.bundle(nodes[0]["id"])["solution"]["content"] == b["solution"]["content"]
    assert lib.source_page(d["id"], 1, b["sources"][1]["file_id"], "json")["json"][
        "elements"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["exam", "exercise_collection", "reference"])
async def test_missing_solution_explicit_no_invented_hierarchy(services, kind):
    s = services
    u = owner(s)
    lib = Library(s)
    r = lib.upload(pdf(s), "source.pdf", META | {"kind": kind}, u)
    await extract(s, lib, r, u)
    lib.review(r["version_id"], u, True, "Reviewed")
    d = lib.publish(r["version_id"], u)
    nodes = lib.nodes(d["id"])
    assert len(nodes) == 1 and nodes[0]["kind"] == kind
    if kind != "reference":
        b = lib.bundle(nodes[0]["id"])
        assert b["solution"] is None and b["solution_status"] == "not_available"
        assert "Exact source page 2" in b["content"]
        with pytest.raises(HTTPException):
            lib.parts(nodes[0]["id"])
    assert not lib.nodes(d["id"], "lesson")


@pytest.mark.asyncio
async def test_combined_pdf_ranges_extract_once_and_identity_invalidation(services):
    s = services
    u = owner(s)
    lib = Library(s)
    r = lib.upload(pdf(s, pages=4), "combined.pdf", META, u)
    v = r["version_id"]
    with pytest.raises(HTTPException):
        lib.attach_solution(v, SOL, u, page_range={"first_page": 3, "last_page": 4})
    lib.set_range(v, v + ":primary", {"first_page": 1, "last_page": 2}, u)
    lib.attach_solution(v, SOL, u, page_range={"first_page": 3, "last_page": 4})
    lib.verify_solution(v, VERIFY, u)
    lib.set_range(v, v + ":solution", {"first_page": 4, "last_page": 4}, u)
    assert lib.version(v)["files"][1]["verification"] == "pending"
    lib.set_range(v, v + ":solution", {"first_page": 3, "last_page": 4}, u)
    lib.verify_solution(v, VERIFY, u)
    await extract(s, lib, r, u)
    assert (
        s.extraction_db.one("SELECT count(*) n FROM jobs WHERE kind='page'")["n"] == 4
    )
    lib.review(v, u, True, "Matched")
    d = lib.publish(v, u)
    b = lib.bundle(lib.nodes(d["id"])[0]["id"])
    assert "page 3" not in b["content"] and "page 1." not in b["solution"]["content"]
    assert b["sources"][0]["pages"] == [1, 2] and b["sources"][1]["pages"] == [3, 4]
    with pytest.raises(HTTPException):
        lib.source_page(d["id"], 3, b["sources"][0]["file_id"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("subject", "math"),
        ("track", "other"),
        ("year", "2024"),
        ("session", "other"),
        ("exam_type", "test"),
    ],
)
def test_no_solution_pairing_by_title_or_known_identity_mismatch(
    services, field, value
):
    s = services
    u = owner(s)
    lib = Library(s)
    r = lib.upload(pdf(s), "exam.pdf", META, u)
    lib.attach_solution(
        r["version_id"], SOL | {field: value}, u, pdf(s, "solution.pdf"), "solution.pdf"
    )
    with pytest.raises(HTTPException) as exc:
        lib.verify_solution(r["version_id"], VERIFY, u)
    assert "mismatch" in exc.value.detail


@pytest.mark.asyncio
async def test_new_version_keeps_public_metadata_and_revokes_old_sources_only_on_publish(
    services,
):
    lib, r, u = seeded(services)
    d = await process_and_publish(services, lib, r, u)
    node = lib.nodes(d["id"], "lesson")[0]["id"]
    text = lib.node(node)["content"]
    v = lib.clone(r["version_id"], u)
    lib.update_metadata(
        v["id"], v["metadata"] | {"title": "Draft changed", "subject": "math"}, u
    )
    assert (
        lib.get_doc(d["id"], True)["title"] == d["title"]
        and lib.node(node)["content"] == text
    )
    with pytest.raises(HTTPException):
        lib.update_metadata(r["version_id"], v["metadata"], u)
    lib.review(v["id"], u, True, "Re-reviewed")
    lib.publish(v["id"], u)
    assert lib.get_doc(d["id"], True)["title"] == "Draft changed"
    with pytest.raises(HTTPException):
        lib.node(node)


class LongVision:
    async def extract(self, image, page, width, height):
        return PageDocument(
            pdf_page=page,
            width=width,
            height=height,
            elements=[
                {
                    "id": "h",
                    "type": "heading",
                    "order": 0,
                    "text": "الدرس 1: طويل",
                    "structure_type": "lesson",
                }
            ]
            + [
                {
                    "id": f"p{i}",
                    "type": "paragraph",
                    "order": i + 1,
                    "text": str(i) + " " + ("Exact text. " * 500),
                }
                for i in range(4)
            ]
            + [{"id": "eq", "type": "equation", "order": 6, "latex": "Q=mc\\Delta T"}],
        ), {}


@pytest.mark.asyncio
async def test_long_lesson_lossless_parts_budget_credit_and_context_restore(services):
    s = services
    lib, r, u = seeded(s)
    await extract(s, lib, r, u, LongVision())
    lib.review(r["version_id"], u, True, "Checked")
    d = lib.publish(r["version_id"], u)
    node = lib.nodes(d["id"], "lesson")[0]["id"]
    parts = lib.parts(node)
    assert len(parts) > 1 and all(
        p["metadata"]["boundary"] == "complete_extracted_elements" for p in parts
    )
    rebuilt = "\n".join(lib.part(p["id"])["content"] for p in parts)
    assert (
        all(f"{i} Exact text." in rebuilt for i in range(4))
        and "Q=mc\\Delta T" in rebuilt
    )
    user, chat = chat_and_config(s)
    s.settings = replace(s.settings, max_tool_chars=10000)
    t = Tools(s, user, chat)
    assert t.load(node)["error"] == "SOURCE_EXCEEDS_TOOL_BUDGET" and not t.sources
    assert not s.db.rows("SELECT * FROM loaded_context")
    payload = t.execute("get_lesson_part", {"part_id": parts[0]["id"]})
    assert "error" not in payload and list(t.sources) == [parts[0]["id"]]
    with pytest.raises(ValueError, match="not actually loaded"):
        t.answer({"blocks": [{"type": "text", "text": "x"}], "source_ids": [node]})
    t.answer(
        {"blocks": [{"type": "text", "text": "x"}], "source_ids": [parts[0]["id"]]}
    )
    s.settings = replace(s.settings, max_context_chars=500)
    fresh = Tools(s, user, chat)
    engine = AgentEngine(s)
    engine.context({"conversation_id": chat}, fresh, user)
    assert not fresh.sources


@pytest.mark.asyncio
async def test_metadata_only_does_not_read_files_and_shared_cache(
    services, monkeypatch
):
    lib, r, u = seeded(services)
    d = await process_and_publish(services, lib, r, u)
    node = lib.nodes(d["id"], "lesson")[0]["id"]
    lib.cache.clear()
    real = services.store.read
    calls = []
    monkeypatch.setattr(
        services.store, "read", lambda path: (calls.append(path), real(path))[1]
    )
    lib.node(node, False)
    assert calls == []
    lib.node(node)
    Library(services).node(node)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_atomic_budget_refusal_and_complete_serialized_budget(services):
    s = services
    u = owner(s)
    lib = Library(s)
    r = lib.upload(pdf(s), "exam.pdf", META, u)
    await extract(s, lib, r, u)
    lib.review(r["version_id"], u, True, "Checked")
    d = lib.publish(r["version_id"], u)
    node = lib.nodes(d["id"])[0]["id"]
    user, chat = chat_and_config(s)
    payload = Tools(s, user, chat).load(node, scope="bundle", remember=False)
    assert len(payload["content"]) < len(js(payload))
    s.settings = replace(s.settings, max_tool_chars=len(payload["content"]) + 1)
    t = Tools(s, user, chat)
    result = t.load(node, scope="bundle")
    assert (
        result["error"] == "ATOMIC_BUNDLE_EXCEEDS_TOOL_BUDGET"
        and not t.sources
        and not s.db.rows("SELECT * FROM loaded_context")
    )


@pytest.mark.asyncio
async def test_api_bundle_filters_file_scope_and_owner_only(services):
    s = services
    u = owner(s)
    lib = Library(s)
    r = lib.upload(pdf(s), "exam.pdf", META, u)
    await extract(s, lib, r, u)
    lib.review(r["version_id"], u, True, "Checked")
    d = lib.publish(r["version_id"], u)
    node = lib.nodes(d["id"])[0]["id"]
    create_user(s.db, "a@example.com", "Strong-password-1", "Student")
    c = TestClient(create_app(s))
    h = login(c)
    assert (
        c.get("/api/library/nodes/" + node + "/bundle").json()["solution_status"]
        == "not_available"
    )
    assert (
        c.get("/api/library/documents?kind=exam&year=2025&session=June").json()[
            "items"
        ][0]["id"]
        == d["id"]
    )
    assert not c.get("/api/library/search?q=Exact&kind=book").json()["items"]
    assert (
        c.get(f"/api/library/documents/{d['id']}/page/1?file_id=other").status_code
        == 404
    )
    assert c.get(f"/api/library/documents/{d['id']}/page/1/json").json()["json"][
        "elements"
    ]
    assert (
        c.post(
            "/api/owner/versions/" + r["version_id"] + "/clone", headers=h
        ).status_code
        == 403
    )
    assert (
        c.post(
            "/api/owner/versions/" + r["version_id"] + "/solution/verify",
            json=VERIFY,
            headers=h,
        ).status_code
        == 403
    )
    assert c.get("/api/library/lessons/" + node).status_code == 422


def test_migration_backfills_real_v1_database_without_rewriting_sources(tmp_path):
    path = tmp_path / "v1.sqlite3"
    import sqlite3

    c = sqlite3.connect(path)
    c.executescript(Path("migrations/001_platform.sql").read_text())
    c.execute(
        "CREATE TABLE migrations(version INTEGER PRIMARY KEY,applied_at REAL NOT NULL)"
    )
    c.execute("INSERT INTO migrations VALUES(1,?)", (time.time(),))
    c.execute(
        "INSERT INTO users(id,email,password_hash,name,role,created_at) VALUES('u','a','x','A','owner',0)"
    )
    c.execute(
        "INSERT INTO documents(id,title,kind,subject,track,source,owner_id,created_at) VALUES('d','T','book','physics','science','S','u',0)"
    )
    c.execute(
        "INSERT INTO versions(id,document_id,sequence,bookforge_id,created_at) VALUES('v','d',1,'raw',0)"
    )
    c.commit()
    c.close()
    db = DB(path)
    assert db.one("SELECT * FROM version_files")["id"] == "v:primary"
    assert (
        json.loads(db.one("SELECT metadata FROM versions")["metadata"])["subject"]
        == "physics"
    )
    db.migrate()


def test_block_boundaries_keep_math_fences_and_tables_whole():
    text = "<!-- PDF page 2; source v -->\n\n$$\na\n\nb\n$$\n\n```python\na\n\nb\n```\n\n| X | Y |\n|---|---|\n| 1 | 2 |\n"
    blocks = legacy_blocks(text, 1)
    assert any("a\n\nb" in b and "$$" in b for b, _ in blocks)
    assert any("a\n\nb" in b and "```" in b for b, _ in blocks)
    assert all(p == 2 for _, p in blocks)
    elements = [
        {"markdown": "x" * 9000, "type": "paragraph"},
        {"markdown": "$$a$$", "type": "equation"},
    ]
    assert len(element_groups(elements)) == 2


class SharedPageVision:
    async def extract(self, image, page, width, height):
        return PageDocument(
            pdf_page=page,
            width=width,
            height=height,
            elements=[
                {
                    "id": "h1",
                    "type": "heading",
                    "order": 0,
                    "text": "Lesson 1: Alpha",
                    "structure_type": "lesson",
                },
                {
                    "id": "p1",
                    "type": "paragraph",
                    "order": 1,
                    "text": "First lesson only.",
                },
                {
                    "id": "h2",
                    "type": "heading",
                    "order": 2,
                    "text": "Lesson 2: Beta",
                    "structure_type": "lesson",
                },
                {
                    "id": "p2",
                    "type": "paragraph",
                    "order": 3,
                    "text": "Second lesson only.",
                },
                {"id": "eq", "type": "equation", "order": 4, "latex": "E=mc^2"},
            ],
        ), {}


@pytest.mark.asyncio
async def test_two_lessons_on_same_page_remain_element_scoped(services):
    lib, r, u = seeded(services)
    await extract(services, lib, r, u, SharedPageVision())
    lib.review(r["version_id"], u, True, "Both exact boundaries reviewed")
    d = lib.publish(r["version_id"], u)
    lessons = lib.nodes(d["id"], "lesson")
    assert len(lessons) == 2
    first, second = [lib.node(n["id"]) for n in lessons]
    assert "Second lesson" not in first["content"] and not first["equations"]
    assert (
        "First lesson" not in second["content"]
        and second["equations"][0]["metadata"]["latex"] == "E=mc^2"
    )


@pytest.mark.asyncio
async def test_legacy_parts_read_only_frozen_markdown_and_revoke_with_version(services):
    lib, r, u = seeded(services)
    d = await process_and_publish(services, lib, r, u)
    n = lib.nodes(d["id"], "lesson")[0]["id"]
    before = lib.node(n)["content"]
    services.db.execute("DELETE FROM published_parts WHERE node_id=?", (n,))
    raw = services.extraction_db.one(
        "SELECT content_file FROM nodes WHERE kind='lesson'"
    )
    services.extraction_store.write(raw["content_file"], b"UNAPPROVED MUTATION")
    parts = lib.parts(n)
    assert parts and all(
        p["metadata"]["boundary"] == "approved_markdown_blocks" for p in parts
    )
    content = "\n".join(lib.part(p["id"])["content"] for p in parts)
    assert (
        "UNAPPROVED MUTATION" not in content
        and "الحرارة" in content
        and "Q=mc" in content
        and "الحرارة" in before
    )
    services.db.execute("UPDATE documents SET status='ARCHIVED' WHERE id=?", (d["id"],))
    with pytest.raises(HTTPException):
        lib.part(parts[0]["id"])


@pytest.mark.asyncio
async def test_failed_page_remains_explicit_in_whole_bundle_and_original_preserved(
    services,
):
    s = services
    u = owner(s)
    lib = Library(s)
    r = lib.upload(pdf(s), "exam.pdf", META, u)
    await extract(s, lib, r, u)
    bid = lib.version(r["version_id"])["bookforge_id"]
    s.extraction_db.execute(
        "UPDATE pages SET status='FAILED',artifact_dir=NULL WHERE book_id=? AND pdf_page=2",
        (bid,),
    )
    s.extraction_db.execute(
        "DELETE FROM elements WHERE book_id=? AND ordinal>=2000000", (bid,)
    )
    with pytest.raises(HTTPException):
        lib.review(r["version_id"], u, False, "Not acknowledged")
    lib.review(r["version_id"], u, True, "Missing page explicitly acknowledged")
    d = lib.publish(r["version_id"], u)
    b = lib.bundle(lib.nodes(d["id"])[0]["id"])
    assert (
        b["extraction_complete"] is False
        and "[SOURCE PAGE UNAVAILABLE OR UNREADABLE]" in b["content"]
    )
    assert b["sources"][0]["pages"] == [1, 2]
    assert s.store.path(
        s.db.one("SELECT source_pdf FROM published_files")["source_pdf"]
    ).is_file()


@pytest.mark.asyncio
async def test_owner_approved_preview_never_reads_changed_raw_extraction(services):
    lib, r, u = seeded(services)
    await process_and_publish(services, lib, r, u)
    raw = services.extraction_db.one("SELECT artifact_dir FROM pages")
    services.extraction_store.write(raw["artifact_dir"] + "/page.md", b"UNAPPROVED")
    services.extraction_store.write(raw["artifact_dir"] + "/page.json", b"{}")
    services.extraction_db.execute("UPDATE pages SET status='FAILED'")
    c = TestClient(create_app(services))
    login(c, "owner@example.com")
    res = c.get("/api/owner/versions/" + r["version_id"] + "/page/1").json()
    assert (
        res["immutable_preview"]
        and "UNAPPROVED" not in res["content"]
        and res["json"]["elements"]
    )
    assert lib.version(r["version_id"])["pages"][0]["status"] == "SUCCESS"
