"""Freeze JSON, ordered full source text, rasters and file identities before publication."""

import hashlib, json, shutil
from fastapi import HTTPException
from bac.core.db import js, uid
from bac.vendor.bookforge.models.page import Element
from bac.vendor.bookforge.markdown.generator import element_markdown
from bac.library.parts import joined, make_parts


def frozen_snapshot(s, version, document, files, actor, notes):
    prefix = "snapshots/" + version["id"] + "/" + uid("review")
    all_elements = []
    assets = []
    pages = []
    frozen_files = []
    raw_nodes = []
    # One read transaction prevents mixing node/element/page generations during a concurrent retry.
    c = s.extraction_db.connect()
    try:
        c.execute("BEGIN")
        for source in files:
            raw = dict(
                c.execute(
                    "SELECT * FROM books WHERE id=?", (source["bookforge_id"],)
                ).fetchone()
            )
            if not raw["status"].startswith("COMPLETED"):
                raise HTTPException(409, "Wait for every source file to complete")
            selected = [
                dict(p)
                for p in c.execute(
                    "SELECT * FROM pages WHERE book_id=? AND pdf_page BETWEEN ? AND ? ORDER BY pdf_page",
                    (raw["id"], source["first_page"], source["last_page"]),
                )
            ]
            elements = [
                dict(e)
                for e in c.execute(
                    "SELECT * FROM elements WHERE book_id=? AND ordinal>=? AND ordinal<? ORDER BY ordinal",
                    (
                        raw["id"],
                        source["first_page"] * 1_000_000,
                        (source["last_page"] + 1) * 1_000_000,
                    ),
                )
            ]
            if source["role"] == "primary" and document["kind"] == "book":
                raw_nodes = [
                    dict(n)
                    for n in c.execute(
                        "SELECT * FROM nodes WHERE book_id=? ORDER BY start_order",
                        (raw["id"],),
                    )
                ]
            frozen_files.append(
                {
                    **source,
                    "sha256": raw["sha256"],
                    "filename": raw["filename"],
                    "selected_pages": [p["pdf_page"] for p in selected],
                    "page_count": raw["page_count"],
                    "_raw_pdf": raw["source_file"],
                    "_pages": selected,
                    "_elements": elements,
                }
            )
    finally:
        c.close()
    for source in frozen_files:
        role = source["role"]
        fp = prefix + "/files/" + role
        pdf_path = fp + "/source.pdf"
        s.store.path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            s.extraction_store.path(source["_raw_pdf"]), s.store.path(pdf_path)
        )
        source["source_pdf"] = pdf_path
        for p in source.pop("_pages"):
            image = fp + f"/pages/{p['pdf_page']:04d}.png"
            original = f"library/{source['bookforge_id']}/pages/page_{p['pdf_page']:04d}/original.png"
            if s.extraction_store.path(original).exists():
                s.store.write(image, s.extraction_store.read(original))
            else:
                image = None
            json_path = None
            md_path = None
            if p["artifact_dir"]:
                json_path = fp + f"/pages/{p['pdf_page']:04d}.json"
                s.store.write(
                    json_path, s.extraction_store.read(p["artifact_dir"] + "/page.json")
                )
            pages.append(
                {
                    "file_id": source["id"],
                    "version_id": version["id"],
                    "document_id": version["document_id"],
                    "role": role,
                    "pdf_page": p["pdf_page"],
                    "printed_page": p["printed_page"],
                    "image_file": image,
                    "json_file": json_path,
                    "content_file": md_path,
                    "status": p["status"],
                    "quality": json.loads(p["quality"]),
                    "languages": json.loads(p["languages"]),
                }
            )
        for e in source.pop("_elements"):
            payload = json.loads(e["payload"])
            el = Element.model_validate(payload)
            digest = hashlib.sha256(
                (source["id"] + ":" + e["id"]).encode()
            ).hexdigest()[:20]
            eid = version["id"] + ":element:" + digest
            aid = None
            if e["asset_file"]:
                aid = version["id"] + ":asset:" + digest
                asset_path = fp + "/assets/" + digest + ".png"
                s.store.write(asset_path, s.extraction_store.read(e["asset_file"]))
                assets.append(
                    {
                        "id": aid,
                        "version_id": version["id"],
                        "document_id": version["document_id"],
                        "node_id": None,
                        "file_id": source["id"],
                        "pdf_page": e["ordinal"] // 1_000_000,
                        "ordinal": e["ordinal"],
                        "type": e["type"],
                        "file": asset_path,
                        "metadata": {
                            **payload,
                            "source_element_id": e["id"],
                            "ordinal": e["ordinal"],
                            "file_id": source["id"],
                            "role": role,
                            "extraction_version": version["id"],
                        },
                    }
                )
            markdown = element_markdown(el)
            if aid:
                # Reuse deterministic Markdown rendering; replace only the relative image target.
                marker = "asset/" + digest + ".png"
                markdown = element_markdown(el, marker, ".").replace(
                    "](" + marker + ")", "](/api/library/assets/" + aid + ")"
                )
            all_elements.append(
                {
                    "id": eid,
                    "file_id": source["id"],
                    "role": role,
                    "pdf_page": e["ordinal"] // 1_000_000,
                    "printed_page": next(
                        (
                            p["printed_page"]
                            for p in pages
                            if p["file_id"] == source["id"]
                            and p["pdf_page"] == e["ordinal"] // 1_000_000
                        ),
                        None,
                    ),
                    "ordinal": e["ordinal"],
                    "type": e["type"],
                    "title": el.text if e["type"] == "heading" else el.caption,
                    "markdown": markdown,
                    "metadata": payload,
                    "asset_id": aid,
                }
            )
        source.pop("_raw_pdf")
        selected_elements = [e for e in all_elements if e["file_id"] == source["id"]]
        content_file = fp + "/content.md"
        # Freeze each selected page, including explicit blank/unreadable gaps.
        source["content_file"] = content_file
        for page in [p for p in pages if p["file_id"] == source["id"]]:
            path = fp + f"/pages/{page['pdf_page']:04d}.md"
            text = joined(
                [e for e in selected_elements if e["pdf_page"] == page["pdf_page"]]
            )
            if not text:
                raw_doc = (
                    json.loads(s.store.read(page["json_file"]))
                    if page["json_file"]
                    else {}
                )
                text = (
                    "[BLANK PAGE]"
                    if raw_doc.get("is_blank")
                    else "[SOURCE PAGE UNAVAILABLE OR UNREADABLE]"
                )
            s.store.write(path, text.encode())
            page["content_file"] = path
        file_pages = [p for p in pages if p["file_id"] == source["id"]]
        body = []
        for p in file_pages:
            text = s.store.read(p["content_file"]).decode()
            if not text.startswith("<!-- PDF page"):
                text = (
                    f"<!-- PDF page {p['pdf_page']}; source {source['id']} -->\n\n"
                    + text
                )
            body.append(text)
        s.store.write(content_file, "\n\n".join(body).encode())
        source["extraction_complete"] = all(
            p["status"] != "FAILED" and p["json_file"] is not None for p in file_pages
        )
    primary = next(f for f in frozen_files if f["role"] == "primary")
    primary_elements = [e for e in all_elements if e["role"] == "primary"]
    warnings = [
        {
            "file_id": p["file_id"],
            "role": p["role"],
            "pdf_page": p["pdf_page"],
            "status": p["status"],
            "quality": p["quality"],
        }
        for p in pages
        if p["status"] in ("FAILED", "NEEDS_REVIEW")
    ]
    nodes = []
    parts = []
    if document["kind"] == "book":
        mapping = {
            n["id"]: version["id"]
            + ":"
            + hashlib.sha256(n["id"].encode()).hexdigest()[:16]
            for n in raw_nodes
        }
        for raw in raw_nodes:
            subset = [
                e
                for e in primary_elements
                if raw["start_order"] <= e["ordinal"] <= raw["end_order"]
            ]
            nid = mapping[raw["id"]]
            meta = json.loads(s.extraction_store.read(raw["metadata_file"]))
            meta.pop("assets", None)
            meta.update(
                {
                    "source_node_id": raw["id"],
                    "extraction_version": version["id"],
                    "review_state": "OWNER_APPROVED",
                    "file_id": primary["id"],
                    "warnings": warnings,
                }
            )
            path = prefix + "/nodes/" + nid.split(":")[-1] + "/content.md"
            s.store.write(path, joined(subset).encode())
            n = {
                **{
                    k: raw[k]
                    for k in (
                        "kind",
                        "title",
                        "start_order",
                        "end_order",
                        "start_page",
                        "end_page",
                    )
                },
                "id": nid,
                "version_id": version["id"],
                "document_id": version["document_id"],
                "parent_id": mapping.get(raw["parent_id"]),
                "content_file": path,
                "metadata": meta,
            }
            nodes.append(n)
            if n["kind"] == "lesson":
                parts.extend(make_parts(n, subset, prefix, s.store))
    else:
        nid = version["id"] + ":bundle"
        kind = document["kind"]
        path = prefix + "/nodes/bundle/content.md"
        text = s.store.read(primary["content_file"]).decode()
        s.store.write(path, text.encode())
        nodes = [
            {
                "id": nid,
                "version_id": version["id"],
                "document_id": version["document_id"],
                "parent_id": None,
                "kind": kind,
                "title": document["title"],
                "start_order": primary["first_page"] * 1_000_000,
                "end_order": (primary["last_page"] + 1) * 1_000_000 - 1,
                "start_page": primary["first_page"],
                "end_page": primary["last_page"],
                "content_file": path,
                "metadata": {
                    "file_id": primary["id"],
                    "extraction_version": version["id"],
                    "review_state": "OWNER_APPROVED",
                    "atomic_bundle": kind in ("exam", "exercise_collection"),
                    "warnings": warnings,
                    "bundle_files": [
                        {
                            k: f[k]
                            for k in (
                                "id",
                                "role",
                                "first_page",
                                "last_page",
                                "source_pdf",
                                "content_file",
                            )
                        }
                        for f in frozen_files
                    ],
                },
            }
        ]
    for a in assets:
        owners = [
            n
            for n in nodes
            if a["file_id"] == n["metadata"]["file_id"]
            and n["start_order"] <= a["ordinal"] <= n["end_order"]
        ]
        a["node_id"] = (
            max(owners, key=lambda n: n["start_order"])["id"]
            if owners
            else nodes[0]["id"]
        )
    for n in nodes:
        if document["kind"] == "book" and n["kind"] == "book":
            n["title"] = document["title"]
    manifest = {
        "schema_version": 2,
        "document": document,
        "reviewer_id": actor,
        "review_notes": notes,
        "nodes": nodes,
        "parts": parts,
        "assets": assets,
        "pages": pages,
        "files": frozen_files,
        "issues": warnings,
        "elements": [
            {k: v for k, v in e.items() if k != "markdown"} for e in all_elements
        ],
    }
    s.store.write(prefix + "/manifest.json", js(manifest).encode())
    return prefix, manifest
