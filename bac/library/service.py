"""Owner-managed Markdown sources, immutable publication and scoped removal."""

import hashlib
import json
from pathlib import Path
import re
import shutil
import time
from fastapi import HTTPException
from bac.core.db import uid, js
from bac.core.study import (
    TRACKS,
    SUBJECTS,
    TRACK_SUBJECTS,
    CONTENT_TYPES,
    document_tracks,
    resolve,
    content_type,
)
from bac.library.contracts import DocumentMetadata, UploadPackage
from bac.library.markdown_import import parse_markdown, references, groups
from bac.library.retrieval import Reader


def transcribed_search_text(meta):
    """Index all literal fields, including complex-table cells on parent nodes."""
    return "\n".join(
        [meta.get("text", ""), meta.get("caption", ""), meta.get("latex", "")]
        + meta.get("headers", [])
        + [" ".join(row) for row in meta.get("rows", [])]
        + [cell.get("text", "") for cell in meta.get("cells", [])]
        + meta.get("footnotes", [])
        + [entry.get("title", "") for entry in meta.get("toc_entries", [])]
    )


class Library(Reader):
    def __init__(self, s):
        self.s, self.db, self.cache = s, s.db, s.library_cache

    def get_doc(self, id, published=False):
        d = self.db.one(
            "SELECT * FROM documents WHERE id=? AND status!='DELETED'", (id,)
        )
        if not d or (
            published and (d["status"] != "ACTIVE" or not d["published_version"])
        ):
            raise HTTPException(404, "Published document not found")
        if getattr(self, "study_scope", None):
            self.study_scope.check(id)
        d["metadata"] = json.loads(d["metadata"])
        return d

    def upload_package(
        self,
        path,
        filename,
        metadata,
        actor,
        package,
        solution_path=None,
        solution_filename=None,
        document_id=None,
    ):
        meta = DocumentMetadata.model_validate(metadata).model_dump()
        pack = UploadPackage.model_validate(package)
        if pack.layout == "combined" or pack.primary_range or pack.solution_range:
            raise HTTPException(
                422, "ملف Markdown قد يحتوي الحل داخله؛ لا تُستخدم نطاقات صفحات PDF"
            )
        if pack.layout == "none" and (solution_path or pack.matching_confirmed):
            raise HTTPException(422, "اختر إرفاق حل منفصل")
        if pack.layout == "separate" and (
            not solution_path
            or not pack.matching_confirmed
            or meta["kind"] not in ("exam", "exercise_collection")
        ):
            raise HTTPException(
                422, "أرفق ملف حل مطابقًا وأكّد مطابقته للتمارين أو الاختبار"
            )
        if Path(path).stat().st_size > self.s.settings.max_upload_mb * 1024**2 or (
            solution_path
            and Path(solution_path).stat().st_size
            > self.s.settings.max_upload_mb * 1024**2
        ):
            raise HTTPException(413, "File too large")
        primary = parse_markdown(Path(path).read_bytes(), filename)
        solution = (
            parse_markdown(Path(solution_path).read_bytes(), solution_filename)
            if solution_path
            else None
        )
        return self._import(
            primary, filename, meta, actor, document_id, solution, solution_filename
        )

    def upload(self, path, filename, metadata, actor, document_id=None):
        return self.upload_package(
            path, filename, metadata, actor, {"layout": "none"}, document_id=document_id
        )

    def _import(
        self, primary, filename, meta, actor, document_id, solution, solution_filename
    ):
        vid = uid("version")
        prefix = "markdown/" + vid
        meta["title"] = meta["title"] or Path(filename).stem
        meta["source_format"] = "markdown"
        meta["original_source_dir"] = prefix
        doc_id = document_id or uid("doc")
        warnings = primary[2] + (solution[2] if solution else [])
        manifest = {
            "schema_version": 2,
            "source_format": "markdown",
            "nodes": [],
            "parts": [],
            "assets": [],
            "pages": [],
            "elements": [],
            "files": [],
            "issues": warnings,
        }
        self.s.store.write(prefix + "/original.md", primary[0].encode())
        try:
            for role, parsed, name in [("primary", primary, filename)] + (
                [("solution", solution, solution_filename)] if solution else []
            ):
                self._snapshot_file(
                    manifest, prefix, vid, doc_id, role, parsed, name, meta, actor
                )
            self.s.store.write(prefix + "/manifest.json", js(manifest).encode())
            with self.db.tx() as c:
                if document_id:
                    existing = c.execute(
                        "SELECT * FROM documents WHERE id=? AND status!='DELETED'",
                        (doc_id,),
                    ).fetchone()
                    if not existing:
                        raise HTTPException(404, "Document not found")
                    seq = c.execute(
                        "SELECT coalesce(max(sequence),0)+1 FROM versions WHERE document_id=?",
                        (doc_id,),
                    ).fetchone()[0]
                else:
                    seq = 1
                    c.execute(
                        "INSERT INTO documents(id,title,kind,subject,track,year,source,owner_id,created_at,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            doc_id,
                            meta["title"],
                            meta["kind"],
                            meta["subject"],
                            meta["track"],
                            meta.get("year"),
                            meta.get("source", ""),
                            actor,
                            time.time(),
                            js(meta),
                        ),
                    )
                c.execute(
                    "INSERT INTO versions(id,document_id,sequence,bookforge_id,status,snapshot_dir,warnings,created_at,metadata) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        vid,
                        doc_id,
                        seq,
                        "markdown:" + hashlib.sha256(primary[0].encode()).hexdigest(),
                        "UPLOADED",
                        prefix,
                        js(warnings),
                        time.time(),
                        js(meta),
                    ),
                )
                for f in manifest["files"]:
                    c.execute(
                        "INSERT INTO version_files(id,version_id,bookforge_id,role,last_page,metadata,verification,verified_by,verified_at,evidence) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            f["id"],
                            vid,
                            f["sha256"],
                            f["role"],
                            f["last_page"],
                            js(f),
                            f["verification"],
                            actor if f["role"] == "solution" else None,
                            f.get("verified_at"),
                            f.get("evidence"),
                        ),
                    )
        except BaseException:
            shutil.rmtree(self.s.store.path(prefix), ignore_errors=True)
            raise
        self.db.audit(
            actor,
            "document.markdown_import",
            doc_id,
            {
                "version": vid,
                "source_files": len(manifest["files"]),
                "sections": len(primary[1]),
            },
        )
        return {
            "document_id": doc_id,
            "version_id": vid,
            "solution_linked": bool(solution),
            "solution_status": "owner_verified" if solution else "not_available",
            "source_format": "markdown",
            "sections": len(primary[1]),
            "warnings": warnings,
            "status": "UPLOADED",
        }

    def _snapshot_file(
        self, manifest, prefix, vid, doc_id, role, parsed, filename, meta, actor
    ):
        text, sections, _ = parsed
        fid = vid + ":" + role
        source = prefix + "/" + role + ".md"
        self.s.store.write(source, text.encode())
        pages, printed, reference_kind = references(text)
        f = {
            "id": fid,
            "role": role,
            "version_id": vid,
            "document_id": doc_id,
            "filename": filename,
            "content_file": source,
            "source_pdf": source,
            "source_format": "markdown",
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
            "first_page": min(pages),
            "last_page": max(pages),
            "page_count": len(pages),
            "selected_pages": pages,
            "metadata": meta
            | ({"designation": "provided"} if role == "solution" else {}),
            "extraction_status": "COMPLETED",
            "extraction_complete": True,
            "verification": "owner_verified"
            if role == "solution"
            else "not_applicable",
            "evidence": "Owner explicitly confirmed the exact supplied Markdown solution match."
            if role == "solution"
            else "",
            "verified_by": actor if role == "solution" else None,
            "verified_at": time.time() if role == "solution" else None,
        }
        manifest["files"].append(f)
        for page in pages:
            manifest["pages"].append(
                {
                    "file_id": fid,
                    "version_id": vid,
                    "document_id": doc_id,
                    "pdf_page": page,
                    "printed_page": printed.get(page),
                    "image_file": None,
                    "json_file": None,
                    "content_file": source,
                    "status": "COMPLETED",
                    "quality": {
                        "source_format": "markdown",
                        "reference_kind": reference_kind,
                    },
                    "languages": [],
                }
            )
        if role == "solution":
            return
        root = vid + ":book"
        if meta["kind"] in ("book", "reference"):
            manifest["nodes"].append(
                {
                    "id": root,
                    "version_id": vid,
                    "document_id": doc_id,
                    "parent_id": None,
                    "kind": "book",
                    "title": meta["title"],
                    "start_order": 0,
                    "end_order": len(sections) * 10000,
                    "start_page": min(pages),
                    "end_page": max(pages),
                    "content_file": source,
                    "metadata": {
                        "file_id": fid,
                        "source_format": "markdown",
                        "navigation_only": True,
                    },
                }
            )
        for index, section in enumerate(sections):
            nid = vid + ":section:" + str(index + 1)
            path = prefix + "/nodes/" + str(index + 1) + ".md"
            self.s.store.write(path, section.content.encode())
            spages, _, page_kind = references(section.content)
            data = section.metadata | {
                "file_id": fid,
                "source_format": "markdown",
                "content_chars": len(section.content),
                "reference_kind": page_kind,
                "source_lines": [section.first_line, section.last_line],
                "pages": spages,
            }
            kind = "lesson" if meta["kind"] in ("book", "reference") else meta["kind"]
            node = {
                "id": nid,
                "version_id": vid,
                "document_id": doc_id,
                "parent_id": root if kind == "lesson" else None,
                "kind": kind,
                "title": section.metadata["title"],
                "start_order": index * 10000 + 1,
                "end_order": (index + 1) * 10000 - 1,
                "start_page": min(spages),
                "end_page": max(spages),
                "content_file": path,
                "metadata": data,
            }
            manifest["nodes"].append(node)
            # Keep exam statements and solutions atomic; split only large textbook lessons.
            chunks = groups(section.content) if kind == "lesson" else [section.content]
            current_page = min(spages)
            for ci, chunk in enumerate(chunks):
                cpath = prefix + "/parts/" + str(index + 1) + "-" + str(ci + 1) + ".md"
                self.s.store.write(cpath, chunk.encode())
                cpages, _, chunk_reference = references(chunk)
                if (
                    chunk_reference == "markdown_section"
                    and page_kind == "source_pdf_page"
                ):
                    cpages = [current_page]
                current_page = max(cpages)
                headings = re.findall(r"^#{1,6}\s+(?!\[)([^\n]+)", chunk, re.M)
                title = headings[0].strip() if headings else section.metadata["title"]
                cmeta = data | {
                    "title": title,
                    "pages": cpages,
                    "content_chars": len(chunk),
                    "complete_lesson": len(chunks) == 1,
                    "boundary": "complete_markdown_blocks",
                    "start_order": node["start_order"] + ci,
                    "end_order": node["start_order"] + ci,
                }
                manifest["parts"].append(
                    {
                        "id": nid + ":part:" + str(ci + 1),
                        "node_id": nid,
                        "version_id": vid,
                        "part_index": ci,
                        "content_file": cpath,
                        "metadata": cmeta,
                    }
                )
                if len(chunks) > 1:
                    manifest["nodes"].append(
                        node
                        | {
                            "id": nid + ":chunk:" + str(ci + 1),
                            "parent_id": nid,
                            "kind": "section",
                            "title": section.metadata["title"]
                            + " — "
                            + title
                            + f" ({ci + 1}/{len(chunks)})",
                            "start_order": node["start_order"] + ci,
                            "end_order": node["start_order"] + ci,
                            "start_page": min(cpages),
                            "end_page": max(cpages),
                            "content_file": cpath,
                            "metadata": cmeta | {"partial_lesson": True},
                        }
                    )

    def version(self, id):
        v = self.db.one("SELECT * FROM versions WHERE id=?", (id,))
        if not v or v["status"] == "REMOVED":
            raise HTTPException(404, "Version not found")
        self.get_doc(v["document_id"])
        v["metadata"] = json.loads(v["metadata"])
        v["warnings"] = json.loads(v["warnings"])
        if not v["snapshot_dir"]:
            return v | {
                "files": [],
                "source_format": "legacy_pdf",
                "requires_markdown_reupload": True,
            }
        manifest = json.loads(self.s.store.read(v["snapshot_dir"] + "/manifest.json"))
        return v | {
            "source_format": manifest.get("source_format", "legacy_pdf"),
            "files": manifest.get("files", []),
            "sections": [
                {k: n[k] for k in ("id", "title", "kind", "metadata")}
                for n in manifest.get("nodes", [])
                if n["kind"] != "book"
            ],
        }

    def preview(self, id):
        v = self.version(id)
        if v.get("requires_markdown_reupload"):
            raise HTTPException(409, "أعد رفع المصدر بصيغة Markdown")
        manifest = json.loads(self.s.store.read(v["snapshot_dir"] + "/manifest.json"))
        return {
            "version": v,
            "sections": [
                {**n, "content": self.s.store.read(n["content_file"]).decode()}
                for n in manifest.get("nodes", [])
                if n["kind"] != "book" and not n["metadata"].get("partial_lesson")
            ],
        }

    def review(self, id, actor, acknowledge_issues, notes):
        v = self.version(id)
        if v["source_format"] != "markdown":
            raise HTTPException(409, "أعد رفع المصدر بصيغة Markdown للمراجعة")
        if v["status"] != "UPLOADED":
            raise HTTPException(409, "Approved version is immutable")
        if v["warnings"] and not acknowledge_issues:
            raise HTTPException(409, "أكّد مراجعة التحذيرات قبل اعتماد الملف")
        manifest = json.loads(self.s.store.read(v["snapshot_dir"] + "/manifest.json"))
        for f in manifest["files"]:
            if (
                hashlib.sha256(self.s.store.read(f["content_file"])).hexdigest()
                != f["sha256"]
            ):
                raise HTTPException(
                    409, "تغيّر ملف المصدر بعد الاستيراد؛ أعد رفعه ومراجعته"
                )
        old_prefix = v["snapshot_dir"]
        prefix = "snapshots/" + id + "/" + uid("review")
        shutil.copytree(self.s.store.path(old_prefix), self.s.store.path(prefix))

        def relocate(value):
            if isinstance(value, str) and value.startswith(old_prefix + "/"):
                return prefix + value[len(old_prefix) :]
            if isinstance(value, list):
                return [relocate(x) for x in value]
            if isinstance(value, dict):
                return {k: relocate(x) for k, x in value.items()}
            return value

        self.s.store.write(prefix + "/manifest.json", js(relocate(manifest)).encode())
        try:
            with self.db.tx() as c:
                changed = c.execute(
                    "UPDATE versions SET status='REVIEWED',snapshot_dir=?,reviewer_id=?,reviewed_at=?,review_notes=? WHERE id=? AND status='UPLOADED' AND edit_revision=?",
                    (prefix, actor, time.time(), notes, id, v["edit_revision"]),
                ).rowcount
                if not changed:
                    raise HTTPException(
                        409, "تغيّرت المسودة أثناء المراجعة؛ راجعها من جديد"
                    )
        except BaseException:
            shutil.rmtree(self.s.store.path(prefix), ignore_errors=True)
            raise
        self.db.audit(actor, "document.review", id)
        return {"version_id": id, "status": "REVIEWED", "warnings": v["warnings"]}

    def clone(self, id, actor):
        v = self.version(id)
        if v["source_format"] != "markdown":
            raise HTTPException(409, "أعد رفع المصدر بصيغة Markdown")
        manifest = json.loads(self.s.store.read(v["snapshot_dir"] + "/manifest.json"))
        primary = next(f for f in manifest["files"] if f["role"] == "primary")
        solution = next((f for f in manifest["files"] if f["role"] == "solution"), None)
        meta = {
            k: x for k, x in v["metadata"].items() if k in DocumentMetadata.model_fields
        }
        result = self.upload_package(
            self.s.store.path(primary["source_pdf"]),
            primary["filename"],
            meta,
            actor,
            {"layout": "separate", "matching_confirmed": True}
            if solution
            else {"layout": "none"},
            self.s.store.path(solution["source_pdf"]) if solution else None,
            solution["filename"] if solution else None,
            v["document_id"],
        )
        return self.version(result["version_id"])

    def update_metadata(self, id, metadata, actor):
        v = self.version(id)
        if v["status"] != "UPLOADED" or v["source_format"] != "markdown":
            raise HTTPException(409, "Approved version is immutable")
        meta = DocumentMetadata.model_validate(
            {k: x for k, x in metadata.items() if k in DocumentMetadata.model_fields}
        ).model_dump()
        if any(meta[k] != v["metadata"][k] for k in ("kind", "content_type")):
            raise HTTPException(409, "أعد رفع الملف لتغيير نوع المحتوى")
        meta["title"] = meta["title"] or v["metadata"]["title"]
        meta["source_format"] = "markdown"
        meta["original_source_dir"] = v["metadata"]["original_source_dir"]
        # Serialize mutation with review/removal; their revision guards reject
        # snapshots copied while metadata was changing.
        with self.db.tx() as c:
            current = c.execute(
                "SELECT v.status,v.edit_revision,d.status AS document_status FROM versions v JOIN documents d ON d.id=v.document_id WHERE v.id=?",
                (id,),
            ).fetchone()
            if (
                not current
                or current["status"] != "UPLOADED"
                or current["document_status"] == "DELETED"
                or current["edit_revision"] != v["edit_revision"]
            ):
                raise HTTPException(409, "تغيّرت المسودة؛ افتحها من جديد")
            path = v["snapshot_dir"] + "/manifest.json"
            original = self.s.store.read(path)
            manifest = json.loads(original)
            for f in manifest["files"]:
                f["metadata"] = f["metadata"] | meta
            try:
                self.s.store.write(path, js(manifest).encode())
                c.execute(
                    "UPDATE versions SET metadata=?,edit_revision=edit_revision+1 WHERE id=?",
                    (js(meta), id),
                )
            except BaseException:
                self.s.store.write(path, original)
                raise
        self.db.audit(actor, "document.metadata", id)
        return self.version(id)

    def inventory(self):
        documents = self.db.rows("SELECT * FROM documents WHERE status!='DELETED'")
        drafts = {}
        for v in self.db.rows(
            "SELECT document_id,metadata FROM versions WHERE status!='REMOVED'"
        ):
            drafts.setdefault(v["document_id"], []).extend(
                document_tracks({"metadata": v["metadata"]})
            )
        result = []
        for track in TRACKS:
            for subject in TRACK_SUBJECTS[track]:
                row = {
                    "track": track,
                    "track_label": TRACKS[track][0],
                    "subject": subject,
                    "subject_label": SUBJECTS[subject][0],
                    "content": {},
                }
                for category in CONTENT_TYPES:
                    docs = [
                        d
                        for d in documents
                        if resolve(SUBJECTS, d["subject"]) == subject
                        and track in set(document_tracks(d) + drafts.get(d["id"], []))
                        and content_type(d) == category
                    ]
                    ready = [
                        d
                        for d in docs
                        if d["status"] == "ACTIVE"
                        and d["published_version"]
                        and track in document_tracks(d)
                    ]
                    row["content"][category] = {
                        "file_count": len(docs),
                        "published_count": len(ready),
                        "added": bool(ready),
                        "unpublished_count": len(docs) - len(ready),
                    }
                result.append(row)
        return {
            "items": result,
            "count_basis": "current primary source documents, not sections, versions or attached solutions",
        }

    def _removal(self, subject, track, category, rows):
        subject = resolve(SUBJECTS, subject)
        if not subject:
            raise HTTPException(422, "Choose a predefined subject")
        if track and (track not in TRACKS or subject not in TRACK_SUBJECTS[track]):
            raise HTTPException(422, "Choose a subject in this track")
        if category and category not in CONTENT_TYPES:
            raise HTTPException(422, "Invalid material type")
        docs = []
        for d in rows:
            if (
                d["status"] == "DELETED"
                or resolve(SUBJECTS, d["subject"]) != subject
                or (category and content_type(d) != category)
            ):
                continue
            versions = self.db.rows(
                "SELECT id,status,metadata,snapshot_dir FROM versions WHERE document_id=? AND status!='REMOVED' ORDER BY id",
                (d["id"],),
            )
            tracks = set(document_tracks(d)) | {
                t
                for v in versions
                for t in document_tracks({"metadata": v["metadata"]})
            }
            if track and track not in tracks:
                continue
            docs.append(
                {
                    "id": d["id"],
                    "title": d["title"],
                    "status": d["status"],
                    "tracks": sorted(tracks),
                    "published_version": d["published_version"],
                    "metadata": json.loads(d["metadata"])
                    if isinstance(d["metadata"], str)
                    else d["metadata"],
                    "versions": versions,
                }
            )
        fingerprint = hashlib.sha256(
            js([subject, track, category, docs]).encode()
        ).hexdigest()
        return {
            "subject": subject,
            "track": track,
            "content_type": category,
            "document_count": len(docs),
            "documents": [
                {
                    "id": d["id"],
                    "title": d["title"],
                    "tracks": d["tracks"],
                    "retained_in_other_tracks": bool(
                        track and set(d["tracks"]) - {track}
                    ),
                }
                for d in docs
            ],
            "confirmation_token": fingerprint,
        }, docs

    def removal_preview(self, subject, track=None, category=None):
        return self._removal(
            subject,
            track,
            category,
            self.db.rows("SELECT * FROM documents WHERE status!='DELETED' ORDER BY id"),
        )[0]

    def remove_content(self, subject, track, category, token, actor, document_id=None):
        cleanup = []
        with self.db.tx() as c:
            rows = [
                dict(d)
                for d in c.execute(
                    "SELECT * FROM documents WHERE status!='DELETED' ORDER BY id"
                )
            ]
            if document_id:
                rows = [d for d in rows if d["id"] == document_id]
            preview, docs = self._removal(subject, track, category, rows)
            if not token or token != preview["confirmation_token"]:
                raise HTTPException(409, "تغيّر نطاق الحذف؛ عاينه وأكّده من جديد")
            for d in docs:
                remaining = (
                    [
                        t
                        for t in document_tracks({"metadata": d["metadata"]})
                        if t != track
                    ]
                    if track
                    else []
                )
                retained_versions = False
                for v in d["versions"]:
                    vm = json.loads(v["metadata"])
                    vtracks = (
                        [t for t in document_tracks({"metadata": vm}) if t != track]
                        if track
                        else []
                    )
                    if vtracks:
                        retained_versions = True
                        vm.update(tracks=vtracks, track=vtracks[0])
                        c.execute(
                            "UPDATE versions SET metadata=? WHERE id=?",
                            (js(vm), v["id"]),
                        )
                    else:
                        c.execute(
                            "UPDATE versions SET status='REMOVED' WHERE id=?",
                            (v["id"],),
                        )
                        if v["snapshot_dir"] and v["snapshot_dir"].startswith(
                            ("markdown/", "snapshots/")
                        ):
                            cleanup.append(v["snapshot_dir"])
                        origin = vm.get("original_source_dir", "")
                        if origin.startswith("markdown/"):
                            cleanup.append(origin)
                        c.execute(
                            "DELETE FROM library_fts WHERE version_id=?", (v["id"],)
                        )
                    c.execute(
                        "UPDATE agent_runs SET cancel_requested=1 WHERE status IN ('QUEUED','RUNNING') AND conversation_id IN (SELECT lc.conversation_id FROM loaded_context lc JOIN conversations cv ON cv.id=lc.conversation_id JOIN users u ON u.id=cv.user_id WHERE lc.version_id=? AND (? IS NULL OR u.study_track=?))",
                        (v["id"], track if vtracks else None, track),
                    )
                    c.execute(
                        "DELETE FROM loaded_context WHERE version_id=? AND (? IS NULL OR conversation_id IN (SELECT cv.id FROM conversations cv JOIN users u ON u.id=cv.user_id WHERE u.study_track=?))",
                        (v["id"], track if vtracks else None, track),
                    )
                if retained_versions:
                    dm = d["metadata"].copy()
                    all_remaining = sorted(set(d["tracks"]) - {track})
                    dm.update(
                        tracks=remaining or all_remaining,
                        track=(remaining or all_remaining)[0],
                    )
                    c.execute(
                        "UPDATE documents SET metadata=?,track=?,published_version=?,status=? WHERE id=?",
                        (
                            js(dm),
                            dm["track"],
                            d["published_version"] if remaining else None,
                            d["status"] if remaining else "ACTIVE",
                            d["id"],
                        ),
                    )
                else:
                    c.execute(
                        "UPDATE documents SET status='DELETED',published_version=NULL WHERE id=?",
                        (d["id"],),
                    )
                # An in-flight tutor may already hold a removed source. Cancel scoped runs.
                c.execute(
                    "UPDATE agent_runs SET cancel_requested=1 WHERE status IN ('QUEUED','RUNNING') AND conversation_id IN (SELECT cv.id FROM conversations cv JOIN users u ON u.id=cv.user_id WHERE cv.study_subject=? AND (? IS NULL OR u.study_track=?))",
                    (preview["subject"], track, track),
                )
            for path in set(cleanup):
                c.execute(
                    "INSERT OR IGNORE INTO library_cleanup(path,created_at) VALUES(?,?)",
                    (path, time.time()),
                )
        self.cache.clear()
        self.cleanup()
        self.db.audit(
            actor,
            "library.remove_content",
            subject,
            {"track": track, "content_type": category, "documents": len(docs)},
        )
        return {"ok": True, "removed_documents": len(docs), "subject_preserved": True}

    def document_removal_preview(self, id):
        d = self.get_doc(id)
        return self._removal(d["subject"], None, None, [d])[0]

    def remove_document(self, id, token, actor):
        d = self.get_doc(id)
        return self.remove_content(
            d["subject"], None, None, token, actor, document_id=id
        )

    def cleanup(self):
        for item in self.db.rows("SELECT path FROM library_cleanup"):
            path = item["path"]
            if not path.startswith(("markdown/", "snapshots/")):
                continue
            try:
                shutil.rmtree(
                    self.s.store.path(path), ignore_errors=False
                ) if self.s.store.path(path).exists() else None
                self.db.execute("DELETE FROM library_cleanup WHERE path=?", (path,))
            except OSError:
                pass  # Durable queue retries on startup; authorization is revoked immediately.

    def publish(self, id, actor):
        v = self.version(id)
        if v["status"] != "REVIEWED" or not v["snapshot_dir"]:
            raise HTTPException(409, "Owner review required before publishing")
        manifest = json.loads(self.s.store.read(v["snapshot_dir"] + "/manifest.json"))
        meta = v["metadata"]
        with self.db.tx() as c:
            if not c.execute(
                "SELECT 1 FROM versions WHERE id=? AND status='REVIEWED' AND snapshot_dir=?",
                (id, v["snapshot_dir"]),
            ).fetchone():
                raise HTTPException(409, "Publication already changed")
            for n in manifest["nodes"]:
                keys = (
                    "id",
                    "version_id",
                    "document_id",
                    "parent_id",
                    "kind",
                    "title",
                    "start_order",
                    "end_order",
                    "start_page",
                    "end_page",
                    "content_file",
                )
                c.execute(
                    "INSERT INTO published_nodes VALUES("
                    + ",".join("?" for _ in range(12))
                    + ")",
                    tuple(n[k] for k in keys) + (js(n["metadata"]),),
                )
                # Whole hierarchy is addressable, but index only the most specific actual nodes to avoid duplicate parent-body hits.
                child = any(x["parent_id"] == n["id"] for x in manifest["nodes"])
                body = self.s.store.read(n["content_file"]).decode()
                if child:
                    # Keep direct parent/front-matter text searchable, without repeating descendant bodies.
                    elements = manifest.get("elements", [])
                    own = [
                        e
                        for e in elements
                        if e["file_id"] == n["metadata"].get("file_id")
                        and n["start_order"] <= e["ordinal"] <= n["end_order"]
                        and not any(
                            x["parent_id"] == n["id"]
                            and x["start_order"] <= e["ordinal"] <= x["end_order"]
                            for x in manifest["nodes"]
                        )
                    ]
                    body = "\n".join(
                        transcribed_search_text(e["metadata"]) for e in own
                    )
                if n["kind"] in ("exam", "exercise_collection"):
                    body += "\n" + "".join(
                        self.s.store.read(f["content_file"]).decode()
                        for f in manifest.get("files", [])
                        if f["role"] == "solution"
                    )
                c.execute(
                    "INSERT INTO library_fts VALUES(?,?,?,?)",
                    (n["id"], id, n["title"], body),
                )
            for a in manifest["assets"]:
                keys = (
                    "id",
                    "version_id",
                    "document_id",
                    "node_id",
                    "pdf_page",
                    "type",
                    "file",
                    "file_id",
                    "ordinal",
                )
                c.execute(
                    "INSERT INTO published_assets("
                    + ",".join(keys)
                    + ",metadata) VALUES("
                    + ",".join("?" for _ in range(10))
                    + ")",
                    tuple(a[k] for k in keys) + (js(a["metadata"]),),
                )
            for p in manifest.get("pages", []):
                keys = (
                    "file_id",
                    "version_id",
                    "document_id",
                    "pdf_page",
                    "printed_page",
                    "image_file",
                    "json_file",
                    "content_file",
                    "status",
                )
                c.execute(
                    "INSERT INTO published_pages("
                    + ",".join(keys)
                    + ",quality,languages) VALUES("
                    + ",".join("?" for _ in range(11))
                    + ")",
                    tuple(p[k] for k in keys) + (js(p["quality"]), js(p["languages"])),
                )
            for p in manifest.get("parts", []):
                c.execute(
                    "INSERT INTO published_parts VALUES(?,?,?,?,?,?)",
                    (
                        p["id"],
                        p["node_id"],
                        p["version_id"],
                        p["part_index"],
                        p["content_file"],
                        js(p["metadata"]),
                    ),
                )
            for e in manifest.get("elements", []):
                c.execute(
                    "INSERT INTO published_elements VALUES(?,?,?,?,?,?,?,?)",
                    (
                        e["id"],
                        id,
                        e["file_id"],
                        e["ordinal"],
                        e["type"],
                        e["pdf_page"],
                        js(e["metadata"]),
                        e.get("asset_id"),
                    ),
                )
            for f in manifest.get("files", []):
                c.execute(
                    "INSERT INTO published_files VALUES(?,?,?,?,?,?,?)",
                    (
                        f["id"],
                        id,
                        v["document_id"],
                        f["role"],
                        f["content_file"],
                        f["source_pdf"],
                        js(f),
                    ),
                )
            c.execute("UPDATE versions SET status='PUBLISHED' WHERE id=?", (id,))
            c.execute(
                "UPDATE documents SET published_version=?,status='ACTIVE',title=?,kind=?,subject=?,track=?,year=?,source=?,metadata=? WHERE id=?",
                (
                    id,
                    meta["title"],
                    meta["kind"],
                    meta["subject"],
                    meta["track"],
                    meta.get("year"),
                    meta.get("source", ""),
                    js(meta),
                    v["document_id"],
                ),
            )
        self.cache.clear()
        self.db.audit(actor, "document.publish", v["document_id"], {"version": id})
        return self.get_doc(v["document_id"], True)
