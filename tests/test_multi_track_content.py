"""One published source can serve several predefined tracks, never other subjects."""

import time
import pytest
from fastapi import HTTPException
from bac.core.auth import create_user
from bac.core.db import uid
from bac.core.study import select_track, document_tracks
from bac.library.contracts import DocumentMetadata
from bac.agent.tools import Tools
from bac.agent.full_index import build_catalog
from tests.test_library import seeded, process_and_publish


def scoped_tools(s, track, subject="physics"):
    id = create_user(
        s.db, uid("student") + "@example.invalid", "Strong-password-1", "Student"
    )
    user = s.db.one("SELECT * FROM users WHERE id=?", (id,))
    user = select_track(s.db, user, track)
    chat = uid("chat")
    s.db.execute(
        "INSERT INTO conversations(id,user_id,title,created_at,updated_at,study_subject) VALUES(?,?,?,?,?,?)",
        (chat, id, "Test", time.time(), time.time(), subject),
    )
    return Tools(s, user, chat)


def test_multiple_tracks_normalize_deduplicate_and_keep_legacy_single_track():
    m = DocumentMetadata(
        kind="book", subject="فيزياء", tracks=["science", "mathematics", "علوم تجريبية"]
    )
    assert (
        m.tracks == ["experimental_sciences", "mathematics"]
        and m.track == "experimental_sciences"
    )
    assert m.subject == "physics"
    assert DocumentMetadata(kind="book", subject="physics", track="science").tracks == [
        "experimental_sciences"
    ]


@pytest.mark.parametrize(
    "tracks",
    [
        [],
        ["fake"],
        ["experimental_sciences", "foreign_languages"],
        ["experimental_sciences", "literature_philosophy"],
    ],
)
def test_empty_unknown_or_incompatible_track_sets_rejected(tracks):
    with pytest.raises(ValueError):
        DocumentMetadata(kind="book", subject="physics", tracks=tracks)


@pytest.mark.asyncio
async def test_one_book_and_pdf_is_visible_to_each_target_but_not_other_track_or_subject(
    services,
):
    lib, r, owner = seeded(services)
    lib.update_metadata(
        r["version_id"],
        {
            "kind": "book",
            "title": "Shared book",
            "subject": "physics",
            "tracks": ["experimental_sciences", "mathematics"],
        },
        owner,
    )
    d = await process_and_publish(services, lib, r, owner)
    lesson = lib.nodes(d["id"], "lesson")[0]["id"]
    for track in ["experimental_sciences", "mathematics"]:
        tools = scoped_tools(services, track)
        assert [x["id"] for x in tools.library.list_documents()] == [d["id"]]
        assert tools.library.node(lesson)["node"]["id"] == lesson
        assert tools.library.search("الحرارة", {"track": "رياضيات"})
        _, mapping = build_catalog(services, study_scope=tools.study_scope)
        assert lesson in {x["id"] for x in mapping.values()}
    for track, subject in [
        ("technical_mathematics", "physics"),
        ("mathematics", "mathematics"),
    ]:
        tools = scoped_tools(services, track, subject)
        assert not tools.library.list_documents() and not tools.library.search(
            "الحرارة"
        )
        assert not build_catalog(services, study_scope=tools.study_scope)[1]
        with pytest.raises(HTTPException) as e:
            tools.library.node(lesson)
        assert e.value.status_code == 404
    assert len(services.db.rows("SELECT id FROM documents")) == 1
    assert len(services.db.rows("SELECT id FROM documents")) == 1


@pytest.mark.asyncio
async def test_existing_publication_adds_then_removes_track_without_reextracting(
    services,
):
    lib, r, owner = seeded(services)
    d = await process_and_publish(services, lib, r, owner)
    maths = scoped_tools(services, "mathematics")
    science = scoped_tools(services, "experimental_sciences")
    assert not maths.library.list_documents()
    before = len(services.db.rows("SELECT * FROM model_usage"))
    clone = lib.clone(r["version_id"], owner)
    meta = clone["metadata"] | {"tracks": ["experimental_sciences", "mathematics"]}
    lib.update_metadata(clone["id"], meta, owner)
    assert (
        not maths.library.list_documents()
    )  # A draft never broadens publication access.
    lib.review(
        clone["id"], owner, True, "Same completed original, revised audience only"
    )
    shared = lib.publish(clone["id"], owner)
    assert maths.library.list_documents()[0]["id"] == d["id"]
    assert science.library.list_documents()[0]["id"] == d["id"]
    clone2 = lib.clone(shared["published_version"], owner)
    lib.update_metadata(
        clone2["id"], clone2["metadata"] | {"tracks": ["mathematics"]}, owner
    )
    assert science.library.list_documents()
    lib.review(clone2["id"], owner, True, "Narrow audience, no source re-extraction")
    lib.publish(clone2["id"], owner)
    assert not science.library.list_documents()
    assert maths.library.list_documents()[0]["id"] == d["id"]
    assert len(services.db.rows("SELECT * FROM model_usage")) == before
    assert len(services.db.rows("SELECT id FROM documents")) == 1


def test_paired_markdown_answer_inherits_exact_target_tracks(services):
    lib, _, owner=seeded(services)
    source=services.store.path("test.md")
    meta={"kind":"exam","subject":"physics","tracks":["experimental_sciences","mathematics"]}
    r=lib.upload_package(source,"p.md",meta,owner,{"layout":"separate","matching_confirmed":True},source,"a.md")
    answer=next(f for f in lib.version(r["version_id"])["files"] if f["role"]=="solution")
    assert answer["metadata"]["tracks"]==meta["tracks"]
    assert answer["verification"]=="owner_verified" and answer["metadata"]["designation"]=="provided"



@pytest.mark.asyncio
async def test_legacy_metadata_without_track_array_keeps_single_branch_access(services):
    lib, r, owner = seeded(services)
    d = await process_and_publish(services, lib, r, owner)
    services.db.execute(
        "UPDATE documents SET track='science',metadata='{}' WHERE id=?", (d["id"],)
    )
    assert scoped_tools(services, "experimental_sciences").library.list_documents()
    assert not scoped_tools(services, "mathematics").library.list_documents()
    assert document_tracks({"track": "science", "metadata": "{}"}) == [
        "experimental_sciences"
    ]
