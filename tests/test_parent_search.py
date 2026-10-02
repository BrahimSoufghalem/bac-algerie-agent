import pytest
from bac.library.service import transcribed_search_text
from bac.vendor.bookforge.models.page import PageDocument
from tests import test_library


def test_literal_fields_are_all_searchable_not_first_nonempty_only():
    text = transcribed_search_text(
        {"text": "title", "caption": "caption", "latex": "formula",
         "headers": ["header"], "rows": [["row"]],
         "cells": [{"text": "cell"}], "footnotes": ["footnote"],
         "toc_entries": [{"title": "toc"}]}
    )
    assert text.splitlines() == [
        "title", "caption", "formula", "header", "row", "cell", "footnote", "toc"]


@pytest.mark.asyncio
async def test_parent_complex_table_cells_headers_and_notes_indexed_without_child_duplication(
    services, monkeypatch
):
    class ParentVision:
        async def extract(self, image, page, width, height):
            return PageDocument(
                pdf_page=page, width=width, height=height,
                elements=[
                    {"id": "unit", "type": "heading", "order": 0,
                     "structure_type": "unit", "text": "Unit 01"},
                    {"id": "table", "type": "table", "order": 1,
                     "bbox": [5, 5, 100, 100], "complex_table": True,
                     "caption": "CaptionMarker", "headers": ["HeaderMarker"],
                     "cells": [{"row": 0, "column": 0, "text": "كمية المادة"}],
                     "footnotes": ["FootnoteMarker"]},
                    {"id": "lesson", "type": "heading", "order": 2,
                     "structure_type": "lesson", "text": "Lesson 1"},
                    {"id": "body", "type": "paragraph", "order": 3,
                     "text": "DescendantOnlyMarker"}
                ]
            ), {}
    monkeypatch.setattr(test_library, "FakeVision", ParentVision)
    lib, uploaded, owner = test_library.seeded(services)
    doc = await test_library.process_and_publish(services, lib, uploaded, owner)
    unit = lib.nodes(doc["id"], "unit")[0]
    lesson = lib.nodes(doc["id"], "lesson")[0]
    for query in ("كمية المادة", "CaptionMarker", "HeaderMarker", "FootnoteMarker"):
        hits = lib.search(query)
        assert [h["node_id"] for h in hits] == [unit["id"]]
    assert [h["node_id"] for h in lib.search("DescendantOnlyMarker")] == [lesson["id"]]