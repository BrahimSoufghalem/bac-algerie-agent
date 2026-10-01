"""Lossless retrieval subdivisions; never split exam/exercise logical bundles."""

import hashlib, re
from bac.core.db import js

TARGET_CHARS = 8000
PAGE_MARKER = re.compile(r"<!-- PDF page (\d+);[^\n]*-->")


def joined(elements):
    blocks = []
    last_page = None
    for e in elements:
        if last_page != e["pdf_page"]:
            blocks.append(f"<!-- PDF page {e['pdf_page']}; source {e['file_id']} -->")
            last_page = e["pdf_page"]
        blocks.append(e["markdown"])
    return "\n\n".join(blocks)


def element_groups(elements, target=TARGET_CHARS):
    groups = []
    current = []
    size = 0
    for e in elements:
        text = e["markdown"]
        heading = e["type"] == "heading" and current and size >= target // 3
        if current and (size + len(text) + 2 > target or heading):
            groups.append(current)
            current = []
            size = 0
        current.append(e)
        size += len(text) + 2
    if current:
        groups.append(current)
    return groups


def make_parts(node, elements, prefix, store):
    result = []
    for index, group in enumerate(element_groups(elements)):
        digest = hashlib.sha256(
            js([node["id"], [e["id"] for e in group]]).encode()
        ).hexdigest()[:24]
        id = node["id"] + ":part:" + digest
        path = prefix + "/parts/" + digest + ".md"
        text = joined(group)
        store.write(path, text.encode())
        pages = sorted({e["pdf_page"] for e in group})
        meta = {
            "file_id": group[0]["file_id"],
            "pages": pages,
            "printed_pages": list(
                dict.fromkeys(e["printed_page"] for e in group if e["printed_page"])
            ),
            "start_order": group[0]["ordinal"],
            "end_order": group[-1]["ordinal"],
            "element_ids": [e["id"] for e in group],
            "title": next(
                (e["title"] for e in group if e["type"] == "heading"), node["title"]
            ),
            "content_chars": len(text),
            "boundary": "complete_extracted_elements",
            "complete_lesson": len(result) == 0 and len(group) == len(elements),
        }
        result.append(
            {
                "id": id,
                "node_id": node["id"],
                "version_id": node["version_id"],
                "part_index": index,
                "content_file": path,
                "metadata": meta,
            }
        )
    return result


def legacy_blocks(text, initial_page):
    """Parse only approved v1 Markdown, never re-read mutable raw extraction.
    Fences/math/tables are indivisible; exact text and page markers are retained.
    """
    lines = text.splitlines(keepends=True)
    groups = []
    current = []
    fence = None
    math = False
    page = initial_page
    block_page = page
    for line in lines:
        marker = PAGE_MARKER.search(line)
        if marker and not fence and not math:
            if current:
                groups.append(("".join(current), block_page))
                current = []
            page = int(marker.group(1))
            block_page = page
        match = re.match(r"^\s*(`{3,}|~{3,})", line)
        if match:
            run = match.group(1)
            if fence and run[0] == fence[0] and len(run) >= len(fence):
                fence = None
            elif not fence:
                fence = run
        if line.strip() == "$$" and not fence:
            math = not math
        if not line.strip() and not fence and not math:
            if current:
                groups.append(("".join(current), block_page))
                current = []
            continue
        if not current:
            block_page = page
        current.append(line)
    if current:
        groups.append(("".join(current), block_page))
    return groups
