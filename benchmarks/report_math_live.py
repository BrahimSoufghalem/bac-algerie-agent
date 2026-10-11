"""Export explicitly allowed, redacted evidence; never export private DB/key files."""

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from benchmarks.math_live_support import (
    load_secret_values,
    read_json,
    redact,
    token_totals,
)


def make_evidence(root):
    raw = root / "raw"
    requests = read_json(raw / "requests.json", [])
    results = read_json(raw / "results.json", [])
    tools = read_json(raw / "tool-audit.json", [])
    assert len({x["request_number"] for x in requests}) == len(requests), (
        "Duplicate provider request number"
    )
    all_totals = token_totals(requests)
    assert (
        sum(
            x["input_tokens"] + x["output_tokens"]
            for x in requests
            if type(x.get("input_tokens")) is int
            and type(x.get("output_tokens")) is int
        )
        == all_totals["known_total_tokens"]
    )
    stages = {
        s: token_totals([r for r in requests if r["stage"] == s])
        for s in sorted({r["stage"] for r in requests})
    }
    per_turn = []
    for row in results:
        run_ids = {row["run_id"]} | {
            a["run_id"] for a in row.get("previous_attempts", [])
        }
        req = [r for r in requests if r.get("run_id") in run_ids]
        attempts = [
            t for t in tools if t.get("run_id") in run_ids and t["name"] == "run_python"
        ]
        reply = row.get("reply") or {}
        blocks = json.loads(reply.get("blocks") or "[]")
        text = reply.get("content", "")
        graph = [b for b in blocks if b.get("type") == "graph"]

        def execution(t):
            result = t.get("result") or {}
            return result.get("output", result) if isinstance(result, dict) else {}

        checks = [c for a in attempts for c in execution(a).get("checks", [])]
        per_turn.append(
            {
                "id": row["id"],
                "status": row["status"],
                "reply_published": bool(reply),
                "attempt_count": len(run_ids),
                "known_usage": token_totals(req),
                "python_attempts": len(attempts),
                "python_computed": sum(
                    execution(t).get("status") == "computed" for t in attempts
                ),
                "python_errors": [
                    execution(t).get("error") or t.get("exception")
                    for t in attempts
                    if execution(t).get("error") or t.get("exception")
                ],
                "check_statuses": {
                    s: sum(c.get("status") == s for c in checks)
                    for s in ("passed", "failed", "inconclusive")
                },
                "graph_blocks": len(graph),
                "possible_doubled_latex_macros": len(
                    re.findall(
                        r"\\\\(?:mathbb|infty|implies|quad|in|nearrow|searrow)\b", text
                    )
                ),
                "duration_seconds": row.get("duration_seconds"),
            }
        )
    sql = None
    db = root / "private/qa-data/platform.sqlite3"
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute(
            "SELECT SUM(input_tokens), SUM(output_tokens), COUNT(*) FROM model_usage"
        ).fetchone()
        con.close()
        sql = {
            "input": rows[0] or 0,
            "output": rows[1] or 0,
            "rows": rows[2],
            "matches_known_wire_usage": rows[0] == all_totals["known_input_tokens"]
            and rows[1] == all_totals["known_output_tokens"],
        }
    m23 = next((r for r in per_turn if r["id"] == "M23"), None)
    return {
        "planned_turns": 24,
        "executed_turns": len(results),
        "complete_run": len(results) == 24,
        "completed_publications": sum(r["status"] == "COMPLETED" for r in results),
        "failed_runs": sum(r["status"] == "FAILED" for r in results),
        "tokens": all_totals,
        "by_stage": stages,
        "per_turn": per_turn,
        "platform_usage_crosscheck": sql,
        "missing_image_case_zero_provider_requests": m23["known_usage"]["requests"] == 0
        if m23
        else None,
        "runtime_preflight": read_json(root / "runtime-preflight.json", None),
        "scope": "Real model and production Docker sandbox on a disposable GitHub runner; not a deployment",
        "limitations": [
            "COMPLETED means published, not mathematically correct.",
            "computed/check passed reflects executed model-written code, not independent proof.",
            "Graph block presence does not establish curve correctness or visible UI rendering.",
            "Double-escaped LaTeX count is a candidate flag; review actual rendering.",
            "Cache/thinking totals cover only reported counters; missing is unknown, not zero.",
            "Provider errors/timeouts can have unknown token usage; recorded totals are known-only.",
            "No monetary estimate; prices are not configured.",
            "The source fixture and exact questions are original; model outputs are stochastic.",
        ],
    }


