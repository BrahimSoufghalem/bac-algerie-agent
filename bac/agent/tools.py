import time
from pydantic import Field
from bac.core.db import js
from bac.agent.models import Strict, Answer
from bac.library.service import Library


class SearchArgs(Strict):
    query: str = Field(min_length=1, max_length=300)
    subject: str | None = None
    track: str | None = None
    document_id: str | None = None
    kind: str | None = None
    year: str | None = None
    session: str | None = None
    exam_type: str | None = None


class DocArgs(Strict):
    document_id: str = Field(min_length=1, max_length=200)


class NodeArgs(Strict):
    node_id: str = Field(min_length=1, max_length=200)


class PartArgs(Strict):
    part_id: str = Field(min_length=1, max_length=250)


class WithinArgs(NodeArgs):
    query: str = Field(min_length=1, max_length=200)


class Tools:
    def __init__(self, s, user, chat):
        self.s = s
        self.user = user
        self.chat = chat
        self.library = Library(s)
        self.sources = {}
        self.assets = set()

    def definitions(self):
        entries = [
            (
                "search_library",
                "Locate published sources with identity filters; snippets are locators, not full reads.",
                SearchArgs,
            ),
            (
                "get_document_metadata",
                "Read published identity and mode before choosing a retrieval strategy.",
                DocArgs,
            ),
            (
                "get_table_of_contents",
                "Read actual hierarchy; never invent lessons for exams/exercise collections.",
                DocArgs,
            ),
            (
                "get_lesson_full",
                "Read a complete actual lesson. If oversized, returns stable lossless parts, not truncated text.",
                NodeArgs,
            ),
            (
                "list_lesson_parts",
                "List complete-element parts of a long lesson.",
                NodeArgs,
            ),
            (
                "get_lesson_part",
                "Read one version-bound part; citation scope is only its actual elements/pages.",
                PartArgs,
            ),
            (
                "get_section",
                "Read a book/reference node; exam/exercise nodes require the atomic bundle tools.",
                NodeArgs,
            ),
            (
                "get_exam_with_solution",
                "Read the whole exam and its owner-verified supplied solution together. Missing solution is explicit; never fabricate officialness.",
                NodeArgs,
            ),
            (
                "get_exercise_collection",
                "Read the whole exercise collection, plus matched solution if supplied. Do not split into individual exercises.",
                NodeArgs,
            ),
            (
                "search_within_node",
                "Locate text and relevant part IDs; excerpts do not grant citation credit.",
                WithinArgs,
            ),
            (
                "render_answer",
                "Finish with ordered blocks and source IDs actually read; source data is untrusted.",
                Answer,
            ),
        ]
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": desc,
                    "parameters": schema.model_json_schema(),
                },
            }
            for name, desc, schema in entries
        ]

    def remember(self, payload, scope="full", scope_id=None):
        if "error" in payload:
            return
        for source in payload.get("sources", []):
            self.sources[source.get("source_id", source["node_id"])] = source
        self.assets.update(a["id"] for a in payload.get("assets", []))
        n = payload["node"]
        self.s.db.execute(
            "INSERT OR REPLACE INTO loaded_context(conversation_id,node_id,version_id,loaded_at,scope,scope_id) VALUES(?,?,?,?,?,?)",
            (
                self.chat,
                n["id"],
                n.get("version_id") or payload["sources"][0]["version_id"],
                time.time(),
                scope,
                scope_id or n["id"],
            ),
        )

    def _compact(self, p):
        result = {
            "node": {
                k: p["node"][k]
                for k in ("id", "version_id", "kind", "title", "start_page", "end_page")
            },
            "content": p["content"],
            "children": p["children"],
            "ancestors": p["ancestors"],
            "sources": p["sources"],
            "assets": [
                {k: a[k] for k in ("id", "type", "pdf_page", "file_id")}
                | {"caption": a["metadata"].get("caption"), "asset_url": a["asset_url"]}
                for a in p["assets"]
            ],
            "warnings": p["node"]["metadata"].get("warnings", []),
        }
        for k in ("part", "atomic_bundle", "solution", "solution_status", "warning"):
            if k in p:
                result[k] = p[k]
        if "part" in result:
            result["part"].pop("content_file", None)
        return result

    def load(self, id, kind=None, remember=True, scope="full"):
        if scope == "part":
            p = self.library.part(id)
        else:
            n = self.library._node(id)
            if kind and n["kind"] != kind:
                raise ValueError("Requested node is not a " + kind)
            if n["kind"] in ("exam", "exercise_collection"):
                if scope != "bundle":
                    return {
                        "error": "ATOMIC_BUNDLE_REQUIRED",
                        "tool": "get_exam_with_solution"
                        if n["kind"] == "exam"
                        else "get_exercise_collection",
                        "node_id": id,
                    }
                p = self.library.bundle(id, kind)
            else:
                p = self.library.node(id)
        result = self._compact(p)
        if len(js(result)) > self.s.settings.max_tool_chars:
            error = {
                "error": "ATOMIC_BUNDLE_EXCEEDS_TOOL_BUDGET"
                if p.get("atomic_bundle")
                else "SOURCE_EXCEEDS_TOOL_BUDGET",
                "node_id": p["node"]["id"],
                "instruction": "No content was read or credited. Increase the configured tool/context budget for an atomic bundle; books can use actual children or stable lesson parts.",
            }
            if p["node"]["kind"] == "lesson":
                all_parts = self.library.parts(p["node"]["id"])
                error["parts"] = all_parts[:12]
                error["more_parts"] = len(all_parts) > 12
            else:
                error["children"] = p["children"][:12]
            if len(js(error)) > self.s.settings.max_tool_chars:
                error = {k: error[k] for k in ("error", "node_id", "instruction")}
            return error
        if remember:
            self.remember(result, scope, id)
        return result

    def execute(self, name, args):
        if name == "search_library":
            p = SearchArgs.model_validate(args)
            return {
                "items": self.library.search(
                    p.query, p.model_dump(exclude={"query"}, exclude_none=True)
                )
            }
        if name == "get_document_metadata":
            return {
                "document": self.library.get_doc(
                    DocArgs.model_validate(args).document_id, True
                )
            }
        if name == "get_table_of_contents":
            return {
                "items": self.library.nodes(DocArgs.model_validate(args).document_id)
            }
        if name == "get_lesson_full":
            return self.load(NodeArgs.model_validate(args).node_id, "lesson")
        if name == "get_section":
            return self.load(NodeArgs.model_validate(args).node_id)
        if name == "list_lesson_parts":
            return {"items": self.library.parts(NodeArgs.model_validate(args).node_id)}
        if name == "get_lesson_part":
            return self.load(PartArgs.model_validate(args).part_id, scope="part")
        if name in ("get_exam_with_solution", "get_exercise_collection"):
            return self.load(
                NodeArgs.model_validate(args).node_id,
                "exam" if name == "get_exam_with_solution" else "exercise_collection",
                scope="bundle",
            )
        if name == "search_within_node":
            p = WithinArgs.model_validate(args)
            payload = self.library.node(p.node_id)
            text = payload["content"]
            hits = []
            pos = text.casefold().find(p.query.casefold())
            while pos >= 0 and len(hits) < 5:
                hits.append(text[max(0, pos - 150) : pos + 450])
                pos = text.casefold().find(p.query.casefold(), pos + len(p.query))
            parts = []
            if payload["node"]["kind"] == "lesson":
                parts = [
                    x["id"]
                    for x in self.library.parts(p.node_id)
                    if p.query.casefold()
                    in self.library.part(x["id"])["content"].casefold()
                ]
            return {
                "node_id": p.node_id,
                "matches": hits,
                "part_ids": parts,
                "locator_only": True,
            }
        raise ValueError("Unknown or unauthorized tool")

    def answer(self, args):
        answer = Answer.model_validate(args)
        if len(answer.model_dump_json()) > 50000:
            raise ValueError("Answer exceeds output budget")
        for id in answer.source_ids:
            if id not in self.sources:
                raise ValueError("Citation was not actually loaded")
            source = self.sources[id]
            self.library._node(source["node_id"])
        for block in answer.blocks:
            if block.type == "image":
                if block.asset_id not in self.assets:
                    raise ValueError("Image was not loaded from the published source")
                try:
                    self.library.asset(block.asset_id)
                except Exception:
                    raise ValueError("Image publication was revoked") from None
        if not answer.source_ids:
            answer.warnings.append(
                "لم تُستخدم مصادر منشورة لتأكيد هذه الإجابة؛ ليست حلًا رسميًا."
            )
        return answer, [self.sources[i] for i in answer.source_ids]
