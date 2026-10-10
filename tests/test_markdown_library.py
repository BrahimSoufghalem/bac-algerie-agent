"""Markdown routing metadata, source fidelity, inventory and destructive-scope guards."""

import json
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from bac.api.main import create_app
from bac.library.markdown_import import parse_markdown, groups
from bac.agent.full_index import build_catalog
from bac.core.auth import create_user
from bac.core.db import uid
from bac.core.study import TRACK_SUBJECTS
from tests.test_library import SOURCE, seeded, process_and_publish
from tests.test_multi_track_content import scoped_tools
from tests.test_api import login


def upload(
    lib,
    s,
    owner,
    category="textbook",
    tracks=None,
    title="مصدر تجريبي",
    text=SOURCE,
    document_id=None,
):
    path = s.store.path(uid("source") + ".md")
    path.write_text(text)
    return lib.upload(
        path,
        path.name,
        {
            "title": title,
            "kind": "book",
            "content_type": category,
            "subject": "physics",
            "tracks": tracks or ["experimental_sciences"],
        },
        owner,
        document_id,
    )


@pytest.mark.parametrize("fence", ["yaml", "plain", "missing"])
def test_trailing_metadata_with_and_without_fence(fence):
    text = SOURCE.replace("```yaml", "```" if fence == "plain" else "```yaml")
    if fence == "missing":
        text = text.replace("```yaml\n", "").replace("```\n", "")
    original, sections, warnings = parse_markdown(text.encode(), "source.md")
    assert original == text and len(sections) == 1 and not warnings
    assert sections[0].metadata["covers"] == ["انتقال الحرارة", "كمية الحرارة"]
    assert "$$\nQ=mc\\Delta T\n$$" in sections[0].content
    assert "section_id:" not in sections[0].content


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"\xff",
        b"\x00",
        b"# title\nbody",
        b"```yaml\nsection_id: 1\ntitle: a\nsummary: b\n```\ncontent",
        b"body\nsection_id: 1\ntitle: a\nsummary: b\n\n# forgotten\nbody",
        b"body\nsection_id: 1\ntitle: a\nsummary: b\ncovers: bad",
        b"body\nsection_id: 1\ntitle: a\nsummary: &x [*x]",
    ],
)
def test_invalid_input_never_silently_accepted(content):
    with pytest.raises(HTTPException):
        parse_markdown(content, "source.md")


def test_unrelated_code_is_not_routing_metadata():
    text = SOURCE.replace(
        "الحرارة تنتقل", "```python\nsection_id: not_metadata\n```\n\nالحرارة تنتقل"
    )
    assert len(parse_markdown(text.encode(), "source.md")[1]) == 1


def test_subdivision_never_cuts_equations_tables_or_a_subsection():
    section = (
        "# مثال\n\n"
        + "نص طويل " * 300
        + "\n\n$$\na=1\n\nb=2\n$$\n\n| a | b |\n|---|---|\n| 1 | 2 |\n"
    )
    parts = groups(section + "\n# قسم ثان\n\nمحتوى آخر", 400)
    assert parts[0] == section + "\n"
    assert len(parts) == 2 and all(p.count("$$") % 2 == 0 for p in parts)


def test_duplicate_section_ids_and_replacement_symbols_are_warnings_not_guessed_repair():
    text = SOURCE.replace("جسم ساخن", "جسم � ساخن") + SOURCE
    _, sections, warnings = parse_markdown(text.encode(), "source.md")
    assert len(sections) == 2 and len(warnings) == 2 and "�" in sections[0].content


def test_no_extraction_service_model_or_state_is_created(services):
    assert not hasattr(services, "extraction_engine") and not hasattr(
        services, "extraction_db"
    )
    assert not (services.store.root / "extraction").exists()
    assert not services.db.rows("SELECT * FROM active_models WHERE slot='extraction'")