def export(root):
    secret_values = load_secret_values()
    public = root / "public"
    public.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        evidence = make_evidence(root)
    except (AssertionError, ValueError, sqlite3.Error) as exc:
        evidence = {
            "audit_integrity_error": type(exc).__name__,
            "planned_turns": 24,
            "executed_turns": len(read_json(root / "raw/results.json", [])),
            "complete_run": False,
            "limitations": [
                "Token totals could not be independently reconciled; inspect sanitized raw evidence."
            ],
        }
    (public / "evidence.json").write_text(
        json.dumps(redact(evidence, secret_values), ensure_ascii=False, indent=2)
    )
    allowed = (
        [
            root / "configuration.json",
            root / "mathematics-catalog.json",
            root / "router_audit.json",
            root / "runtime-preflight.json",
        ]
        + list((root / "raw").glob("request-*.json"))
        + [
            root / "raw/requests.json",
            root / "raw/results.json",
            root / "raw/tool-audit.json",
            root / "raw/cases.json",
        ]
    )
    for p in allowed:
        if p.is_file():
            (public / p.name).write_text(
                json.dumps(
                    redact(json.loads(p.read_text()), secret_values),
                    ensure_ascii=False,
                    indent=2,
                )
            )
    safe = redact(evidence, secret_values)
    t = safe.get("tokens", {})
    lines = [
        "# تجربة الرياضيات الحقيقية — Gemini 3.5 Flash Lite",
        "",
        f"الأسئلة المنفذة: {safe.get('executed_turns', 0)} / 24. اكتمال التنفيذ لا يعني صحة الإجابات.",
        "",
        f"التوكنات المعروفة: إدخال {t.get('known_input_tokens', 'غير متاح')} + إخراج {t.get('known_output_tokens', 'غير متاح')} = {t.get('known_total_tokens', 'غير متاح')}.",
        f"طلبات بلا عداد استخدام كامل: {t.get('unknown_usage_requests', 'غير متاح')}. غياب عداد الكاش أو التفكير ليس صفرًا.",
        "",
        "| السؤال | حالة النشر | التوكنات المعروفة | Python منفذ | أخطاء Python | كتل رسم |",
        "|---|---|---:|---:|---|---:|",
    ]
    for row in safe.get("per_turn", []):
        lines.append(
            f"| {row['id']} | {row['status']} | {row['known_usage']['known_total_tokens']} | {row['python_computed']} | {', '.join(row['python_errors']) or '—'} | {row['graph_blocks']} |"
        )
    lines += [
        "",
        "## حدود التقرير",
        "هذه عدادات تنفيذ وإشارات تدقيق، وليست حكمًا آليًا على جودة الشرح. راجع الإجابات والمراجع ونتائج الأدوات في الملفات المرفقة قبل الحكم على صحة الحسابات والرسوم وفهم المتابعات. لم تُصلح أي مشكلة في المنصة.",
        "قاعدة البيانات، مفاتيح التشفير، مفتاح Gemini، ورمز خدمة Python لا تدخل المرفقات.",
    ]
    (public / "report.md").write_text("\n".join(lines) + "\n")
    for p in public.iterdir():
        data = p.read_text()
        if any(s and s in data for s in secret_values):
            raise ValueError("Refusing unsafe artifact export")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write((public / "report.md").read_text())
    print("Sanitized evidence export prepared; private database/key files excluded")
    return safe


if __name__ == "__main__":
    export(Path(os.environ["MASAR_BENCHMARK_ROOT"]))
