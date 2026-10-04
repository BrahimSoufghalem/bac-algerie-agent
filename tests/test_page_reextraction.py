"""Explicit offline one-page Vision requests; no live credentials or curriculum."""

import json
from dataclasses import replace
import pymupdf
import pytest
from fastapi import HTTPException
from bac.core.db import uid, js
from bac.core.auth import create_user
from bac.library.service import Library
from bac.vendor.bookforge.models.page import PageDocument
from bac.vendor.bookforge.vision.provider import ProviderError
from tests.test_learning import setup_client


def configure(s, name="old", key="PRIVATE-TEST-KEY"):
    cid = uid("cfg")
    cfg = {"base_url": "https://example.org/v1", "model": name}
    s.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (cid, "extraction", js(cfg), s.vault.encrypt(key), 1),
    )
    s.db.execute(
        "INSERT OR REPLACE INTO active_models VALUES(?,?)", ("extraction", cid)
    )
    return cid


class Vision:
    def __init__(self, calls, model="old", key="PRIVATE-TEST-KEY", fail=False):
        self.calls, self.model, self.key, self.fail = calls, model, key, fail

    async def extract(self, image, page, width, height):
        self.calls.append((self.model, self.key, page, image.read_bytes()))
        if self.fail:
            raise ProviderError("HTTP_400", False)
        elements = []
        if page == 1:
            elements.append(
                {
                    "id": "lesson",
                    "type": "heading",
                    "order": 0,
                    "structure_type": "lesson",
                    "text": "الدرس: حركة الاختبار",
                }
            )
        elements.append(
            {
                "id": "text",
                "type": "paragraph",
                "order": len(elements),
                "text": f"{self.model} content page {page}",
            }
        )
        return PageDocument(
            pdf_page=page, width=width, height=height, elements=elements
        ), {"prompt_tokens": 1, "completion_tokens": 1}


async def drain(s):
    while job := s.extraction_queue.claim():
        await s.extraction_engine.process(job)


async def seeded(s, published=True):
    settings = replace(s.extraction_settings, min_request_interval=0)
    s.extraction_engine.settings = settings
    s.extraction_queue.settings = settings
    s.extraction_engine.queue.settings = settings
    owner = create_user(
        s.db,
        "owner-reextract@fixture.invalid",
        "Test-owner-password-123",
        "Owner",
        "owner",
    )
    pdf = s.store.path("manual-pages.pdf")
    with pymupdf.open() as d:
        for i in range(3):
            d.new_page().insert_text((40, 40), f"Controlled page {i + 1}")
        d.save(pdf)
    lib = Library(s)
    uploaded = lib.upload(
        pdf,
        "manual-pages.pdf",
        {
            "title": "Controlled manual pages",
            "kind": "book",
            "subject": "physics",
            "track": "science",
        },
        owner,
    )
    configure(s)
    calls = []
    s.extraction_engine.provider_factory = lambda cfg, key: Vision(
        calls, cfg["model"], key
    )
    lib.process(uploaded["version_id"], owner)
    await drain(s)
    if published:
        lib.review(uploaded["version_id"], owner, True, "Controlled fixture reviewed")
        lib.publish(uploaded["version_id"], owner)
    return lib, uploaded, owner, calls


