"""Source-derived page inheritance; no provider calls or source rewriting."""

import json
from pathlib import Path
import pytest
from bac.library.markdown_import import (
    groups,
    last_source_page,
    parse_markdown,
    references,
)
from benchmarks.math_live_support import load_fixture


def metadata(id, source_pages="PDF 999"):
    return (
        "\n```yaml\n"
        f'section_id: "{id}"\n'
        f'title: "section {id}"\n'
        'summary: "local routing summary"\n'
        f'source_pages: "{source_pages}"\n'
        "covers: []\n```\n"
    )


@pytest.mark.parametrize("fence", ["```", "~~~"])
def test_literal_code_cannot_change_source_page(fence):
    text = (
        "## [صفحة الكتاب 5 / صفحة PDF 109]\nbody\n"
        f"{fence}yaml\n"
        "## [صفحة الكتاب 99 / صفحة PDF 999]\n"
        f"{fence}\n"
        "<!--\n## [صفحة الكتاب 98 / صفحة PDF 998]\n-->\n"
    )
    assert references(text) == ([109], {109: "5"}, "source_pdf_page")
    assert last_source_page(text) == 109


def test_markerless_section_inherits_page_not_yaml_claim():
    text = "## [صفحة الكتاب 5 / صفحة PDF 109]\nfirst\n" + metadata("a")
    text += "# next subsection\nsecond\n" + metadata("b")
    original, sections, _ = parse_markdown(text.encode(), "source.md")
    assert original == text and sections[1].initial_page == 109
    assert references(sections[1].content, sections[1].initial_page)[0] == [109]
    assert sections[1].metadata["source_pages"] == "PDF 999"


@pytest.mark.parametrize(
    "prefix,expected",
    [
        ("", [110]),
        ("\n\n---\n", [110]),
        ("<!-- blank separator -->\n", [110]),
        ("# source heading on prior page\n", [109, 110]),
        ("prior-page explanation\n", [109, 110]),
    ],
)
def test_only_real_prefix_content_inherits_prior_page(prefix, expected):
    text = prefix + "## [صفحة الكتاب 6 / صفحة PDF 110]\nnew-page body\n"
    assert references(text, 109)[0] == expected


def test_unpaginated_markdown_keeps_non_pdf_reference_kind():
    assert references("# lesson\nbody\n") == ([1], {}, "markdown_section")
    assert last_source_page("# lesson\nbody\n") is None


def test_last_encountered_marker_not_numeric_maximum():
    text = "## [صفحة PDF 110]\nbody\n## [صفحة PDF 109]\nbody\n"
    assert last_source_page(text) == 109


def test_page_context_survives_chunk_boundaries_without_adding_markers():
    text = (
        "## [صفحة PDF 109]\n# first\n\n"
        + "body " * 100
        + "\n\n# second\n\ncontinued on same page\n"
    )
    chunks = groups(text, target=100)
    assert len(chunks) == 2 and "".join(chunks) == text
    current, pages = None, []
    for chunk in chunks:
        pages.append(references(chunk, current)[0])
        current = last_source_page(chunk, current)
    assert pages == [[109], [109]]


def revised_book():
    repo = Path(__file__).resolve().parents[1]
    plan = json.loads((repo / "benchmarks/math_live/plan.json").read_text())
    return load_fixture(repo, plan | plan["live_source"])


def test_revised_book_sections_and_all_inherited_ranges():
    raw = revised_book()
    text, sections, _ = parse_markdown(raw, "source-v2.md")
    assert text.encode() == raw and len(sections) == 107
    assert len({s.metadata["section_id"] for s in sections}) == 107
    by_id = {s.metadata["section_id"]: s for s in sections}
    for id, expected in [("3.16", [109]), ("4.9", [135])]:
        section = by_id[id]
        assert references(section.content, section.initial_page)[0] == expected

    # Derive ownership independently from global source-line markers.
    import re

    lines = text.splitlines()
    ownership, current = [], None
    for line in lines:
        marker = re.match(r"^\s*#{1,6}\s*\[.*?صفحة\s*PDF\s*(\d+)\s*\]", line)
        if marker:
            current = int(marker[1])
        ownership.append(current)
    for section in sections:
        expected = sorted(
            {
                ownership[i]
                for i in range(section.first_line - 1, section.last_line)
                if ownership[i] is not None
                and lines[i].strip()
                and not re.fullmatch(r"\s*(?:---+|<!--.*?-->)\s*", lines[i])
            }
        )
        assert references(section.content, section.initial_page)[0] == expected


def test_revised_fixture_hash_guard_and_original_remain_available():
    import hashlib

    repo = Path(__file__).resolve().parents[1]
    plan = json.loads((repo / "benchmarks/math_live/plan.json").read_text())
    revised_plan = plan | plan["live_source"]
    assert hashlib.sha256(revised_book()).hexdigest() == revised_plan["source_sha256"]
    assert len(revised_book()) == 1340252
    assert hashlib.sha256(load_fixture(repo, plan)).hexdigest() == plan["source_sha256"]
    with pytest.raises(ValueError):
        load_fixture(repo, revised_plan | {"source_sha256": "0" * 64})
    with pytest.raises(ValueError):
        load_fixture(repo, revised_plan | {"source_fixture": "../../private"})


def test_snapshot_persists_inherited_pages_and_preserves_source(services):
    from bac.library.service import Library

    raw = revised_book()
    parsed = parse_markdown(raw, "source-v2.md")
    manifest = {key: [] for key in ("files", "pages", "nodes", "parts")}
    Library(services)._snapshot_file(
        manifest,
        "test-page-context",
        "test-version",
        "test-document",
        "primary",
        parsed,
        "source-v2.md",
        {"kind": "book", "title": "Revised math"},
        "test-owner",
    )
    assert services.store.path(manifest["files"][0]["content_file"]).read_bytes() == raw
    for id, expected in [("3.16", [109]), ("4.9", [135])]:
        node = next(
            n for n in manifest["nodes"] if n["metadata"].get("section_id") == id
        )
        assert node["start_page"] == node["end_page"] == expected[0]
        assert node["metadata"]["pages"] == expected
        assert node["metadata"]["reference_kind"] == "source_pdf_page"
        own = [p for p in manifest["parts"] if p["node_id"] == node["id"]]
        assert own and all(p["metadata"]["pages"] == expected for p in own)
