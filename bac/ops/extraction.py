"""Read-only bounded extraction diagnostics. No provider calls, secrets or source content."""

import json
import sqlite3
import time
from pathlib import Path
from contextlib import closing
from bac.vendor.bookforge.vision.provider import NETWORK_ERROR_CODES

STATUSES = {
    "books": {
        "UPLOADED",
        "PROCESSING",
        "COMPLETED",
        "COMPLETED_WITH_ISSUES",
        "STRUCTURE_FAILED",
    },
    "pages": {"PENDING", "PROCESSING", "SUCCESS", "NEEDS_REVIEW", "FAILED"},
    "jobs": {"PENDING", "RUNNING", "DONE", "FAILED"},
}
STAGES = {
    "claimed",
    "render",
    "cached_response",
    "rate_wait",
    "provider_request",
    "response_saved",
    "postprocess",
    "structure",
}
ERRORS = NETWORK_ERROR_CODES | {
    "WORKER_LEASE_EXPIRED",
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
    "OUTPUT_TRUNCATED",
    "INVALID_STRUCTURED_JSON",
    "INVALID_EXTRACTION_RESPONSE",
    "RESPONSE_TOO_LARGE",
}


def _open(path):
    c = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5)
    c.row_factory = sqlite3.Row
    return c


def diagnose_extraction(root, worker_limit, request_timeout, lease_seconds, now=None):
    root = Path(root)
    now = time.time() if now is None else now
    if not (root / "extraction/state.sqlite3").is_file():
        return {"found": False, "provider_requests": 0, "database_changes": 0}
    with closing(_open(root / "extraction/state.sqlite3")) as c:
        # One coherent read snapshot while the worker is processing in parallel.
        c.execute("BEGIN")
        state = c.execute("SELECT * FROM settings WHERE id=1").fetchone()
        if not state:
            return {"found": False, "provider_requests": 0, "database_changes": 0}
        states = {}
        for table, known in STATUSES.items():
            counts = {}
            for r in c.execute(
                f"SELECT status,count(*) n FROM {table} GROUP BY status"
            ):
                status = r["status"] if r["status"] in known else "OTHER"
                counts[status] = counts.get(status, 0) + r["n"]
            states[table] = counts
        count = lambda sql, args=(): c.execute(sql, args).fetchone()[0]
        effective = min(state["workers"], worker_limit)
        ready = count(
            "SELECT count(*) FROM jobs WHERE status='PENDING' AND available_at<=?",
            (now,),
        )
        active = count(
            "SELECT count(*) FROM engine_heartbeats WHERE last_seen>?", (now - 30,)
        )
        expired = count(
            "SELECT count(*) FROM jobs WHERE status='RUNNING' AND (lease_until IS NULL OR lease_until<=?)",
            (now,),
        )
        recent = count(
            "SELECT count(*) FROM pages WHERE status IN ('SUCCESS','NEEDS_REVIEW') AND completed_at>?",
            (now - 600,),
        )
        error_groups = {}
        for r in c.execute(
            "SELECT last_error,count(*) n FROM jobs WHERE last_error IS NOT NULL GROUP BY last_error"
        ):
            code = r["last_error"] if r["last_error"] in ERRORS else "OTHER_FAILURE"
            error_groups[code] = error_groups.get(code, 0) + r["n"]
        jobs = []
        for j in c.execute(
            "SELECT * FROM jobs WHERE status='RUNNING' ORDER BY kind,id LIMIT 16"
        ).fetchall():
            if j["kind"] == "page":
                phase = c.execute(
                    "SELECT message,ts FROM events WHERE page_id=? AND ts>=? AND message LIKE 'EXTRACTION_STAGE:%' ORDER BY id DESC LIMIT 1",
                    (j["target_id"], j["available_at"]),
                ).fetchone()
            else:
                phase = c.execute(
                    "SELECT message,ts FROM events WHERE book_id=? AND page_id IS NULL AND ts>=? AND message LIKE 'EXTRACTION_STAGE:%' ORDER BY id DESC LIMIT 1",
                    (j["book_id"], j["available_at"]),
                ).fetchone()
            stage = (
                phase["message"].split(":", 1)[1] if phase else "unknown_legacy_stage"
            )
            jobs.append(
                {
                    "kind": j["kind"]
                    if j["kind"] in ("page", "structure")
                    else "other",
                    "attempts": j["attempts"],
                    "lease_remaining_seconds": round(j["lease_until"] - now)
                    if j["lease_until"] is not None
                    else None,
                    "response_already_saved": bool(j["raw_file"]),
                    "stage": stage if stage in STAGES else "unknown_legacy_stage",
                    "stage_elapsed_seconds": round(max(0, now - phase["ts"]))
                    if phase
                    else None,
                }
            )
        config_match = []
        current = None
        if (root / "platform.sqlite3").is_file():
            with closing(_open(root / "platform.sqlite3")) as p:
                a = p.execute(
                    "SELECT config_id FROM active_models WHERE slot='extraction'"
                ).fetchone()
                current = a["config_id"] if a else None
        for r in c.execute(
            "SELECT DISTINCT r.config_json FROM books b JOIN runs r ON r.id=b.run_id WHERE b.status='PROCESSING' LIMIT 16"
        ):
            try:
                cid = json.loads(r["config_json"]).get("_platform_config_id")
            except (ValueError, AttributeError):
                cid = None
            config_match.append(bool(current and cid == current) if cid else None)
        cooldown = round(max(0, state["cooldown_until"] - now))
        rate = round(max(0, state["next_request"] - now))
        hints = []
        if not active:
            hints.append("NO_RECENT_WORKER_HEARTBEAT")
        if effective < 1:
            hints.append("INVALID_WORKER_COUNT")
        if states["jobs"].get("RUNNING", 0) >= effective > 0 and ready:
            hints.append("WORKER_CAP_OCCUPIED")
        if cooldown or rate:
            hints.append("PROVIDER_OR_RATE_WAIT_ACTIVE")
        if expired:
            hints.append("EXPIRED_OR_MISSING_LEASE_PRESENT")
        if (
            ready
            and not recent
            and any(code in NETWORK_ERROR_CODES for code in error_groups)
        ):
            hints.append("NETWORK_FAILURES_WITHOUT_RECENT_PAGE_COMPLETIONS")
        return {
            "found": True,
            "states": states,
            "configured_workers": state["workers"],
            "deployment_worker_limit": worker_limit,
            "effective_workers": effective,
            "request_deadline_seconds": request_timeout,
            "lease_seconds": lease_seconds,
            "active_worker_heartbeats": active,
            "pending_ready": ready,
            "running_expired_or_missing_lease": expired,
            "cooldown_remaining_seconds": cooldown,
            "rate_wait_remaining_seconds": rate,
            "page_completions_last_10_minutes": recent,
            "last_error_task_counts": error_groups,
            "running_jobs": jobs,
            "running_jobs_truncated": states["jobs"].get("RUNNING", 0) > len(jobs),
            "processing_run_uses_current_config": config_match,
            "hints": hints,
            "provider_requests": 0,
            "database_changes": 0,
            "note": "Last errors are per-task historical state, not request counts or proof of the current cause. Equality compares configuration IDs, not key values. No source IDs/files, content, URLs, keys or identities included. Legacy jobs may have no stage events.",
        }