@pytest.mark.asyncio
async def test_successful_page_fresh_model_only_original_pixels_no_raw_cache_and_frozen_source(
    services,
):
    lib, r, owner, calls = await seeded(services)
    source = lib.version(r["version_id"])
    node = lib.nodes(r["document_id"], "lesson")[0]["id"]
    original_content = lib.node(node)["content"]
    oldpage = services.extraction_db.one(
        "SELECT * FROM pages WHERE book_id=? AND pdf_page=2", (source["bookforge_id"],)
    )
    oldjob = services.extraction_db.one(
        "SELECT * FROM jobs WHERE target_id=? AND kind='page'", (oldpage["id"],)
    )
    assert (
        oldjob["raw_file"]
        and services.extraction_store.path(oldjob["raw_file"]).exists()
    )
    with pytest.raises(HTTPException) as exc:
        lib.reextract_page(r["version_id"], 2, None, owner)
    assert exc.value.status_code == 409
    draft = lib.clone(r["version_id"], owner)
    other = lib.clone(r["version_id"], owner)
    before = services.extraction_db.rows(
        "SELECT * FROM pages WHERE book_id=? AND pdf_page!=2 ORDER BY pdf_page",
        (source["bookforge_id"],),
    )
    cid = configure(services, "new", "PRIVATE-NEW-KEY")
    queued = lib.reextract_page(draft["id"], 2, None, owner)
    assert queued["scheduled"] == 1 and queued["page"] == 2
    newjob = services.extraction_db.one(
        "SELECT * FROM jobs WHERE id=?", (queued["job_id"],)
    )
    assert newjob["raw_file"] is None and newjob["id"] != oldjob["id"]
    assert (
        len(
            services.extraction_db.rows(
                "SELECT * FROM jobs WHERE kind='page' AND status='PENDING'"
            )
        )
        == 1
    )
    pending = services.extraction_db.one(
        "SELECT * FROM pages WHERE id=?", (oldpage["id"],)
    )
    assert pending["artifact_dir"] is None and pending["status"] == "PENDING"
    run = services.extraction_db.one(
        "SELECT * FROM runs WHERE id=?", (queued["run_id"],)
    )
    assert json.loads(run["config_json"])["_platform_config_id"] == cid
    assert (
        services.extraction_engine.vault.decrypt(run["encrypted_key"])
        == "PRIVATE-NEW-KEY"
    )
    configure(services, "later", "PRIVATE-LATER-KEY")
    with pytest.raises(HTTPException) as duplicate:
        lib.reextract_page(draft["id"], 2, None, owner)
    assert duplicate.value.status_code == 409
    assert (
        services.db.one(
            "SELECT edit_revision FROM versions WHERE id=?", (other["id"],)
        )["edit_revision"]
        > 0
    )
    await drain(services)
    assert len(calls) == 4 and calls[-1][:3] == ("new", "PRIVATE-NEW-KEY", 2)
    assert (
        calls[-1][3] == calls[1][3]
    )  # Same original pixels, a fresh provider invocation.
    after = services.extraction_db.rows(
        "SELECT * FROM pages WHERE book_id=? AND pdf_page!=2 ORDER BY pdf_page",
        (source["bookforge_id"],),
    )
    assert after == before
    newpage = services.extraction_db.one(
        "SELECT * FROM pages WHERE id=?", (oldpage["id"],)
    )
    assert newpage["artifact_dir"] != oldpage["artifact_dir"]
    assert (
        "new content page 2"
        in services.extraction_store.read(newpage["artifact_dir"] + "/page.md").decode()
    )
    assert lib.node(node)["content"] == original_content
    assert lib.get_doc(r["document_id"])["published_version"] == r["version_id"]
    frozen = lib.approved_page(
        lib.version(r["version_id"]), source["files"][0]["id"], 2
    )
    assert "old content page 2" in services.store.read(frozen["content_file"]).decode()
    lib.review(draft["id"], owner, True, "Reviewed new page")
    lib.publish(draft["id"], owner)
    newnode = lib.nodes(r["document_id"], "lesson")[0]["id"]
    assert "new content page 2" in lib.node(newnode)["content"]
    assert lib.get_doc(r["document_id"])["published_version"] == draft["id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["SUCCESS", "NEEDS_REVIEW", "FAILED"])
async def test_any_terminal_page_can_be_explicitly_reextracted(services, status):
    lib, r, owner, calls = await seeded(services, published=False)
    bid = lib.version(r["version_id"])["bookforge_id"]
    services.extraction_db.execute(
        "UPDATE pages SET status=? WHERE book_id=? AND pdf_page=2", (status, bid)
    )
    result = lib.reextract_page(r["version_id"], 2, None, owner)
    await drain(services)
    assert result["scheduled"] == 1 and len(calls) == 4
    assert lib.version(r["version_id"])["pages"][1]["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_api_owner_explicit_confirmation_range_and_file_scope_no_implicit_request(
    services,
):
    lib, r, owner, calls = await seeded(services, published=False)
    c, h, _ = setup_client(services, "owner", "second-owner@fixture.invalid")
    endpoint = f"/api/owner/versions/{r['version_id']}/page/2/reextract"
    before = len(services.extraction_db.rows("SELECT * FROM runs"))
    for body in [{}, {"confirm": False}]:
        assert c.post(endpoint, json=body, headers=h).status_code == 422
    assert (
        c.post(
            endpoint, json={"confirm": True, "file_id": "different-file"}, headers=h
        ).status_code
        == 404
    )
    assert (
        c.post(
            endpoint.replace("/page/2/", "/page/99/"), json={"confirm": True}, headers=h
        ).status_code
        == 404
    )
    for role in ["student", "teacher"]:
        other, oh, _ = setup_client(services, role, role + "-manual@fixture.invalid")
        assert (
            other.post(endpoint, json={"confirm": True}, headers=oh).status_code == 403
        )
    assert (
        len(services.extraction_db.rows("SELECT * FROM runs")) == before
        and len(calls) == 3
    )
    assert c.post(endpoint, json={"confirm": True}, headers=h).status_code == 200
    assert c.post(endpoint, json={"confirm": True}, headers=h).status_code == 409
    await drain(services)
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_missing_current_config_and_unprocessed_source_do_not_schedule(services):
    lib, r, owner, calls = await seeded(services, published=False)
    services.db.execute("DELETE FROM active_models WHERE slot='extraction'")
    with pytest.raises(HTTPException) as missing:
        lib.reextract_page(r["version_id"], 2, None, owner)
    assert missing.value.status_code == 409
    configure(services)
    bid = lib.version(r["version_id"])["bookforge_id"]
    services.extraction_db.execute(
        "UPDATE pages SET status='PENDING' WHERE book_id=? AND pdf_page=3", (bid,)
    )
    with pytest.raises(HTTPException) as pending:
        lib.reextract_page(r["version_id"], 2, None, owner)
    assert pending.value.status_code == 409 and len(calls) == 3


@pytest.mark.asyncio
async def test_failed_fresh_extraction_keeps_published_source_and_does_not_show_stale_draft_text(
    services,
):
    lib, r, owner, calls = await seeded(services)
    original = lib.version(r["version_id"])
    draft = lib.clone(r["version_id"], owner)
    services.extraction_engine.provider_factory = lambda cfg, key: Vision(
        calls, cfg["model"], key, True
    )
    lib.reextract_page(draft["id"], 2, None, owner)
    await drain(services)
    p = services.extraction_db.one(
        "SELECT * FROM pages WHERE book_id=? AND pdf_page=2",
        (original["bookforge_id"],),
    )
    assert p["status"] == "FAILED" and p["artifact_dir"] is None
    assert lib.get_doc(r["document_id"])["published_version"] == r["version_id"]
    frozen = lib.approved_page(
        lib.version(r["version_id"]), original["files"][0]["id"], 2
    )
    assert "old content page 2" in services.store.read(frozen["content_file"]).decode()
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_solution_page_scope_and_matching_must_be_reviewed_again(services):
    from tests.test_phase2 import META, SOL, VERIFY

    lib, r, owner, calls = await seeded(services, published=False)
    old = r["version_id"]
    lib.update_metadata(old, META, owner)
    lib.set_range(old, old + ":primary", {"first_page": 1, "last_page": 2}, owner)
    lib.attach_solution(old, SOL, owner, page_range={"first_page": 3, "last_page": 3})
    lib.verify_solution(old, VERIFY, owner)
    lib.review(old, owner, True, "Controlled combined-source fixture reviewed")
    lib.publish(old, owner)
    draft = lib.clone(old, owner)
    lib.verify_solution(draft["id"], VERIFY, owner)
    for page, file in [(3, "primary"), (2, "solution")]:
        with pytest.raises(HTTPException) as invalid:
            lib.reextract_page(draft["id"], page, draft["id"] + ":" + file, owner)
        assert invalid.value.status_code == 404
    assert len(calls) == 3
    other_pages = services.extraction_db.rows(
        "SELECT * FROM pages WHERE book_id=? AND pdf_page!=3 ORDER BY pdf_page",
        (draft["bookforge_id"],),
    )
    configure(services, "solution-new", "PRIVATE-SOLUTION-KEY")
    queued = lib.reextract_page(draft["id"], 3, draft["id"] + ":solution", owner)
    assert queued["role"] == "solution"
    assert lib.version(draft["id"])["files"][1]["verification"] == "pending"
    await drain(services)
    assert calls[-1][:3] == ("solution-new", "PRIVATE-SOLUTION-KEY", 3)
    assert len(calls) == 4
    assert (
        services.extraction_db.rows(
            "SELECT * FROM pages WHERE book_id=? AND pdf_page!=3 ORDER BY pdf_page",
            (draft["bookforge_id"],),
        )
        == other_pages
    )
    with pytest.raises(HTTPException) as unverified:
        lib.review(draft["id"], owner, True, "Not verified yet")
    assert unverified.value.status_code == 409
    frozen = lib.approved_page(lib.version(old), old + ":solution", 3)
    assert "old content page 3" in services.store.read(frozen["content_file"]).decode()
    assert lib.get_doc(r["document_id"])["published_version"] == old
    lib.verify_solution(draft["id"], VERIFY, owner)
    lib.review(draft["id"], owner, True, "Solution compared again after re-extraction")
    lib.publish(draft["id"], owner)
    frozen_new = lib.approved_page(
        lib.version(draft["id"]), draft["id"] + ":solution", 3
    )
    assert (
        "solution-new content page 3"
        in services.store.read(frozen_new["content_file"]).decode()
    )


@pytest.mark.asyncio
async def test_running_structure_job_blocks_fresh_page_request(services):
    lib, r, owner, calls = await seeded(services, published=False)
    bid = lib.version(r["version_id"])["bookforge_id"]
    services.extraction_db.execute(
        "UPDATE jobs SET status='RUNNING' WHERE kind='structure' AND book_id=?", (bid,)
    )
    before = services.extraction_db.one("SELECT count(*) n FROM runs")["n"]
    with pytest.raises(HTTPException) as running:
        lib.reextract_page(r["version_id"], 2, None, owner)
    assert running.value.status_code == 409
    assert services.extraction_db.one("SELECT count(*) n FROM runs")["n"] == before
    assert len(calls) == 3
