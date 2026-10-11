"""Lossless owner Markdown import. Trailing metadata is routing data, not evidence."""

from dataclasses import dataclass
import re
import yaml
from fastapi import HTTPException

PAGE = re.compile(
    r"^\s*#{1,6}\s*\[([^\n]*?)(?:صفحة\s*PDF|PDF)\s*(\d+)\s*\]", re.I | re.M
)
KEY = re.compile(r"^(section_id|title|status|summary|covers|source_pages)\s*:")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})([^\n]*)$")


@dataclass
class Section:
    metadata: dict
    content: str
    first_line: int
    last_line: int
    initial_page: int | None = None


def _metadata(text, line):
    lines = text.strip().splitlines()
    while lines and lines[0].strip() == "---":
        lines.pop(0)
    while lines and lines[-1].strip() in ("---", "..."):
        lines.pop()
    if len(text) > 65536:
        raise HTTPException(422, f"كتلة فهرسة طويلة جدًا قرب السطر {line}")
    try:
        if any(
            isinstance(token, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken))
            for token in yaml.scan(text)
        ):
            raise yaml.YAMLError("Aliases are not supported in routing metadata")
        data = yaml.safe_load("\n".join(lines))
    except yaml.YAMLError:
        raise HTTPException(422, f"بيانات فهرسة غير صالحة قرب السطر {line}") from None
    if not isinstance(data, dict) or not all(
        k in data for k in ("section_id", "title", "summary")
    ):
        raise HTTPException(
            422, f"تحتاج كتلة الفهرسة إلى section_id وtitle وsummary قرب السطر {line}"
        )
    for key in ("section_id", "title", "summary"):
        if not isinstance(data[key], (str, int, float)) or not str(data[key]).strip():
            raise HTTPException(422, f"حقل {key} فارغ أو غير صالح قرب السطر {line}")
        data[key] = str(data[key]).strip()
    if len(data["title"]) > 400 or len(data["summary"]) > 4000:
        raise HTTPException(422, f"عنوان أو ملخص طويل جدًا قرب السطر {line}")
    covers = data.get("covers", [])
    if (
        not isinstance(covers, list)
        or len(covers) > 40
        or any(not isinstance(v, str) or len(v) > 500 for v in covers)
    ):
        raise HTTPException(422, f"قائمة covers غير صالحة قرب السطر {line}")
    return {
        k: data[k]
        for k in ("section_id", "title", "summary", "status", "covers", "source_pages")
        if k in data
    } | {"covers": covers}


def parse_markdown(raw, filename):
    if not filename.lower().endswith(".md"):
        raise HTTPException(422, "ارفع ملف Markdown بامتداد .md")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(422, "يجب أن يكون ملف Markdown بترميز UTF-8") from None
    if not text.strip() or "\x00" in text:
        raise HTTPException(422, "ملف Markdown فارغ أو يحتوي بيانات غير نصية")
    lines = text.splitlines(keepends=True)
    markers = []
    i = 0
    while i < len(lines):
        fence = FENCE.match(lines[i].rstrip("\r\n"))
        if fence:
            j = i + 1
            while j < len(lines):
                close = FENCE.match(lines[j].rstrip("\r\n"))
                if (
                    close
                    and close[1][0] == fence[1][0]
                    and len(close[1]) >= len(fence[1])
                    and not close[2].strip()
                ):
                    break
                j += 1
            inside = "".join(lines[i + 1 : j])
            is_meta = fence[2].strip().lower() in ("yaml", "yml", "") and re.search(
                r"^section_id\s*:", inside, re.M
            )
            if is_meta:
                if j == len(lines):
                    raise HTTPException(422, f"كتلة YAML غير مغلقة قرب السطر {i + 1}")
                markers.append((i, j + 1, _metadata(inside, i + 1)))
            i = j + 1
            continue
        if re.match(r"^section_id\s*:", lines[i]):
            a = i - 1 if i and lines[i - 1].strip() == "---" else i
            j = i + 1
            while j < len(lines):
                line = lines[j]
                if line.strip() in ("---", "..."):
                    j += 1
                    if j < len(lines) and re.fullmatch(r"\s*`{3,}\s*", lines[j]):
                        j += 1
                    break
                if not line.strip() or KEY.match(line) or line.startswith((" ", "\t")):
                    j += 1
                    continue
                if re.fullmatch(r"\s*`{3,}\s*", line):
                    j += 1
                break
            block = "".join(lines[a:j])
            block = re.sub(r"\n\s*`{3,}\s*$", "", block)
            markers.append((a, j, _metadata(block, i + 1)))
            i = j
            continue
        i += 1
    if not markers:
        raise HTTPException(
            422, "لم نجد كتل فهرسة؛ أضف section_id وtitle وsummary بعد كل درس أو قسم"
        )
    sections = []
    cursor = 0
    current_page = None
    for a, b, meta in markers:
        body = "".join(lines[cursor:a])
        # Explicitly trailing metadata; never silently treat it as front matter.
        if not any(
            v.strip() and not re.match(r"^\s*(#{1,6}\s|<!--|---\s*$)", v)
            for v in body.splitlines()
        ):
            raise HTTPException(
                422, f"لا يوجد محتوى قبل ملخص {meta['title']}؛ الكتل تصف القسم السابق"
            )
        sections.append(Section(meta, body, cursor + 1, a, current_page))
        current_page = last_source_page(body, current_page)
        cursor = b
    trailing = "".join(lines[cursor:])
    if trailing.strip() and re.sub(r"<!--.*?-->|\s|---", "", trailing, flags=re.S):
        raise HTTPException(
            422, "يوجد محتوى بعد آخر ملخص؛ أضف له كتلة فهرسة كي لا يُنسب إلى درس خاطئ"
        )
    warnings = []
    if "\ufffd" in text:
        warnings.append("يوجد رمز استبدال � في المصدر؛ لم نصلحه بالتخمين")
    seen = set()
    for section in sections:
        if section.metadata["section_id"] in seen:
            warnings.append(
                "معرّف section_id مكرر؛ المعرّفات الداخلية تميّز الأقسام حسب ترتيبها"
            )
        seen.add(section.metadata["section_id"])
        if section.metadata.get("status") not in (
            None,
            "مكتمل",
            "complete",
            "completed",
        ):
            warnings.append(f"راجع حالة تفريغ القسم: {section.metadata['title']}")
    return text, sections, list(dict.fromkeys(warnings))


