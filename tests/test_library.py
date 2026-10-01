import pytest
import pymupdf as fitz
from bac.library.service import Library
from bac.core.auth import create_user
from bac.core.db import uid, js
from bac.vendor.bookforge.models.page import PageDocument


def seeded(services):
    user = create_user(
        services.db, "owner@example.com", "Strong-password-1", "Owner", "owner"
    )
    pdf = services.store.path("test.pdf")
    with fitz.open() as d:
        d.new_page().insert_text((30, 30), "Book")
        d.save(pdf)
    lib = Library(services)
    r = lib.upload(
        pdf,
        "book.pdf",
        {
            "title": "كتاب الحرارة",
            "kind": "book",
            "subject": "physics",
            "track": "science",
        },
        user,
    )
    return lib, r, user


class FakeVision:
    async def extract(self, image, page, width, height):
        return PageDocument(
            pdf_page=page,
            width=width,
            height=height,
            languages=["ar"],
            elements=[
                {
                    "id": "lesson",
                    "type": "heading",
                    "order": 0,
                    "structure_type": "lesson",
                    "text": "الدرس الأول: الحرارة",
                },
                {
                    "id": "p",
                    "type": "paragraph",
                    "order": 1,
                    "text": "الحرارة تنتقل من الجسم الساخن إلى الجسم البارد.",
                },
                {
                    "id": "figure",
                    "type": "figure",
                    "order": 2,
                    "bbox": [5, 5, 100, 100],
                    "caption": "رسم المصدر",
                },
                {
                    "id": "eq",
                    "type": "equation",
                    "order": 3,
                    "latex": "Q=mc\\Delta T",
                    "bbox": [5, 105, 100, 150],
                },
            ],
        ), {"total_tokens": 1}


async def process_and_publish(s, lib, r, user):
    cid = uid("cfg")
    s.db.execute(
        "INSERT INTO model_configs VALUES(?,?,?,?,?)",
        (
            cid,
            "extraction",
            js({"base_url": "https://example.org/v1", "model": "fake"}),
            s.vault.encrypt("fake"),
            1,
        ),
    )
    s.db.execute(
        "INSERT OR REPLACE INTO active_models VALUES(?,?)", ("extraction", cid)
    )
    s.extraction_engine.provider_factory = lambda cfg, key: FakeVision()
    lib.process(r["version_id"], user)
    while j := s.extraction_queue.claim():
        await s.extraction_engine.process(j)
    lib.review(r["version_id"], user, True, "Reviewed source")
    return lib.publish(r["version_id"], user)


@pytest.mark.asyncio
async def test_draft_not_visible_review_required_and_published_bundle(services):
    lib, r, user = seeded(services)
    assert not lib.list_documents()
    with pytest.raises(Exception):
        lib.publish(r["version_id"], user)
    d = await process_and_publish(services, lib, r, user)
    assert len(lib.list_documents()) == 1
    lessons = lib.nodes(d["id"], "lesson")
    assert len(lessons) == 1
    result = lib.node(lessons[0]["id"])
    assert "الحرارة تنتقل" in result["content"]
    assert result["assets"] and result["sources"][0]["version_id"] == r["version_id"]
    assert lib.search("الحرارة")
    services.db.execute("UPDATE documents SET status='ARCHIVED' WHERE id=?", (d["id"],))
    assert not lib.search("الحرارة")
    with pytest.raises(Exception):
        lib.node(lessons[0]["id"])
