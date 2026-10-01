import time, hashlib
from bac.core.db import uid
from bac.science.runner import ScienceRunner
from bac.science.registry import CONTRACTS, DESCRIPTIONS
from bac.science.contracts import PlotFromResult
from pydantic import Field
from bac.core.db import js
from bac.agent.models import Strict, Answer, VerificationBlock
from bac.library.service import Library
from bac.learning.service import Learning
from bac.learning.private import PrivateFiles
from bac.learning.contracts import Note, Material, PrivatePage


class EmptyArgs(Strict):
    pass


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
    def __init__(self, s, user, chat, run_id=None):
        self.s = s
        self.user = user
        self.chat = chat
        self.library = Library(s)
        self.sources = {}
        self.assets = set()
        self.run_id = run_id
        self.scientific = {}
        self.runner = ScienceRunner(s.settings)
        self.learning = Learning(s)
        self.private = PrivateFiles(s)
        self.pending_private = None
        self.private_assets = {}

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
        entries.extend(
            (name, DESCRIPTIONS[name], schema) for name, schema in CONTRACTS.items()
        )
        entries.append(
            (
                "plot_from_result",
                "Plot numeric array outputs actually computed in this run; no model replacements.",
                PlotFromResult,
            )
        )
        entries.extend(
            [
                (
                    "propose_note",
                    "Propose a pending educational note only; user review and explicit consent are required. Never automatically remember messages.",
                    Note,
                ),
                (
                    "list_private_uploads",
                    "List only this user's unexpired private files in this conversation; never search/index them into the shared library.",
                    EmptyArgs,
                ),
                (
                    "read_private_page",
                    "Read one own temporary page: text or actual image pixels delivered separately. Private/untrusted, not official; unreadable text remains unknown.",
                    PrivatePage,
                ),
            ]
        )
        if self.learning.preferences(self.user)["include_approved_notes"]:
            entries.append(
                (
                    "list_my_notes",
                    "Read only own explicitly approved notes when user opted in; tentative context, not permanent facts.",
                    EmptyArgs,
                )
            )
        if self.user["role"] in ("teacher", "owner"):
            entries.append(
                (
                    "save_teaching_material",
                    "Save a private generated draft: lesson plan, exercises, test with full solution/rubric, grading or reference review. Use actually loaded source IDs and actual science results; never official by default.",
                    Material,
                )
            )
        else:
            entries.append(
                (
                    "save_practice_test",
                    "Save only self_practice: generated test, full separate solution and marks summing to total; private and not official.",
                    Material,
                )
            )
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

    def credit_private(self, payload):
        source = payload["source"]
        self.private.row(self.user, source["node_id"], self.chat)
        self.sources[source["source_id"]] = source
        if payload.get("asset_id"):
            self.assets.add(payload["asset_id"])
            self.private_assets[payload["asset_id"]] = source

    def science(self, name, args):
        if name == "plot_from_result":
            p = PlotFromResult.model_validate(args)
            previous = self.scientific.get(p.result_id)
            if not previous or previous["tool"] != "run_scientific_code":
                raise ValueError(
                    "Numeric outputs were not actually computed in this run"
                )
            outputs = previous["output"].get("outputs", {})
            plot = {
                "title": p.title,
                "x_label": p.x_label,
                "y_label": p.y_label,
                "kind": p.kind,
                "series": [
                    {
                        "label": p.y_output,
                        "x": outputs.get(p.x_output),
                        "y": outputs.get(p.y_output),
                    }
                ],
            }
            validated = CONTRACTS["plot_data"].model_validate(plot).model_dump()
            output = self.runner.execute("plot_data", validated)
            if "error" not in output:
                output["origin"] = "computed_program_outputs"
                output["parent_result_id"] = p.result_id
                output["scope"] = (
                    "Exact returned program arrays; shape checked, but program assumptions are not independently verified"
                )
            inputs = p.model_dump()
        else:
            inputs = CONTRACTS[name].model_validate(args).model_dump()
            output = self.runner.execute(name, inputs)
        if "error" in output:
            return output
        result = {
            "result_id": uid("science"),
            "tool": name,
            "inputs": inputs,
            "output": output,
        }
        if len(js(result)) > self.s.settings.max_tool_chars:
            return {
                "error": "SCIENTIFIC_RESULT_EXCEEDS_TOOL_BUDGET",
                "message": "No result credited; use fewer points/outputs or increase tool/context budgets",
            }
        if self.run_id:
            active = self.s.db.one(
                "SELECT status,cancel_requested FROM agent_runs WHERE id=?",
                (self.run_id,),
            )
            if (
                not active
                or active["status"] != "RUNNING"
                or active["cancel_requested"]
            ):
                return {"error": "SCIENTIFIC_RUN_NO_LONGER_ACTIVE"}
        self.s.db.execute(
            "INSERT INTO scientific_results VALUES(?,?,?,?,?,?,?,?,?)",
            (
                result["result_id"],
                self.user["id"],
                self.chat,
                self.run_id,
                name,
                js(inputs),
                js(output),
                hashlib.sha256(js(output).encode()).hexdigest(),
                time.time(),
            ),
        )
        self.scientific[result["result_id"]] = result
        return result

    def execute(self, name, args):
        if name in (
            "propose_note",
            "list_my_notes",
            "list_private_uploads",
            "read_private_page",
            "save_teaching_material",
            "save_practice_test",
        ):
            live = self.s.db.one("SELECT * FROM users WHERE id=?", (self.user["id"],))
            if not live or not live["active"]:
                raise ValueError("Account disabled")
            if name == "propose_note":
                return self.learning.propose(live, self.run_id, args)
            if name == "list_my_notes":
                EmptyArgs.model_validate(args)
                if not self.learning.preferences(live)["include_approved_notes"]:
                    raise ValueError("Note context consent is disabled")
                return {
                    "items": [
                        n
                        for n in self.learning.notes(live)
                        if n["status"] == "approved"
                    ][:6]
                }
            if name == "list_private_uploads":
                EmptyArgs.model_validate(args)
                return {"items": self.private.list(live, self.chat)}
            if name == "read_private_page":
                p = PrivatePage.model_validate(args)
                result, image = self.private.page(live, p.upload_id, p.page, self.chat)
                self.pending_private = (result, image)
                return result
            if name == "save_teaching_material" and live["role"] not in (
                "teacher",
                "owner",
            ):
                raise ValueError("Teacher permission required")
            if name == "save_practice_test" and args.get("kind") != "self_practice":
                raise ValueError("Only self_practice may be saved by this tool")
            return self.learning.material(self, args)

        if name in CONTRACTS or name == "plot_from_result":
            return self.science(name, args)
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
            if source.get("scope") == "private":
                self.private.row(self.user, source["node_id"], self.chat)
            else:
                self.library._node(source["node_id"])
        blocks = []
        for block in answer.blocks:
            if block.type in ("verification", "graph"):
                result = self.scientific.get(block.result_id)
                if not result:
                    raise ValueError(
                        "Scientific result was not computed/loaded in this run"
                    )
                if block.type == "graph" and not any(
                    k in result["output"] for k in ("chart", "diagram")
                ):
                    raise ValueError("Graph requires an actual chart tool result")
                blocks.append(block.model_copy(update={"result": result}))
            else:
                blocks.append(block)
            if block.type == "equation":
                for result_id in block.result_ids:
                    if result_id not in self.scientific:
                        raise ValueError(
                            "Equation evidence was not computed in this run"
                        )
            if block.type == "verification" and result["output"].get("status") in (
                "failed",
                "inconclusive",
            ):
                answer.warnings.append(
                    "فحص حسابي لم ينجح أو لم يُحسم؛ لا يُعدّ هذا تأكيدًا لصحة الحل."
                )
            if block.type == "image":
                if block.asset_id not in self.assets:
                    raise ValueError("Image was not loaded from the published source")
                if block.asset_id in self.private_assets:
                    source = self.private_assets[block.asset_id]
                    self.private.row(self.user, source["node_id"], self.chat)
                    blocks[-1] = block.model_copy(
                        update={
                            "asset_url": "/api/private/"
                            + source["node_id"]
                            + "/pages/"
                            + str(source["pages"][0])
                        }
                    )
                else:
                    try:
                        self.library.asset(block.asset_id)
                    except Exception:
                        raise ValueError("Image publication was revoked") from None
        displayed = {b.result_id for b in blocks if b.type == "verification"}
        for id, result in self.scientific.items():
            if (
                result["output"].get("status") in ("failed", "inconclusive")
                and id not in displayed
            ):
                blocks.append(
                    VerificationBlock(result_id=id).model_copy(
                        update={"result": result}
                    )
                )
                answer.warnings.append(
                    "أُظهر فحص سابق لم ينجح أو لم يُحسم بدل إخفائه؛ لا يثبت التصحيح اللاحق صحة كل الحل."
                )
        if len(blocks) > 30:
            raise ValueError("Answer plus mandatory failed checks exceeds block budget")
        answer = answer.model_copy(update={"blocks": blocks})
        if any(
            b.type in ("verification", "graph")
            or (b.type == "equation" and b.result_ids)
            for b in blocks
        ):
            answer.warnings.append(
                "التحقق يخص المدخلات والفحص المعروض فقط، وليس تصديقًا لكل الشرح أو تفسير المسألة."
            )
        if len(answer.model_dump_json()) > 50000:
            raise ValueError(
                "Resolved scientific answer exceeds output budget; use fewer result blocks/points"
            )
        if not answer.source_ids:
            answer.warnings.append(
                "لم تُستخدم مصادر منشورة لتأكيد هذه الإجابة؛ ليست حلًا رسميًا."
            )
        answer.warnings = list(dict.fromkeys(answer.warnings))[-20:]
        if len(answer.model_dump_json()) > 50000:
            raise ValueError("Resolved answer and warnings exceed output budget")
        return answer, [self.sources[i] for i in answer.source_ids]