def _page_markers(text):
    """Only literal source headings establish page provenance, never YAML or code."""
    offset, fence, comment = 0, None, False
    for line in text.splitlines(keepends=True):
        start = offset
        offset += len(line)
        if comment:
            if "-->" in line:
                comment = False
            continue
        if not fence and line.lstrip().startswith("<!--"):
            comment = "-->" not in line
            continue
        candidate = FENCE.match(line.rstrip("\r\n"))
        if candidate:
            if (
                fence
                and candidate[1][0] == fence[0]
                and len(candidate[1]) >= len(fence)
                and not candidate[2].strip()
            ):
                fence = None
            elif not fence:
                fence = candidate[1]
            continue
        if fence:
            continue
        marker = PAGE.match(line)
        if marker:
            printed = re.search(r"صفحة الكتاب\s*(.*?)\s*/", marker[1])
            yield start, int(marker[2]), printed[1].strip() if printed else None


def last_source_page(text, default=None):
    """Carry the last encountered page, not the greatest numeric page."""
    current = default
    for _, page, _ in _page_markers(text):
        current = page
    return current


def _has_source_content(text):
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return any(
        line.strip() and not re.fullmatch(r"(?:-{3,}|\*{3,}|_{3,})", line.strip())
        for line in text.splitlines()
    )


def references(text, initial_page=None):
    pages = list(_page_markers(text))
    ids = {page for _, page, _ in pages}
    # A section/chunk may start midway through the preceding physical page.
    prefix = text[: pages[0][0]] if pages else text
    if initial_page is not None and _has_source_content(prefix):
        ids.add(initial_page)
    if not ids:
        return [1], {}, "markdown_section"
    printed = {page: label for _, page, label in pages}
    return sorted(ids), printed, "source_pdf_page"


def blocks(text):
    """Blank-line blocks preserve tables, fenced code and display equations whole."""
    result, current = [], []
    fence, math = None, False
    for line in text.splitlines(keepends=True):
        m = FENCE.match(line.rstrip("\r\n"))
        if m:
            if (
                fence
                and m[1][0] == fence[0]
                and len(m[1]) >= len(fence)
                and not m[2].strip()
            ):
                fence = None
            elif not fence:
                fence = m[1]
        if not fence and len(re.findall(r"(?<!\\)\$\$", line)) % 2:
            math = not math
        current.append(line)
        if not line.strip() and not fence and not math:
            result.append("".join(current))
            current = []
    if current:
        result.append("".join(current))
    return result


def groups(text, target=8000):
    # Only heading boundaries split a logical explanation/example. A large atomic
    # section stays whole, rather than silently chopping its proof or solution.
    atomic, current = [], []
    for block in blocks(text):
        heading = re.match(r"^#{1,3}\s+(?!\[)", block)
        if current and heading:
            atomic.append("".join(current))
            current = []
        current.append(block)
    if current:
        atomic.append("".join(current))
    result, current, size = [], [], 0
    for block in atomic:
        if current and size + len(block) > target:
            result.append("".join(current))
            current, size = [], 0
        current.append(block)
        size += len(block)
    if current:
        result.append("".join(current))
    return result
