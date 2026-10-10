import pytest
from bac.library.service import transcribed_search_text
from tests.test_library import seeded, process_and_publish, SOURCE


def test_literal_fields_are_all_searchable_not_first_nonempty_only():
    text = transcribed_search_text(
        {
            "text": "title",
            "caption": "caption",
            "latex": "formula",
            "headers": ["header"],
            "rows": [["row"]],
            "cells": [{"text": "cell"}],
            "footnotes": ["footnote"],
            "toc_entries": [{"title": "toc"}],
        }
    )
    assert text.splitlines() == [
        "title",
        "caption",
        "formula",
        "header",
        "row",
        "cell",
        "footnote",
        "toc",
    ]


@pytest.mark.asyncio
async def test_markdown_table_notes_and_distinct_lessons_are_searchable_without_root_duplication(
    services,
):
    lib, _, owner = seeded(services)
    text = SOURCE.replace(
        "وصف الرسم:",
        "| HeaderMarker | Value |\n|---|---|\n| كمية المادة | 1 |\n\nFootnoteMarker\n\nوصف الرسم:",
    ) + SOURCE.replace("الدرس الأول: الحرارة", "درس مستقل").replace(
        "الحرارة تنتقل", "DescendantOnlyMarker"
    ).replace('section_id: "1"', 'section_id: "2"')
    source = services.store.path("search.md")
    source.write_text(text)
    r = lib.upload(
        source,
        "search.md",
        {"kind": "book", "subject": "physics", "track": "science"},
        owner,
    )
    doc = await process_and_publish(services, lib, r, owner)
    nodes = lib.nodes(doc["id"], "lesson")
    for query in ("كمية المادة", "HeaderMarker", "FootnoteMarker"):
        assert [
            h["node_id"] for h in lib.search(query) if h["document_id"] == doc["id"]
        ] == [nodes[0]["id"]]
    assert [h["node_id"] for h in lib.search("DescendantOnlyMarker")] == [
        nodes[1]["id"]
    ]
