"""Known Markdown sources; no model calls during import/review/publication."""

import pytest
from bac.library.service import Library
from bac.core.auth import create_user

SOURCE = """## [صفحة الكتاب 1 / صفحة PDF 1]
# الدرس الأول: الحرارة
الحرارة تنتقل من الجسم الساخن إلى الجسم البارد.

$$
Q=mc\\Delta T
$$

وصف الرسم: جسم ساخن وجسم بارد؛ اتجاه انتقال الطاقة من الساخن إلى البارد.

```yaml
---
section_id: "1"
title: "الدرس الأول: الحرارة"
status: "مكتمل"
summary: "الحرارة وانتقال الطاقة وحسابها بعلاقة Q=mcΔT."
covers:
  - "انتقال الحرارة"
  - "كمية الحرارة"
---
```
"""


def seeded(services):
    owner = create_user(
        services.db, "owner@example.com", "Strong-password-1", "Owner", "owner"
    )
    path = services.store.path("test.md")
    path.write_text(SOURCE)
    lib = Library(services)
    result = lib.upload(
        path,
        "book.md",
        {
            "title": "كتاب الحرارة",
            "kind": "book",
            "subject": "physics",
            "track": "science",
        },
        owner,
    )
    return lib, result, owner


async def process_and_publish(s, lib, result, owner):
    lib.review(result["version_id"], owner, True, "Reviewed source")
    return lib.publish(result["version_id"], owner)


@pytest.mark.asyncio
async def test_draft_not_visible_review_required_and_published_bundle(services):
    lib, result, owner = seeded(services)
    assert not lib.list_documents()
    with pytest.raises(Exception):
        lib.publish(result["version_id"], owner)
    doc = await process_and_publish(services, lib, result, owner)
    lessons = lib.nodes(doc["id"], "lesson")
    assert len(lessons) == 1
    payload = lib.node(lessons[0]["id"])
    assert "الحرارة تنتقل" in payload["content"]
    assert (
        not payload["assets"]
        and payload["sources"][0]["version_id"] == result["version_id"]
    )
    assert lib.search("الحرارة") and not services.db.rows("SELECT * FROM model_usage")
    services.db.execute(
        "UPDATE documents SET status='ARCHIVED' WHERE id=?", (doc["id"],)
    )
    assert not lib.search("الحرارة")
    with pytest.raises(Exception):
        lib.node(lessons[0]["id"])
