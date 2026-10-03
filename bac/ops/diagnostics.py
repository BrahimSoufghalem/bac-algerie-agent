"""Operator-only bounded diagnostics, without arguments, sources or model text."""

import json
from bac.core.activity import LABELS
from bac.agent.provider_errors import safe_provider_diagnostic

ERROR_CODES = {
    "INVALID_SELECTOR_RESPONSE",
    "SELECTED_SOURCE_CHANGED",
    "MATCHING_SOURCE_NOT_FOUND",
    "TOOL_INPUT_OR_SOURCE_ERROR",
    "SOURCE_EXCEEDS_TOOL_BUDGET",
    "ATOMIC_BUNDLE_EXCEEDS_TOOL_BUDGET",
    "ATOMIC_BUNDLE_REQUIRED",
    "SOURCE_UNAVAILABLE",
    "SOURCE_PERMISSION_DENIED",
    "SOURCE_NOT_READY",
    "SOURCE_KIND_MISMATCH",
    "RETRIEVAL_STOPPED",
    "REFERENCE_READ_REQUIRED",
    "SCIENTIFIC_SANDBOX_UNAVAILABLE",
    "SCIENTIFIC_SANDBOX_BUSY",
    "SCIENTIFIC_INPUT_LIMIT",
    "SCIENTIFIC_TIMEOUT",
    "SCIENTIFIC_RESOURCE_OR_PROCESS_LIMIT",
    "SCIENTIFIC_PROCESS_FAILURE",
    "SCIENTIFIC_INPUT_OR_COMPUTATION_ERROR",
    "SOURCE_IMAGE_BUDGET_EXCEEDED",
    "PRIVATE_IMAGE_BUDGET_EXCEEDED",
    "TOOL_RESULT_EXCEEDS_BUDGET",
    "RUN_TIMEOUT",
    "CANCELLED",
    "ACCOUNT_DISABLED",
    "CONTEXT_BUDGET_EXCEEDED",
    "TOO_MANY_TOOLS",
    "FINAL_ANSWER_INVALID",
    "FINAL_ANSWER_REQUIRED",
    "REPEATED_TOOL_LOOP",
    "EMPTY_MODEL_RESPONSE",
    "OUTPUT_TRUNCATED",
    "MODEL_DID_NOT_COMPLETE",
    "RESPONSE_TOO_LARGE",
    "TOOL_ARGUMENTS_TOO_LARGE",
    "NETWORK_OR_TIMEOUT",
    "INVALID_MODEL_RESPONSE",
    "PROVIDER_METADATA_TOO_LARGE",
    "AGENT_EXECUTION_ERROR",
    "LEASE_LOST_OR_CANCELLED",
    "HTTP_400",
    "HTTP_401",
    "HTTP_403",
    "HTTP_404",
    "HTTP_408",
    "HTTP_413",
    "HTTP_422",
    "HTTP_429",
    "HTTP_500",
    "HTTP_502",
    "HTTP_503",
    "HTTP_504",
}
FIELDS = {
    "expression",
    "values",
    "variable",
    "lower",
    "upper",
    "samples",
    "title",
    "x_label",
    "y_label",
    "kind",
    "series",
    "code",
    "inputs",
    "blocks",
    "source_ids",
    "response_kind",
    "node_id",
    "part_id",
    "document_id",
    "page",
    "asset_id",
}
ISSUES = {
    "missing",
    "extra_forbidden",
    "string_type",
    "int_type",
    "float_type",
    "float_parsing",
    "int_parsing",
    "greater_than_equal",
    "less_than_equal",
    "too_long",
    "too_short",
    "literal_error",
    "value_error",
    "list_type",
    "dict_type",
    "finite_number",
}


def safe_code(code):
    return code if isinstance(code, str) and code in ERROR_CODES else "OTHER_FAILURE"


def safe_diagnostic(name, result):
    code = result.get("error")
    if str(result.get("message", "")).startswith("REFERENCE_READ_REQUIRED"):
        code = "REFERENCE_READ_REQUIRED"
    issues = []
    raw_issues = result.get("issues", [])
    for issue in (raw_issues if isinstance(raw_issues, list) else [])[:8]:
        if not isinstance(issue, dict):
            continue
        field = str(issue.get("field", "")).split(".")[0]
        issue_type = issue.get("type")
        issues.append(
            {
                "field": field if field in FIELDS else "other",
                "type": issue_type
                if isinstance(issue_type, str) and issue_type in ISSUES
                else "other",
            }
        )
    return {
        "stage": LABELS.get(name, ("organize", ""))[0],
        "code": safe_code(code),
        "issues": issues,
    }


def diagnose_run(db, run_id=None):
    run = (
        db.one(
            "SELECT id,status,error,steps,tool_calls,config_id,created_at FROM agent_runs WHERE id=?",
            (run_id,),
        )
        if run_id
        else db.one(
            "SELECT id,status,error,steps,tool_calls,config_id,created_at FROM agent_runs "
            "WHERE status IN ('FAILED','INTERRUPTED') ORDER BY created_at DESC LIMIT 1"
        )
    )
    if not run:
        return {"found": False}
    active = db.one("SELECT config_id FROM active_models WHERE slot='agent'")
    newer = db.one(
        "SELECT 1 FROM agent_runs WHERE created_at>? LIMIT 1", (run["created_at"],)
    )
    diagnostics = []
    rows = db.rows(
        "SELECT payload FROM run_events WHERE run_id=? AND type='tool_diagnostic' "
        "ORDER BY id DESC LIMIT 40",
        (run["id"],),
    )
    for row in reversed(rows):
        try:
            payload = json.loads(row["payload"])
            if not isinstance(payload, dict):
                continue
            # Re-sanitize storage; never trust arbitrary old payloads.
            item = safe_diagnostic("", payload | {"error": payload.get("code")})
            stage = payload.get("stage")
            item["stage"] = (
                stage
                if isinstance(stage, str)
                and stage in {"review", "math", "check", "diagram", "organize"}
                else "organize"
            )
            diagnostics.append(item)
        except (ValueError, TypeError):
            continue
    provider_diagnostics = []
    for row in reversed(
        db.rows(
            "SELECT payload FROM run_events WHERE run_id=? AND type='provider_diagnostic' "
            "ORDER BY id DESC LIMIT 40",
            (run["id"],),
        )
    ):
        try:
            provider_diagnostics.append(
                safe_provider_diagnostic(json.loads(row["payload"]))
            )
        except (ValueError, TypeError):
            continue
    return {
        "found": True,
        "status": run["status"]
        if run["status"]
        in {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "INTERRUPTED"}
        else "UNKNOWN",
        "error": safe_code(run["error"]) if run["error"] else None,
        "model_requests": run["steps"],
        "tool_calls": run["tool_calls"],
        "uses_current_model_config": bool(
            active and active["config_id"] == run["config_id"]
        ),
        "newer_run_exists": bool(newer),
        "diagnostics": diagnostics,
        "provider_diagnostics": provider_diagnostics,
        "note": "No prompt, model text, arguments, source IDs/files, keys or user identity included. Hints are bounded classifications, not proof of cause. Older runs may have no tool/provider diagnostics.",
    }
