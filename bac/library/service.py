from pathlib import Path
import hashlib, json, re, time
from fastapi import HTTPException
from bac.core.db import uid, js
from bac.vendor.bookforge.library.uploads import register_pdf


def suggest_kind(filename):
    if re.search(r"فرض|اختبار|بكالوريا|exam|bac\b", filename, re.I):
        return "exam"
    if re.search(r"تمارين|exercices|exercises", filename, re.I):
        return "exercise_collection"
    if re.search(r"ملخص|قوانين|summary|formula", filename, re.I):
        return "reference"
    return "book"


class Library:
    def __init__(self, s):
        self.s = s
        self.db = s.db
        self.cache = {}

    def get_doc(self, id, published=False):
        d = self.db.one("SELECT * FROM documents WHERE id=?", (id,))
        if not d or (
            published and (d["status"] != "ACTIVE" or not d["published_version"])
        ):
            raise HTTPException(404, "Published document not found")
        return d

    def upload(self, path, filename, metadata, actor, document_id=None):
        raw, duplicate = register_pdf(
            path,
            filename,
            self.s.extraction_db,
            self.s.extraction_store,
            self.s.extraction_settings,
        )
        with self.db.tx() as c:
            if document_id:
                d = c.execute(
                    "SELECT * FROM documents WHERE id=?", (document_id,)
                ).fetchone()
                if not d or d["status"] == "DELETED":
                    raise HTTPException(404, "Document not found")
                seq = c.execute(
                    "SELECT coalesce(max(sequence),0)+1 FROM versions WHERE document_id=?",
                    (document_id,),
                ).fetchone()[0]
                doc_id = document_id
            else:
                doc_id = uid("doc")
                seq = 1
                c.execute(
                    "INSERT INTO documents(id,title,kind,subject,track,year,source,owner_id,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        doc_id,
                        metadata["title"] or raw["title"],
                        metadata["kind"],
                        metadata["subject"],
                        metadata["track"],
                        metadata.get("year"),
                        metadata.get("source", ""),
                        actor,
                        time.time(),
                    ),
                )
            version = uid("version")
            c.execute(
                "INSERT INTO versions(id,document_id,sequence,bookforge_id,created_at) VALUES(?,?,?,?,?)",
                (version, doc_id, seq, raw["id"], time.time()),
            )
        self.db.audit(
            actor,
            "document.upload",
            doc_id,
            {
                "version": version,
                "kind": metadata["kind"],
                "duplicate_source": duplicate,
            },
        )
        return {
            "document_id": doc_id,
            "version_id": version,
            "pdf_pages": raw["page_count"],
            "duplicate_source": duplicate,
            "suggested_kind": suggest_kind(filename),
        }

    def version(self, id):
        v = self.db.one("SELECT * FROM versions WHERE id=?", (id,))
        if not v:
            raise HTTPException(404, "Version not found")
        raw = self.s.extraction_db.one(
            "SELECT * FROM books WHERE id=?", (v["bookforge_id"],)
        )
        pages = self.s.extraction_db.rows(
            "SELECT id,pdf_page,status,error,quality,printed_page FROM pages WHERE book_id=? ORDER BY pdf_page",
            (v["bookforge_id"],),
        )
        return {
            **v,
            "extraction_status": raw["status"],
            "pages": [{**p, "quality": json.loads(p["quality"])} for p in pages],
        }

    def process(self, id, actor):
        v = self.version(id)
        if v["status"] in ("REVIEWED", "PUBLISHED"):
            raise HTTPException(
                409, "Create a new version before reprocessing approved content"
            )
        row = self.db.one(
            "SELECT m.* FROM active_models a JOIN model_configs m ON m.id=a.config_id WHERE a.slot='extraction'"
        )
        if not row:
            raise HTTPException(409, "Configure the extraction model first")
        cfg = json.loads(row["config"])
        vault = self.s.extraction_engine.vault
        try:
            run = self.s.extraction_queue.start(
                [v["bookforge_id"]],
                cfg,
                self.s.vault.decrypt(row["encrypted_key"]),
                vault,
                self.s.settings.extraction_workers,
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
        self.db.execute("UPDATE versions SET status='PROCESSING' WHERE id=?", (id,))
        self.db.audit(actor, "document.process", id)
        return {"run_id": run, "version_id": id}

    def review(self, id, actor, acknowledge_issues, notes):
        v = self.version(id)
        if v["status"] == "PUBLISHED":
            raise HTTPException(409, "Published version is immutable")
        if not v["extraction_status"].startswith("COMPLETED"):
            raise HTTPException(409, "Wait for extraction completion")
        issues = [p for p in v["pages"] if p["status"] in ("FAILED", "NEEDS_REVIEW")]
        if issues and not acknowledge_issues:
            raise HTTPException(
                409, "Explicitly acknowledge extraction issues before approving"
            )
        book = self.s.extraction_db.one(
            "SELECT * FROM books WHERE id=?", (v["bookforge_id"],)
        )
        prefix = "snapshots/" + id + "/" + uid("review")
        nodes = []
        assets = []
        raw_nodes = self.s.extraction_db.rows(
            "SELECT * FROM nodes WHERE book_id=? ORDER BY start_order", (book["id"],)
        )
        mapping = {
            n["id"]: id + ":" + hashlib.sha256(n["id"].encode()).hexdigest()[:16]
            for n in raw_nodes
        }
        raw_elements = self.s.extraction_db.rows(
            "SELECT * FROM elements WHERE book_id=? ORDER BY ordinal", (book["id"],)
        )
        page_lookup = {p["id"]: p["pdf_page"] for p in v["pages"]}
        for e in raw_elements:
            if not e["asset_file"]:
                continue
            payload = json.loads(e["payload"])
            aid = id + ":asset:" + hashlib.sha256(e["id"].encode()).hexdigest()[:16]
            target = prefix + "/assets/" + aid.split(":")[-1] + ".png"
            self.s.store.write(target, self.s.extraction_store.read(e["asset_file"]))
            owners = [
                n
                for n in raw_nodes
                if n["start_order"] <= e["ordinal"] <= n["end_order"]
            ]
            parent = max(owners, key=lambda n: n["start_order"]) if owners else None
            assets.append(
                {
                    "id": aid,
                    "version_id": id,
                    "document_id": v["document_id"],
                    "node_id": mapping[parent["id"]] if parent else None,
                    "pdf_page": page_lookup[e["page_id"]],
                    "type": e["type"],
                    "file": target,
                    "metadata": {
                        **payload,
                        "source_element_id": e["id"],
                        "ordinal": e["ordinal"],
                        "extraction_version": id,
                    },
                }
            )
        for n in raw_nodes:
            nid = mapping[n["id"]]
            content = self.s.extraction_store.read(n["content_file"]).decode()
            for e in raw_elements:
                if (
                    not e["asset_file"]
                    or not n["start_order"] <= e["ordinal"] <= n["end_order"]
                ):
                    continue
                aid = id + ":asset:" + hashlib.sha256(e["id"].encode()).hexdigest()[:16]
                filename = (
                    e["page_id"].split(":")[-1] + "_" + Path(e["asset_file"]).name
                )
                content = content.replace(
                    "](assets/" + filename + ")", "](/api/library/assets/" + aid + ")"
                )
            path = prefix + "/nodes/" + nid.split(":")[-1] + "/content.md"
            self.s.store.write(path, content.encode())
            metadata = json.loads(self.s.extraction_store.read(n["metadata_file"]))
            metadata.update(
                {
                    "source_node_id": n["id"],
                    "extraction_version": id,
                    "review_state": "OWNER_APPROVED",
                    "warnings": [
                        {
                            "pdf_page": p["pdf_page"],
                            "status": p["status"],
                            "quality": p["quality"],
                        }
                        for p in issues
                    ],
                }
            )
            nodes.append(
                {
                    **{
                        k: n[k]
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
                    "version_id": id,
                    "document_id": v["document_id"],
                    "parent_id": mapping.get(n["parent_id"]),
                    "content_file": path,
                    "metadata": metadata,
                }
            )
        pages = []
        for p in self.s.extraction_db.rows(
            "SELECT * FROM pages WHERE book_id=? ORDER BY pdf_page", (book["id"],)
        ):
            original = (
                f"library/{book['id']}/pages/page_{p['pdf_page']:04d}/original.png"
            )
            target = prefix + f"/pages/{p['pdf_page']:04d}.png"
            if self.s.extraction_store.path(original).exists():
                self.s.store.write(target, self.s.extraction_store.read(original))
            pages.append(
                {
                    "pdf_page": p["pdf_page"],
                    "printed_page": p["printed_page"],
                    "status": p["status"],
                    "quality": json.loads(p["quality"]),
                    "file": target if self.s.store.path(target).exists() else None,
                }
            )
        self.s.store.write(
            prefix + "/manifest.json",
            js(
                {
                    "nodes": nodes,
                    "assets": assets,
                    "pages": pages,
                    "source_pdf": book["source_file"],
                    "issues": issues,
                }
            ).encode(),
        )
        self.db.execute(
            "UPDATE versions SET status='REVIEWED',snapshot_dir=?,reviewer_id=?,reviewed_at=?,review_notes=?,warnings=? WHERE id=?",
            (prefix, actor, time.time(), notes, js(issues), id),
        )
        self.db.audit(
            actor, "document.review", id, {"acknowledged_issues": len(issues)}
        )
        return {"version_id": id, "status": "REVIEWED", "warnings": issues}

    def publish(self, id, actor):
        v = self.version(id)
        if v["status"] != "REVIEWED" or not v["snapshot_dir"]:
            raise HTTPException(409, "Owner review is required before publishing")
        doc = self.get_doc(v["document_id"])
        manifest = json.loads(self.s.store.read(v["snapshot_dir"] + "/manifest.json"))
        with self.db.tx() as c:
            for n in manifest["nodes"]:
                c.execute(
                    "INSERT INTO published_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(
                        n[k]
                        for k in (
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
                    )
                    + (js(n["metadata"]),),
                )
                c.execute(
                    "INSERT INTO library_fts VALUES(?,?,?,?)",
                    (
                        n["id"],
                        id,
                        n["title"],
                        self.s.store.read(n["content_file"]).decode(),
                    ),
                )
            for a in manifest["assets"]:
                c.execute(
                    "INSERT INTO published_assets VALUES(?,?,?,?,?,?,?,?)",
                    tuple(
                        a[k]
                        for k in (
                            "id",
                            "version_id",
                            "document_id",
                            "node_id",
                            "pdf_page",
                            "type",
                            "file",
                        )
                    )
                    + (js(a["metadata"]),),
                )
            c.execute("UPDATE versions SET status='PUBLISHED' WHERE id=?", (id,))
            c.execute(
                "UPDATE documents SET published_version=?,status='ACTIVE' WHERE id=?",
                (id, doc["id"]),
            )
        self.cache.clear()
        self.db.audit(actor, "document.publish", doc["id"], {"version": id})
        return self.get_doc(doc["id"], True)

    def list_documents(self, filters=None):
        query = "SELECT * FROM documents WHERE status='ACTIVE' AND published_version IS NOT NULL"
        params = []
        for key, value in (filters or {}).items():
            if key in ("subject", "track", "kind", "year") and value:
                query += " AND " + key + "=?"
                params.append(value)
        return self.db.rows(query + " ORDER BY title LIMIT 100", params)

    def nodes(self, doc_id, kind=None):
        d = self.get_doc(doc_id, True)
        sql = "SELECT id,parent_id,kind,title,start_page,end_page FROM published_nodes WHERE version_id=?"
        params = [d["published_version"]]
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        return self.db.rows(sql + " ORDER BY start_order LIMIT 300", params)

    def node(self, id, include_content=True):
        n = self.db.one(
            "SELECT n.* FROM published_nodes n JOIN documents d ON d.id=n.document_id WHERE n.id=? AND d.status='ACTIVE' AND d.published_version=n.version_id",
            (id,),
        )
        if not n:
            raise HTTPException(404, "Published node not found")
        d = self.get_doc(n["document_id"], True)
        key = (id, d["published_version"])
        if key not in self.cache:
            if len(self.cache) > 100:
                self.cache.clear()
            self.cache[key] = self.s.store.read(n["content_file"]).decode()
        ancestors = []
        parent = n["parent_id"]
        while parent:
            p = self.db.one(
                "SELECT id,parent_id,kind,title,start_page,end_page FROM published_nodes WHERE id=?",
                (parent,),
            )
            if not p:
                break
            ancestors.append(p)
            parent = p["parent_id"]
        assets = [
            {
                **a,
                "metadata": json.loads(a["metadata"]),
                "asset_url": "/api/library/assets/" + a["id"],
            }
            for a in self.db.rows(
                "SELECT * FROM published_assets WHERE version_id=? ORDER BY pdf_page",
                (n["version_id"],),
            )
        ]
        assets = [
            a
            for a in assets
            if n["start_order"] <= a["metadata"]["ordinal"] <= n["end_order"]
        ]
        children = self.db.rows(
            "SELECT id,kind,title,start_page,end_page FROM published_nodes WHERE parent_id=? ORDER BY start_order",
            (id,),
        )
        return {
            "node": {**n, "metadata": json.loads(n["metadata"])},
            "document": d,
            "ancestors": ancestors,
            "children": children,
            "content": self.cache[key] if include_content else None,
            "assets": assets,
            "sources": [
                {
                    "document_id": d["id"],
                    "title": d["title"],
                    "node_id": id,
                    "version_id": n["version_id"],
                    "pages": list(range(n["start_page"], n["end_page"] + 1)),
                    "review_state": "OWNER_APPROVED",
                }
            ],
        }

    def search(self, q, filters=None):
        terms = re.findall(r"\w+", q)[:20]
        if not terms:
            return []
        sql = "SELECT f.node_id,n.document_id,n.kind,n.title,n.start_page,n.end_page,n.version_id,snippet(library_fts,3,'','','…',25) AS snippet,-bm25(library_fts) AS score FROM library_fts f JOIN published_nodes n ON n.id=f.node_id JOIN documents d ON d.id=n.document_id WHERE library_fts MATCH ? AND d.status='ACTIVE' AND d.published_version=n.version_id"
        args = [" AND ".join('"' + t + '"' for t in terms)]
        for key, value in (filters or {}).items():
            if key in ("subject", "track", "kind", "year", "document_id") and value:
                sql += " AND " + ("d.id" if key == "document_id" else "d." + key) + "=?"
                args.append(value)
        return self.db.rows(sql + " ORDER BY score DESC LIMIT 12", args)