@pytest.mark.asyncio
async def test_inventory_all_subjects_zero_and_distinct_current_source_files(services):
    lib, initial, owner = seeded(services)
    assert len(lib.inventory()["items"]) == sum(map(len, TRACK_SUBJECTS.values()))

    def row(track="experimental_sciences"):
        return next(
            r
            for r in lib.inventory()["items"]
            if r["track"] == track and r["subject"] == "physics"
        )

    assert row()["content"]["textbook"] == {
        "file_count": 1,
        "published_count": 0,
        "added": False,
        "unpublished_count": 1,
    }
    await process_and_publish(services, lib, initial, owner)
    for category in ["exercises", "school_tests", "bac_exams"]:
        result = upload(
            lib, services, owner, category, ["experimental_sciences", "mathematics"]
        )
        await process_and_publish(services, lib, result, owner)
    cloned = lib.clone(initial["version_id"], owner)
    assert row()["content"]["textbook"]["file_count"] == 1
    assert cloned["status"] == "UPLOADED"
    assert all(row()["content"][k]["added"] for k in row()["content"])
    assert row("mathematics")["content"]["exercises"]["file_count"] == 1
    assert not row("technical_mathematics")["content"]["exercises"]["added"]


@pytest.mark.asyncio
async def test_router_catalog_only_metadata_not_source_body(services):
    lib, initial, owner = seeded(services)
    await process_and_publish(services, lib, initial, owner)
    catalog, mapping = build_catalog(services)
    assert "الحرارة وانتقال الطاقة وحسابها" in catalog and "كمية الحرارة" in catalog
    assert "الحرارة تنتقل من الجسم الساخن إلى الجسم البارد." not in catalog
    assert "وصف الرسم:" not in catalog and "Q=mc\\Delta T" not in catalog
    assert len(mapping) == 2


@pytest.mark.asyncio
async def test_single_track_removal_keeps_shared_content_for_other_track(services):
    lib, _, owner = seeded(services)
    r = upload(lib, services, owner, tracks=["experimental_sciences", "mathematics"])
    doc = await process_and_publish(services, lib, r, owner)
    node = lib.nodes(doc["id"], "lesson")[0]["id"]
    maths = scoped_tools(services, "mathematics")
    science = scoped_tools(services, "experimental_sciences")
    maths.load(node)
    science.load(node)
    preview = lib.removal_preview("physics", "experimental_sciences")
    assert any(d["retained_in_other_tracks"] for d in preview["documents"])
    lib.remove_content(
        "physics", "experimental_sciences", None, preview["confirmation_token"], owner
    )
    with pytest.raises(HTTPException):
        science.library.node(node)
    assert maths.library.node(node)["content"]
    assert (
        len(maths.library.list_documents()) == 1
        and not science.library.list_documents()
    )
    assert (
        services.db.rows(
            "SELECT * FROM loaded_context WHERE conversation_id=?", (maths.chat,)
        )
        if hasattr(maths, "chat")
        else True
    )
    inventory = lib.inventory()["items"]
    assert not next(
        r
        for r in inventory
        if r["track"] == "experimental_sciences" and r["subject"] == "physics"
    )["content"]["textbook"]["file_count"]


@pytest.mark.asyncio
async def test_global_removal_revokes_sources_purges_files_and_preserves_subjects(
    services,
):
    lib, r, owner = seeded(services)
    doc = await process_and_publish(services, lib, r, owner)
    node = lib.nodes(doc["id"], "lesson")[0]["id"]
    before = lib.version(r["version_id"])
    original = before["metadata"]["original_source_dir"]
    token = lib.removal_preview("physics")["confirmation_token"]
    lib.remove_content("physics", None, None, token, owner)
    assert (
        not lib.list_documents()
        and not services.store.path(before["snapshot_dir"]).exists()
        and not services.store.path(original).exists()
    )
    with pytest.raises(HTTPException):
        lib.node(node)
    assert (
        next(
            r
            for r in lib.inventory()["items"]
            if r["track"] == "experimental_sciences" and r["subject"] == "physics"
        )["content"]["textbook"]["file_count"]
        == 0
    )
    with pytest.raises(HTTPException):
        lib.publish(r["version_id"], owner)


def test_stale_confirmation_cannot_delete_newly_added_source(services):
    lib, _, owner = seeded(services)
    token = lib.removal_preview("physics")["confirmation_token"]
    upload(lib, services, owner)
    with pytest.raises(HTTPException) as e:
        lib.remove_content("physics", None, None, token, owner)
    assert (
        e.value.status_code == 409
        and len(services.db.rows("SELECT id FROM documents WHERE status!='DELETED'"))
        == 2
    )


