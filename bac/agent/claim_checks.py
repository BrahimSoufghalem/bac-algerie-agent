"""Validate narrowly scoped execution/history links, not prose correctness certification."""

from bac.agent.session_state import message_digest
from bac.agent.memory import history_text
from bac.core.presentation import public_message
from bac.core.db import js


def block_text(block):
    if block.type == "text":
        return block.text
    if block.type == "equation":
        return block.latex
    if block.type == "table":
        return "\n".join(block.headers + [c for row in block.rows for c in row])
    return ""


def validate_claims(answer, tools):
    for item in answer.checked_claims:
        if item.block_index >= len(answer.blocks) or item.claim not in block_text(
            answer.blocks[item.block_index]
        ):
            raise ValueError("Checked claim must match its public answer block")
        result = tools.scientific.get(item.result_id)
        checks = (result or {}).get("output", {}).get("checks", [])
        if not result or result.get("tool") != "run_python":
            raise ValueError("Actual isolated Python result required")
        if item.check_index >= len(checks):
            raise ValueError("Actual current-run check required")
        check = checks[item.check_index]
        if (
            check["label"] != item.claim
            or check["status"] != "passed"
            or not check.get("evidence")
        ):
            raise ValueError(
                "Actual passed comparison for THIS claim required; printing OK or successful execution is not verification"
            )
    computation = answer.response_kind == "calculation" or (
        getattr(tools, "task_state", {}).get("goal_kind") in {"calculation", "plot"}
        and bool(tools.scientific)
    )
    if (
        computation
        and answer.response_kind in {"teaching", "calculation"}
        and tools.coordinated
        and not answer.checked_claims
    ):
        raise ValueError(
            "Bind computational claims to actual comparisons; no whole-answer certification"
        )
    if answer.history_evidence and not tools.history_summary_requested:
        raise ValueError(
            "History evidence belongs only to a requested own-history summary"
        )
    if (
        tools.history_summary_requested
        and answer.response_kind in {"teaching", "calculation", "history_summary"}
        and (not tools.history_read or not answer.history_evidence)
    ):
        raise ValueError(
            "Requested history summary needs actual dialogue retrieval and student provenance"
        )
    for item in answer.history_evidence:
        if item.block_index >= len(answer.blocks):
            raise ValueError("Unknown history claim block")
        row = tools.s.db.one(
            "SELECT id,role,content,blocks FROM messages WHERE id=? AND conversation_id=? AND active=1",
            (item.message_id, tools.chat),
        )
        if not row or tools.history_evidence.get(item.message_id) != message_digest(
            row
        ):
            raise ValueError("Active actually delivered own-chat history required")
        safe = public_message(row)
        safe["blocks"] = js(safe["blocks"])
        if item.quote not in history_text(safe):
            raise ValueError("History quote not in actual public dialogue")
        if row["role"] != "user":
            raise ValueError(
                "Student misconceptions need student statements, not assistant or book examples"
            )
    if (
        tools.history_summary_requested
        and answer.response_kind in {"history_summary", "teaching", "calculation"}
        and not tools.history_complete
    ):
        answer.warnings.append(
            "هذا ملخص جزئي للرسائل التي راجعتها، وليس حصرًا لكل أخطاء المحادثة."
        )
