"""Deterministic local routing labels for complete-block lesson parts."""

import re


def local_part_metadata(text, parent):
    # Fences/comments are not routing instructions. Page markers are not concepts.
    prose = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    prose = re.sub(r"(?m)^(`{3,}|~{3,})[^\n]*\n[\s\S]*?^\1[^\n]*$", "", prose)
    headings = []
    for line in prose.splitlines():
        match = re.match(r"^#{1,6}\s+(.+)", line)
        if not match:
            continue
        h = " ".join(match[1].split()).strip("# ")
        if re.search(r"^(?:\[?(?:صفحة|الصفحة|page|PDF|ص\.)|\d+[\s./-]*$)", h, re.I):
            continue
        if h and h not in headings and h != parent.get("title"):
            headings.append(h[:140])
    if headings:
        title = headings[0]
        summary = " · ".join(headings[:6])[:420]
        covers = headings[:8]
    else:
        # An exact bounded local extract is a locator, never asserted completeness.
        lines = [
            " ".join(x.split())
            for x in prose.splitlines()
            if x.strip() and not re.match(r"^\s*(?:#|\$|!\[|\|)", x)
        ]
        title = parent.get("title", "")
        summary = " ".join(lines[:3])[:420]
        covers = []
    return {
        "title": title,
        "summary": summary,
        "covers": covers,
        "routing_summary_kind": "extractive_local",
        "content_chars": len(text),
    }