@pytest.mark.asyncio
async def test_category_deletion_and_single_file_deletion_are_separate(services):
    lib, r, owner = seeded(services)
    await process_and_publish(services, lib, r, owner)
    upload(lib, services, owner, "exercises")
    preview = lib.removal_preview("physics", None, "exercises")
    lib.remove_content(
        "physics", None, "exercises", preview["confirmation_token"], owner
    )
    assert len(lib.list_documents()) == 1
    preview = lib.document_removal_preview(r["document_id"])
    lib.remove_document(r["document_id"], preview["confirmation_token"], owner)
    assert not lib.list_documents()


def test_review_freezes_source_and_publication_has_no_model_usage(services):
    lib, r, owner = seeded(services)
    original = lib.version(r["version_id"])["metadata"]["original_source_dir"]
    lib.review(r["version_id"], owner, True, "")
    services.store.write(original + "/primary.md", b"UNAPPROVED CHANGE")
    doc = lib.publish(r["version_id"], owner)
    assert (
        "UNAPPROVED" not in lib.node(lib.nodes(doc["id"], "lesson")[0]["id"])["content"]
    )
    assert not services.db.rows("SELECT * FROM model_usage")


def test_api_owner_csrf_retired_routes_pdf_rejection_and_delete_confirmation(services):
    lib, r, owner = seeded(services)
    client = TestClient(create_app(services))
    headers = login(client, "owner@example.com")
    assert client.get("/api/owner/library/inventory").status_code == 200
    assert (
        client.post(
            "/api/owner/library/remove-preview", json={"subject": "physics"}
        ).status_code
        == 403
    )
    assert client.get("/api/owner/model-presets?slot=extraction").status_code == 422
    assert (
        client.post(
            "/api/owner/models/extraction/test", json={"confirm": True}, headers=headers
        ).status_code
        == 422
    )
    assert client.post(
        f"/api/owner/versions/{r['version_id']}/process", json={}, headers=headers
    ).status_code in (404, 405)
    assert (
        client.post(
            "/api/owner/documents/upload",
            data={
                "metadata": json.dumps(
                    {"kind": "book", "subject": "physics", "track": "science"}
                )
            },
            files={"file": ("book.pdf", b"%PDF fake", "application/pdf")},
            headers=headers,
        ).status_code
        == 422
    )
    preview = client.get(
        f"/api/owner/documents/{r['document_id']}/delete-preview"
    ).json()
    res = client.delete(
        f"/api/owner/documents/{r['document_id']}", headers=headers
    )  # Missing explicit token.
    assert res.status_code == 422
    res = client.request(
        "DELETE",
        f"/api/owner/documents/{r['document_id']}",
        json={"confirmation_token": preview["confirmation_token"]},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    student = create_user(
        services.db, "student-inventory@test.invalid", "Strong-password-1", "Student"
    )
    sc = TestClient(create_app(services))
    sh = login(sc, "student-inventory@test.invalid")
    assert student and sc.get("/api/owner/library/inventory").status_code == 403
    assert (
        sc.post(
            "/api/owner/library/remove",
            json={"subject": "physics", "confirmation_token": "a" * 64},
            headers=sh,
        ).status_code
        == 403
    )


def test_metadata_changes_do_not_reclassify_or_mutate_approved_sources(
    services, monkeypatch
):
    lib, r, owner = seeded(services)
    vid = r["version_id"]
    stale = lib.version(vid)
    changed = stale["metadata"] | {"title": "عنوان جديد"}
    updated = lib.update_metadata(vid, changed, owner)
    assert updated["edit_revision"] == stale["edit_revision"] + 1
    with pytest.raises(HTTPException) as exc:
        lib.update_metadata(vid, changed | {"content_type": "exercises"}, owner)
    assert exc.value.status_code == 409
    lib.review(vid, owner, True, "")
    frozen = lib.preview(vid)
    real_version = lib.version
    monkeypatch.setattr(
        lib, "version", lambda key: stale if key == vid else real_version(key)
    )
    with pytest.raises(HTTPException) as exc:
        lib.update_metadata(vid, changed | {"title": "متأخر"}, owner)
    assert exc.value.status_code == 409
    monkeypatch.setattr(lib, "version", real_version)
    assert lib.preview(vid) == frozen
