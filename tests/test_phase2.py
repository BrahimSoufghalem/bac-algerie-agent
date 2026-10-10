"""Replacement contracts for Markdown bundles, parts, budgets and immutable reads."""

import pytest
from fastapi import HTTPException
from bac.agent.tools import Tools
from bac.library.parts import legacy_blocks
from tests.test_agent import chat_and_config
from tests.test_library import SOURCE, seeded, process_and_publish


@pytest.mark.parametrize(
    "category,kind",
    [
        ("school_tests", "exam"),
        ("bac_exams", "exam"),
        ("exercises", "exercise_collection"),
    ],
)
@pytest.mark.asyncio
async def test_atomic_bundle_exact_supplied_statement_and_solution(
    services, category, kind
):
    lib, _, owner = seeded(services)
    source = services.store.path("test.md")
    result = lib.upload_package(
        source,
        "statement.md",
        {
            "kind": kind,
            "content_type": category,
            "subject": "physics",
            "track": "science",
        },
        owner,
        {"layout": "separate", "matching_confirmed": True},
        source,
        "solution.md",
    )
    doc = await process_and_publish(services, lib, result, owner)
    node = lib.nodes(doc["id"])[0]
    assert node["kind"] == kind
    bundle = lib.bundle(node["id"])
    assert bundle["atomic_bundle"] and len(bundle["sources"]) == 2
    assert bundle["solution_status"] == "owner_verified"
    assert "الحرارة تنتقل" in bundle["solution"]["content"]
    assert bundle["solution"]["provenance"]["designation"] == "provided"
    assert not services.db.rows("SELECT * FROM model_usage")


@pytest.mark.parametrize(
    "category,kind", [("school_tests", "exam"), ("exercises", "exercise_collection")]
)
@pytest.mark.asyncio
async def test_missing_solution_is_explicit_not_invented(services, category, kind):
    lib, _, owner = seeded(services)
    result = lib.upload(
        services.store.path("test.md"),
        "statement.md",
        {
            "kind": kind,
            "content_type": category,
            "subject": "physics",
            "track": "science",
        },
        owner,
    )
    doc = await process_and_publish(services, lib, result, owner)
    bundle = lib.bundle(lib.nodes(doc["id"])[0]["id"])
    assert bundle["solution"] is None and bundle["solution_status"] == "not_available"


@pytest.mark.asyncio
async def test_same_page_sections_are_independent_and_complete(services):
    lib, _, owner = seeded(services)
    text = SOURCE + SOURCE.replace("الدرس الأول: الحرارة", "درس الطاقة").replace(
        "الحرارة تنتقل", "الطاقة محفوظة"
    ).replace('section_id: "1"', 'section_id: "2"')
    path = services.store.path("two.md")
    path.write_text(text)
    result = lib.upload(
        path,
        "two.md",
        {"kind": "book", "subject": "physics", "track": "science"},
        owner,
    )
    doc = await process_and_publish(services, lib, result, owner)
    nodes = lib.nodes(doc["id"], "lesson")
    assert len(nodes) == 2
    assert "الطاقة محفوظة" not in lib.node(nodes[0]["id"])["content"]
    assert "الطاقة محفوظة" in lib.node(nodes[1]["id"])["content"]


@pytest.mark.asyncio
async def test_long_lesson_lossless_parts_and_unauthorized_citation(services):
    lib, _, owner = seeded(services)
    text = (
        "# مقدمة\n\n"
        + ("نص كامل دون حذف. " * 400)
        + "\n\n# قسم آخر\n\n"
        + ("شرح آخر كامل. " * 400)
        + "\n\n"
        + SOURCE[SOURCE.index("```yaml") :]
    )
    path = services.store.path("long.md")
    path.write_text(text)
    r = lib.upload(
        path,
        "long.md",
        {"kind": "book", "subject": "physics", "track": "science"},
        owner,
    )
    doc = await process_and_publish(services, lib, r, owner)
    node = lib.nodes(doc["id"], "lesson")[0]["id"]
    parts = lib.parts(node)
    assert len(parts) > 1
    assert (
        "".join(lib.part(p["id"])["content"] for p in parts)
        == lib.node(node)["content"]
    )
    user, chat = chat_and_config(services)
    tools = Tools(services, user, chat)
    with pytest.raises(ValueError):
        tools.answer({"blocks": [{"type": "text", "text": "x"}], "source_ids": [node]})
    tools.load(node)
    assert tools.answer(
        {"blocks": [{"type": "text", "text": "x"}], "source_ids": [node]}
    )


def test_combined_pdf_page_ranges_are_retired(services):
    lib, _, owner = seeded(services)
    with pytest.raises(HTTPException):
        lib.upload_package(
            services.store.path("test.md"),
            "source.md",
            {"kind": "exam", "subject": "physics", "track": "science"},
            owner,
            {
                "layout": "combined",
                "matching_confirmed": True,
                "primary_range": {"first_page": 1, "last_page": 2},
                "solution_range": {"first_page": 3, "last_page": 4},
            },
        )


def test_invalid_second_markdown_does_not_create_partial_version(services):
    lib, r, owner = seeded(services)
    bad = services.store.path("bad.md")
    bad.write_text("missing metadata")
    with pytest.raises(HTTPException):
        lib.upload_package(
            services.store.path("test.md"),
            "p.md",
            {"kind": "exam", "subject": "physics", "track": "science"},
            owner,
            {"layout": "separate", "matching_confirmed": True},
            bad,
            "a.md",
        )
    assert (
        len(services.db.rows("SELECT * FROM documents")) == 1
        and len(services.db.rows("SELECT * FROM versions")) == 1
    )
    assert services.store.path(lib.version(r["version_id"])["snapshot_dir"]).exists()


def test_legacy_markdown_blocks_keep_equations_and_fences():
    text = "a\n\n$$\nx=1\n\ny=2\n$$\n\n```text\na\n\nb\n```\n"
    parsed = legacy_blocks(text, 1)
    assert any("x=1\n\ny=2" in block for block, _ in parsed)
    assert any("a\n\nb" in block for block, _ in parsed)
