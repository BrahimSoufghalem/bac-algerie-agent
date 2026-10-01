"""Owner lifecycle. Published snapshots never depend on mutable extraction artifacts."""

import hashlib, json, re, time
from fastapi import HTTPException
from bac.core.db import uid, js
from bac.library.contracts import (
    DocumentMetadata,
    SolutionMetadata,
    PageRange,
    SolutionVerification,
)
from bac.library.snapshots import frozen_snapshot
from bac.library.retrieval import Reader
from bac.vendor.bookforge.library.uploads import register_pdf


def suggest_kind(filename):
    if re.search(r"فرض|اختبار|بكالوريا|exam|bac\b", filename, re.I):
        return "exam"
    if re.search(r"تمارين|exercices|exercises", filename, re.I):
        return "exercise_collection"
    if re.search(r"ملخص|قوانين|summary|formula", filename, re.I):
        return "reference"
    return "book"


class Library(Reader):
    def __init__(self, s):
        self.s = s
        self.db = s.db
        self.cache = s.library_cache

    def get_doc(self, id, published=False):
        d = self.db.one("SELECT * FROM documents WHERE id=?", (id,))
        if not d or (
            published and (d["status"] != "ACTIVE" or not d["published_version"])
        ):
            raise HTTPException(404, "Published document not found")
        d["metadata"] = json.loads(d["metadata"])
        return d

    def upload(self, path, filename, metadata, actor, document_id=None):
        meta = DocumentMetadata.model_validate(metadata).model_dump()
        raw, duplicate = register_pdf(
            path,
            filename,
            self.s.extraction_db,
            self.s.extraction_store,
            self.s.extraction_settings,
        )
        meta["title"] = meta["title"] or raw["title"]
        with self.db.tx() as c:
            if document_id:
                d = c.execute(
                    "SELECT * FROM documents WHERE id=? AND status!='DELETED'",
                    (document_id,),
                ).fetchone()
                if not d:
                    raise HTTPException(404, "Document not found")
                doc_id = document_id
                seq = c.execute(
                    "SELECT coalesce(max(sequence),0)+1 FROM versions WHERE document_id=?",
                    (doc_id,),
                ).fetchone()[0]
            else:
                doc_id = uid("doc")
                seq = 1
                c.execute(
                    "INSERT INTO documents(id,title,kind,subject,track,year,source,owner_id,created_at,metadata) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        doc_id,
                        meta["title"],
                        meta["kind"],
                        meta["subject"],
                        meta["track"],
                        meta["year"],
                        meta["source"],
                        actor,
                        time.time(),
                        js(meta),
                    ),
                )
            vid = uid("version")
            c.execute(
                "INSERT INTO versions(id,document_id,sequence,bookforge_id,created_at,metadata) VALUES(?,?,?,?,?,?)",
                (vid, doc_id, seq, raw["id"], time.time(), js(meta)),
            )
            c.execute(
                "INSERT INTO version_files(id,version_id,bookforge_id,role,last_page) VALUES(?,?,?,'primary',?)",
                (vid + ":primary", vid, raw["id"], raw["page_count"]),
            )
        self.db.audit(
            actor,
            "document.upload",
            doc_id,
            {"version": vid, "kind": meta["kind"], "duplicate_source": duplicate},
        )
        return {
            "document_id": doc_id,
            "version_id": vid,
            "pdf_pages": raw["page_count"],
            "duplicate_source": duplicate,
            "suggested_kind": suggest_kind(filename),
        }

    def version(self, id):
        v = self.db.one("SELECT * FROM versions WHERE id=?", (id,))
        if not v:
            raise HTTPException(404, "Version not found")
        v["metadata"] = json.loads(v["metadata"])
        files = []
        if v["status"] in ("REVIEWED", "PUBLISHED") and v["snapshot_dir"]:
            manifest = json.loads(
                self.cache.read(v["snapshot_dir"] + "/manifest.json", self.s.store)
            )
            if manifest.get("schema_version") == 2:
                for f in manifest["files"]:
                    pages = [
                        {**p, "error": None}
                        for p in manifest["pages"]
                        if p["file_id"] == f["id"]
                    ]
                    files.append({**f, "pages": pages})
                primary = next(f for f in files if f["role"] == "primary")
                return {
                    **v,
                    "files": files,
                    "extraction_status": primary["extraction_status"],
                    "pages": primary["pages"],
                }
        for f in self.db.rows(
            "SELECT * FROM version_files WHERE version_id=? ORDER BY role", (id,)
        ):
            raw = self.s.extraction_db.one(
                "SELECT * FROM books WHERE id=?", (f["bookforge_id"],)
            )
            f["metadata"] = json.loads(f["metadata"])
            f["last_page"] = f["last_page"] or raw["page_count"]
            f.update(
                filename=raw["filename"],
                sha256=raw["sha256"],
                page_count=raw["page_count"],
                extraction_status=raw["status"],
            )
            f["pages"] = [
                {**p, "quality": json.loads(p["quality"])}
                for p in self.s.extraction_db.rows(
                    "SELECT id,pdf_page,status,error,quality,printed_page FROM pages WHERE book_id=? AND pdf_page BETWEEN ? AND ? ORDER BY pdf_page",
                    (raw["id"], f["first_page"], f["last_page"]),
                )
            ]
            files.append(f)
        primary = next(f for f in files if f["role"] == "primary")
        return {
            **v,
            "files": files,
            "extraction_status": primary["extraction_status"],
            "pages": primary["pages"],
        }

    def approved_page(self, v, file_id, page):
        if v["status"] not in ("REVIEWED", "PUBLISHED") or not v["snapshot_dir"]:
            return None
        manifest = json.loads(
            self.cache.read(v["snapshot_dir"] + "/manifest.json", self.s.store)
        )
        fid = file_id or v["id"] + ":primary"
        p = next(
            (
                p
                for p in manifest["pages"]
                if p["pdf_page"] == page
                and p.get("file_id", v["id"] + ":primary") == fid
            ),
            None,
        )
        if not p:
            raise HTTPException(404, "Approved page not found")
        return {**p, "image_file": p.get("image_file", p.get("file"))}

    def _editable(self, c, id):
        v = c.execute("SELECT * FROM versions WHERE id=?", (id,)).fetchone()
        if not v:
            raise HTTPException(404, "Version not found")
        if v["status"] in ("REVIEWED", "PUBLISHED"):
            raise HTTPException(409, "Create a new version to change approved content")
        for f in c.execute(
            "SELECT bookforge_id FROM version_files WHERE version_id=?", (id,)
        ):
            raw = self.s.extraction_db.one(
                "SELECT status FROM books WHERE id=?", (f[0],)
            )
            if raw["status"] == "PROCESSING":
                raise HTTPException(
                    409, "Wait for extraction completion before editing"
                )
        return dict(v)

    def _changed(self, c, id):
        c.execute(
            "UPDATE versions SET edit_revision=edit_revision+1,status='UPLOADED' WHERE id=?",
            (id,),
        )
        c.execute(
            "UPDATE version_files SET verification='pending',bound_identity=NULL,verified_by=NULL,verified_at=NULL,evidence=NULL WHERE version_id=? AND role='solution'",
            (id,),
        )

    def clone(self, id, actor):
        v = self.version(id)
        with self.db.tx() as c:
            seq = c.execute(
                "SELECT max(sequence)+1 FROM versions WHERE document_id=?",
                (v["document_id"],),
            ).fetchone()[0]
            nid = uid("version")
            c.execute(
                "INSERT INTO versions(id,document_id,sequence,bookforge_id,created_at,metadata) VALUES(?,?,?,?,?,?)",
                (
                    nid,
                    v["document_id"],
                    seq,
                    v["bookforge_id"],
                    time.time(),
                    js(v["metadata"]),
                ),
            )
            for f in v["files"]:
                c.execute(
                    "INSERT INTO version_files(id,version_id,bookforge_id,role,first_page,last_page,metadata,verification) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        nid + ":" + f["role"],
                        nid,
                        f["bookforge_id"],
                        f["role"],
                        f["first_page"],
                        f["last_page"],
                        js(f["metadata"]),
                        "pending" if f["role"] == "solution" else "not_applicable",
                    ),
                )
        self.db.audit(actor, "version.clone", nid, {"from": id})
        return self.version(nid)

    def update_metadata(self, id, metadata, actor):
        meta = DocumentMetadata.model_validate(metadata).model_dump()
        with self.db.tx() as c:
            self._editable(c, id)
            if (
                meta["kind"] not in ("exam", "exercise_collection")
                and c.execute(
                    "SELECT 1 FROM version_files WHERE version_id=? AND role='solution'",
                    (id,),
                ).fetchone()
            ):
                raise HTTPException(
                    409, "Remove the solution before changing the document mode"
                )
            c.execute("UPDATE versions SET metadata=? WHERE id=?", (js(meta), id))
            self._changed(c, id)
        self.db.audit(actor, "version.metadata", id)
        return self.version(id)

    def set_range(self, id, file_id, values, actor):
        span = PageRange.model_validate(values)
        with self.db.tx() as c:
            v = self._editable(c, id)
            if json.loads(v["metadata"])["kind"] == "book":
                raise HTTPException(
                    409, "Book hierarchy requires its complete primary PDF"
                )
            f = c.execute(
                "SELECT * FROM version_files WHERE id=? AND version_id=?", (file_id, id)
            ).fetchone()
            if not f:
                raise HTTPException(404, "Source file not found")
            raw = self.s.extraction_db.one(
                "SELECT page_count FROM books WHERE id=?", (f["bookforge_id"],)
            )
            if span.last_page > raw["page_count"]:
                raise HTTPException(422, "Range exceeds source PDF")
            for other in c.execute(
                "SELECT * FROM version_files WHERE version_id=? AND id!=? AND bookforge_id=?",
                (id, file_id, f["bookforge_id"]),
            ):
                if not (
                    span.last_page < other["first_page"]
                    or span.first_page > (other["last_page"] or raw["page_count"])
                ):
                    raise HTTPException(
                        409, "Primary and solution ranges must not overlap"
                    )
            c.execute(
                "UPDATE version_files SET first_page=?,last_page=? WHERE id=?",
                (span.first_page, span.last_page, file_id),
            )
            self._changed(c, id)
        self.db.audit(actor, "source.range", file_id)
        return self.version(id)

    def attach_solution(
        self, id, metadata, actor, path=None, filename=None, page_range=None
    ):
        meta = SolutionMetadata.model_validate(metadata).model_dump()
        v = self.version(id)
        raw = None
        if path:
            raw, _ = register_pdf(
                path,
                filename,
                self.s.extraction_db,
                self.s.extraction_store,
                self.s.extraction_settings,
            )
        with self.db.tx() as c:
            v = self._editable(c, id)
            if json.loads(v["metadata"])["kind"] not in ("exam", "exercise_collection"):
                raise HTTPException(
                    409, "Solutions belong only to exam/exercise bundles"
                )
            if c.execute(
                "SELECT 1 FROM version_files WHERE version_id=? AND role='solution'",
                (id,),
            ).fetchone():
                raise HTTPException(
                    409, "Remove the draft solution before replacing it"
                )
            primary = c.execute(
                "SELECT * FROM version_files WHERE version_id=? AND role='primary'",
                (id,),
            ).fetchone()
            if not raw:
                raw = self.s.extraction_db.one(
                    "SELECT * FROM books WHERE id=?", (primary["bookforge_id"],)
                )
            span = PageRange.model_validate(
                page_range or {"first_page": 1, "last_page": raw["page_count"]}
            )
            if span.last_page > raw["page_count"]:
                raise HTTPException(422, "Range exceeds PDF")
            if raw["id"] == primary["bookforge_id"] and not (
                span.last_page < primary["first_page"]
                or span.first_page > (primary["last_page"] or raw["page_count"])
            ):
                raise HTTPException(
                    409, "Select disjoint primary/solution page ranges first"
                )
            c.execute(
                "INSERT INTO version_files(id,version_id,bookforge_id,role,first_page,last_page,metadata,verification) VALUES(?,?,?,'solution',?,?,?,'pending')",
                (
                    id + ":solution",
                    id,
                    raw["id"],
                    span.first_page,
                    span.last_page,
                    js(meta),
                ),
            )
            self._changed(c, id)
        self.db.audit(actor, "solution.attach", id)
        return self.version(id)

    def remove_solution(self, id, actor):
        with self.db.tx() as c:
            self._editable(c, id)
            c.execute(
                "DELETE FROM version_files WHERE version_id=? AND role='solution'",
                (id,),
            )
            self._changed(c, id)
        self.db.audit(actor, "solution.remove", id)
        return self.version(id)

    def _identity(self, v, files):
        primary = next(f for f in files if f["role"] == "primary")
        return hashlib.sha256(
            js(
                [
                    v["metadata"],
                    primary["sha256"],
                    primary["first_page"],
                    primary["last_page"],
                ]
            ).encode()
        ).hexdigest()

    def verify_solution(self, id, values, actor):
        p = SolutionVerification.model_validate(values)
        if (
            not p.matching_confirmed
            or not p.source_confirmed
            or len(p.evidence.strip()) < 20
        ):
            raise HTTPException(
                422, "Explicit matching/source confirmation and evidence required"
            )
        with self.db.tx() as c:
            self._editable(c, id)
            v = self.version(id)
            sol = next((f for f in v["files"] if f["role"] == "solution"), None)
            if not sol:
                raise HTTPException(404, "No draft solution")
            for k in ("subject", "track", "year", "session", "exam_type"):
                if v["metadata"].get(k) and v["metadata"][k] != sol["metadata"].get(k):
                    raise HTTPException(409, "Solution identity mismatch: " + k)
            c.execute(
                "UPDATE version_files SET verification='owner_verified',bound_identity=?,verified_by=?,verified_at=?,evidence=? WHERE id=?",
                (
                    self._identity(v, v["files"]),
                    actor,
                    time.time(),
                    p.evidence.strip(),
                    sol["id"],
                ),
            )
            c.execute(
                "UPDATE versions SET edit_revision=edit_revision+1 WHERE id=?", (id,)
            )
        self.db.audit(actor, "solution.verify", id)
        return self.version(id)

    def process(self, id, actor):
        with self.db.tx() as c:
            self._editable(c, id)
            v = self.version(id)
            row = c.execute(
                "SELECT m.* FROM active_models a JOIN model_configs m ON m.id=a.config_id WHERE a.slot='extraction'"
            ).fetchone()
            if not row:
                raise HTTPException(409, "Configure the extraction model first")
            try:
                run = self.s.extraction_queue.start(
                    list(dict.fromkeys(f["bookforge_id"] for f in v["files"])),
                    json.loads(row["config"]),
                    self.s.vault.decrypt(row["encrypted_key"]),
                    self.s.extraction_engine.vault,
                    self.s.settings.extraction_workers,
                )
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            c.execute(
                "UPDATE versions SET status='PROCESSING',edit_revision=edit_revision+1 WHERE id=?",
                (id,),
            )
        self.db.audit(actor, "document.process", id)
        return {"run_id": run, "version_id": id}

    def review(self, id, actor, acknowledge_issues, notes):
        v = self.version(id)
        if v["status"] in ("REVIEWED", "PUBLISHED"):
            raise HTTPException(409, "Approved version is immutable")
        for f in v["files"]:
            if not f["extraction_status"].startswith("COMPLETED"):
                raise HTTPException(409, "Wait for all source files to complete")
            if f["role"] == "solution" and (
                f["verification"] != "owner_verified"
                or f["bound_identity"] != self._identity(v, v["files"])
            ):
                raise HTTPException(
                    409, "Verify the exact solution match before review"
                )
        issues = [
            {**p, "file_id": f["id"], "role": f["role"]}
            for f in v["files"]
            for p in f["pages"]
            if p["status"] in ("FAILED", "NEEDS_REVIEW")
        ]
        if issues and not acknowledge_issues:
            raise HTTPException(
                409, "Explicitly acknowledge extraction issues before approving"
            )
        doc = {
            **self.get_doc(v["document_id"]),
            **v["metadata"],
            "metadata": v["metadata"],
        }
        files = [
            {k: value for k, value in f.items() if k != "pages"} for f in v["files"]
        ]
        prefix, manifest = frozen_snapshot(self.s, v, doc, files, actor, notes)
        with self.db.tx() as c:
            changed = c.execute(
                "UPDATE versions SET status='REVIEWED',snapshot_dir=?,reviewer_id=?,reviewed_at=?,review_notes=?,warnings=? WHERE id=? AND edit_revision=? AND status NOT IN ('REVIEWED','PUBLISHED')",
                (
                    prefix,
                    actor,
                    time.time(),
                    notes,
                    js(manifest["issues"]),
                    id,
                    v["edit_revision"],
                ),
            ).rowcount
            if not changed:
                raise HTTPException(409, "Draft changed during review; review again")
        self.db.audit(
            actor, "document.review", id, {"acknowledged_issues": len(issues)}
        )
        return {"version_id": id, "status": "REVIEWED", "warnings": manifest["issues"]}

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
                        str(
                            e["metadata"].get("text")
                            or e["metadata"].get("latex")
                            or e["metadata"].get("caption")
                            or e["metadata"].get("rows")
                            or ""
                        )
                        for e in own
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
