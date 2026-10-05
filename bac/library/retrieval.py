"""Publication-scoped hierarchical reads and atomic exam/exercise bundles."""

import hashlib, json, re
from fastapi import HTTPException
from bac.core.db import js
from bac.core.study import TRACKS, SUBJECTS, aliases, resolve
from bac.library.parts import legacy_blocks, TARGET_CHARS


class Reader:
    def list_documents(self, filters=None):
        query = "SELECT * FROM documents WHERE status='ACTIVE' AND published_version IS NOT NULL"
        params = []
        query, params = self._filters(query, params, filters, "")
        return [
            {**d, "metadata": json.loads(d["metadata"])}
            for d in self.db.rows(query + " ORDER BY title LIMIT 100", params)
        ]

    def _filters(self, sql, args, filters, prefix="d."):
        if getattr(self, "study_scope", None):
            sql, args = self.study_scope.sql(sql, args, prefix)
        for key, value in (filters or {}).items():
            if not value:
                continue
            if key in ("subject", "track") and (
                code := resolve(SUBJECTS if key == "subject" else TRACKS, value)
            ):
                values = aliases(SUBJECTS if key == "subject" else TRACKS, code)
                sql += (
                    " AND lower(trim("
                    + prefix
                    + key
                    + ")) IN ("
                    + ",".join("?" for _ in values)
                    + ")"
                )
                args.extend(x.casefold() for x in values)
            elif key in ("subject", "track", "kind", "year"):
                sql += " AND " + prefix + key + "=?"
                args.append(value)
            elif key == "document_id":
                sql += " AND " + prefix + "id=?"
                args.append(value)
            elif key in ("session", "exam_type", "institution", "source"):
                sql += " AND json_extract(" + prefix + "metadata,'$." + key + "')=?"
                args.append(value)
        return sql, args

    def nodes(self, doc_id, kind=None):
        d = self.get_doc(doc_id, True)
        sql = "SELECT id,parent_id,kind,title,start_page,end_page FROM published_nodes WHERE version_id=?"
        args = [d["published_version"]]
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        return self.db.rows(sql + " ORDER BY start_order,id LIMIT 300", args)

    def _node(self, id):
        n = self.db.one(
            "SELECT n.* FROM published_nodes n JOIN documents d ON d.id=n.document_id WHERE n.id=? AND d.status='ACTIVE' AND d.published_version=n.version_id",
            (id,),
        )
        if not n:
            raise HTTPException(404, "Published node not found")
        self.get_doc(n["document_id"], True)
        n["metadata"] = json.loads(n["metadata"])
        return n

    def _source(self, n, pages=None, file_id=None, source_id=None, role="primary"):
        return {
            "document_id": n["document_id"],
            "title": self.get_doc(n["document_id"], True)["title"],
            "node_id": n["id"],
            "version_id": n["version_id"],
            "file_id": file_id
            or n["metadata"].get("file_id", n["version_id"] + ":primary"),
            "source_id": source_id or n["id"],
            "role": role,
            "pages": pages or list(range(n["start_page"], n["end_page"] + 1)),
            "review_state": "OWNER_APPROVED",
        }

    def _assets(self, n, file_id=None, start=None, end=None, all_files=False):
        sql = "SELECT * FROM published_assets WHERE version_id=?"
        args = [n["version_id"]]
        if not all_files:
            sql += " AND file_id=? AND ordinal BETWEEN ? AND ?"
            args.extend(
                [
                    file_id
                    or n["metadata"].get("file_id", n["version_id"] + ":primary"),
                    start if start is not None else n["start_order"],
                    end if end is not None else n["end_order"],
                ]
            )
        return [
            {
                **a,
                "metadata": json.loads(a["metadata"]),
                "asset_url": "/api/library/assets/" + a["id"],
            }
            for a in self.db.rows(sql + " ORDER BY file_id,ordinal", args)
        ]

    def node(self, id, include_content=True):
        n = self._node(id)
        ancestors = []
        parent = n["parent_id"]
        seen = set()
        while parent and parent not in seen:
            seen.add(parent)
            p = self.db.one(
                "SELECT id,parent_id,kind,title,start_page,end_page FROM published_nodes WHERE id=? AND version_id=?",
                (parent, n["version_id"]),
            )
            if not p:
                break
            ancestors.append(p)
            parent = p["parent_id"]
        result = {
            "node": n,
            "document": self.get_doc(n["document_id"], True),
            "ancestors": ancestors,
            "children": self.db.rows(
                "SELECT id,kind,title,start_page,end_page FROM published_nodes WHERE parent_id=? ORDER BY start_order",
                (id,),
            ),
            "content": self.cache.read(n["content_file"], self.s.store)
            if include_content
            else None,
            "assets": self._assets(n),
            "sources": [self._source(n)],
        }
        if include_content:
            result.update(self.materials(n))
        return result

    def materials(self, n):
        items = self.db.rows(
            "SELECT * FROM published_elements WHERE version_id=? AND file_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal",
            (
                n["version_id"],
                n["metadata"].get("file_id", n["version_id"] + ":primary"),
                n["start_order"],
                n["end_order"],
            ),
        )
        items = [{**e, "metadata": json.loads(e["metadata"])} for e in items]
        return {
            plural: [e for e in items if e["type"] in kinds]
            for plural, kinds in [
                ("figures", ("figure", "image", "diagram")),
                ("tables", ("table",)),
                ("equations", ("equation",)),
            ]
        }

    def parts(self, id):
        n = self._node(id)
        if n["kind"] != "lesson":
            raise HTTPException(
                422, "Only actual lessons have retrieval parts; bundles stay whole"
            )
        rows = self.db.rows(
            "SELECT * FROM published_parts WHERE node_id=? ORDER BY part_index", (id,)
        )
        if not rows:
            # Derive safe blocks from approved v1 Markdown only; never mutable raw pages.
            text = self.cache.read(n["content_file"], self.s.store)
            blocks = legacy_blocks(text, n["start_page"])
            groups = []
            group = []
            size = 0
            for block, page in blocks:
                if group and size + len(block) > TARGET_CHARS:
                    groups.append(group)
                    group = []
                    size = 0
                group.append((block, page))
                size += len(block) + 2
            if group:
                groups.append(group)
            pending = []
            for i, group in enumerate(groups):
                body = "\n\n".join(b for b, _ in group)
                digest = hashlib.sha256(js([id, i, body]).encode()).hexdigest()[:24]
                pid = id + ":part:" + digest
                path = "derived/" + n["version_id"] + "/parts/" + digest + ".md"
                self.s.store.write(path, body.encode())
                pages = sorted({p for _, p in group})
                meta = {
                    "title": n["title"],
                    "file_id": n["metadata"].get(
                        "file_id", n["version_id"] + ":primary"
                    ),
                    "pages": pages,
                    "content_chars": len(body),
                    "boundary": "approved_markdown_blocks",
                    "complete_lesson": len(groups) == 1,
                }
                pending.append((pid, id, n["version_id"], i, path, js(meta)))
            with self.db.tx() as c:
                for row in pending:
                    c.execute(
                        "INSERT OR IGNORE INTO published_parts VALUES(?,?,?,?,?,?)", row
                    )
            rows = self.db.rows(
                "SELECT * FROM published_parts WHERE node_id=? ORDER BY part_index",
                (id,),
            )
        return [
            {
                k: v
                for k, v in {**p, "metadata": json.loads(p["metadata"])}.items()
                if k != "content_file"
            }
            for p in rows
        ]

    def part(self, id):
        p = self.db.one("SELECT * FROM published_parts WHERE id=?", (id,))
        if not p:
            raise HTTPException(404, "Part not found")
        n = self._node(p["node_id"])
        meta = json.loads(p["metadata"])
        payload = self.node(n["id"], False)
        if "start_order" in meta:
            assets = self._assets(
                n, meta["file_id"], meta["start_order"], meta["end_order"]
            )
        else:
            assets = [
                a
                for a in self._assets(n)
                if a["id"] in self.cache.read(p["content_file"], self.s.store)
            ]
        return {
            **payload,
            "part": {
                k: v for k, v in {**p, "metadata": meta}.items() if k != "content_file"
            },
            "content": self.cache.read(p["content_file"], self.s.store),
            "assets": assets,
            "sources": [self._source(n, meta["pages"], meta["file_id"], id)],
        }

    def bundle(self, id, kind=None):
        payload = self.node(id)
        n = payload["node"]
        if n["kind"] not in ("exam", "exercise_collection") or (
            kind and n["kind"] != kind
        ):
            raise HTTPException(422, "Requested node is not this bundle mode")
        files = [
            {**f, "metadata": json.loads(f["metadata"])}
            for f in self.db.rows(
                "SELECT * FROM published_files WHERE version_id=? ORDER BY role",
                (n["version_id"],),
            )
        ]
        primary = next((f for f in files if f["role"] == "primary"), None)
        solution = next((f for f in files if f["role"] == "solution"), None)
        payload["atomic_bundle"] = True
        payload["extraction_complete"] = all(
            f["metadata"].get("extraction_complete", True) for f in files
        )
        payload["solution_status"] = "owner_verified" if solution else "not_available"
        payload["files"] = [
            {k: v for k, v in f.items() if k not in ("content_file", "source_pdf")}
            for f in files
        ]
        payload["solution"] = None
        payload["assets"] = self._assets(n, all_files=True)
        if solution:
            meta = solution["metadata"]
            payload["solution"] = {
                "file_id": solution["id"],
                "content": self.cache.read(solution["content_file"], self.s.store),
                "provenance": meta["metadata"],
                "verification": meta["verification"],
                "evidence": meta["evidence"],
                "verified_at": meta["verified_at"],
                "verified_by": meta["verified_by"],
            }
            payload["sources"].append(
                self._source(
                    n,
                    meta["selected_pages"],
                    solution["id"],
                    n["id"] + ":solution",
                    "solution",
                )
            )
        if primary:
            payload["sources"][0] = self._source(
                n, primary["metadata"]["selected_pages"], primary["id"]
            )
        payload["warning"] = (
            "An owner-verified supplied solution is not an AI-certified official solution. No missing solution is invented."
        )
        return payload

    def search(self, q, filters=None):
        terms = re.findall(r"\w+", q)[:20]
        if not terms:
            return []
        sql = "SELECT f.node_id,n.document_id,n.kind,n.title,n.start_page,n.end_page,n.version_id,d.kind AS document_kind,d.subject,d.track,d.year,snippet(library_fts,3,'','','…',25) AS snippet,-bm25(library_fts,0,0,4,1) AS score FROM library_fts f JOIN published_nodes n ON n.id=f.node_id JOIN documents d ON d.id=n.document_id WHERE library_fts MATCH ? AND d.status='ACTIVE' AND d.published_version=n.version_id"
        args = [" AND ".join('"' + t + '"' for t in terms)]
        sql, args = self._filters(sql, args, filters)
        return self.db.rows(sql + " ORDER BY score DESC,n.start_order LIMIT 12", args)

    def source_page(self, document_id, page, file_id=None, format="image"):
        d = self.get_doc(document_id, True)
        fid = file_id or d["published_version"] + ":primary"
        p = self.db.one(
            "SELECT * FROM published_pages WHERE version_id=? AND document_id=? AND file_id=? AND pdf_page=?",
            (d["published_version"], document_id, fid, page),
        )
        if p:
            p["quality"] = json.loads(p["quality"])
            p["languages"] = json.loads(p["languages"])
            if format == "json":
                if not p["json_file"]:
                    raise HTTPException(404, "Structured page unavailable")
                return {
                    "page": {k: v for k, v in p.items() if not k.endswith("_file")},
                    "json": json.loads(self.s.store.read(p["json_file"])),
                    "content": self.cache.read(p["content_file"], self.s.store),
                }
            if not p["image_file"]:
                raise HTTPException(404, "Source page image unavailable")
            return p["image_file"]
        # Old approved snapshots remain readable but JSON was not frozen in phase 1.
        if fid != d["published_version"] + ":primary":
            raise HTTPException(404, "Source file not found")
        v = self.db.one(
            "SELECT snapshot_dir FROM versions WHERE id=?", (d["published_version"],)
        )
        manifest = json.loads(self.s.store.read(v["snapshot_dir"] + "/manifest.json"))
        if manifest.get("schema_version") == 2 or format != "image":
            raise HTTPException(404, "Published page unavailable")
        p = next((p for p in manifest["pages"] if p["pdf_page"] == page), None)
        if not p or not p.get("file"):
            raise HTTPException(404, "Source page unavailable")
        return p["file"]

    def asset(self, id):
        a = self.db.one(
            "SELECT a.* FROM published_assets a JOIN documents d ON d.id=a.document_id WHERE a.id=? AND d.status='ACTIVE' AND d.published_version=a.version_id",
            (id,),
        )
        if not a:
            raise HTTPException(404, "Published asset not found")
        self.get_doc(a["document_id"], True)
        a["metadata"] = json.loads(a["metadata"])
        return a
