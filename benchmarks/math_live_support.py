"""Pure benchmark helpers: no provider calls or model-code execution."""

import base64
import gzip
import hashlib
import io
import json
import os
import re
from pathlib import Path

DROP = {
    "authorization",
    "api_key",
    "encrypted_key",
    "password",
    "thoughtsignature",
    "thought_signature",
    "reasoning_content",
    "reasoning",
    "extra_content",
}
CREDENTIAL_PATTERN = re.compile(
    r"(?:AIza[A-Za-z0-9_-]{20,}|AQ\.[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9_]{20,})"
)


def load_secret_values():
    values = []
    for name in ("GEMINI_API_KEY_FILE", "PYTHON_SANDBOX_TOKEN_FILE"):
        p = os.environ.get(name)
        if p and Path(p).is_file():
            s = Path(p).read_text().strip()
            if s:
                values.append(s)
    return values


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {
            k: redact(v, secrets)
            for k, v in value.items()
            if str(k).casefold() not in DROP
        }
    if isinstance(value, list):
        return [
            redact(v, secrets)
            for v in value
            if not (isinstance(v, dict) and v.get("thought") is True)
        ]
    if isinstance(value, str):
        for s in secrets:
            if s:
                value = value.replace(s, "[REDACTED]")
        return CREDENTIAL_PATTERN.sub("[REDACTED]", value)
    return value


def load_fixture(repo, plan):
    name = plan.get("source_fixture", "book.md.gz.b64")
    if name not in {"book.md.gz.b64", "book-v2.md.gz.b64"}:
        raise ValueError("Unknown mathematics fixture")
    encoded = (Path(repo) / "benchmarks/math_live" / name).read_text()
    compressed = base64.b64decode("".join(encoded.split()), validate=True)
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        data = stream.read(2_000_001)
    if (
        len(data) > 2_000_000
        or len(data) != plan["source_bytes"]
        or hashlib.sha256(data).hexdigest() != plan["source_sha256"]
    ):
        raise ValueError("Mathematics fixture byte count/hash mismatch")
    data.decode("utf-8")
    return data


def token_totals(rows):
    known = [
        r
        for r in rows
        if type(r.get("input_tokens")) is int and type(r.get("output_tokens")) is int
    ]
    if any(r["input_tokens"] < 0 or r["output_tokens"] < 0 for r in known):
        raise ValueError("Negative token counter")
    for r in known:
        if (
            type(r.get("total_tokens")) is int
            and r["total_tokens"] != r["input_tokens"] + r["output_tokens"]
        ):
            raise ValueError("Provider token counters do not cross-foot")
    inputs = sum(r["input_tokens"] for r in known)
    outputs = sum(r["output_tokens"] for r in known)
    return {
        "requests": len(rows),
        "known_usage_requests": len(known),
        "unknown_usage_requests": len(rows) - len(known),
        "known_input_tokens": inputs,
        "known_output_tokens": outputs,
        "known_total_tokens": inputs + outputs,
        "known_cached_tokens": sum(
            r["cached_tokens"] for r in rows if type(r.get("cached_tokens")) is int
        ),
        "unknown_cache_requests": sum(r.get("cached_tokens") is None for r in rows),
        "known_thinking_tokens": sum(
            r["thinking_tokens"] for r in rows if type(r.get("thinking_tokens")) is int
        ),
        "unknown_thinking_requests": sum(
            r.get("thinking_tokens") is None for r in rows
        ),
    }


def read_json(path, default):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else default


def rate_limit_resume(results, requests):
    """Explicit one-time resume of the LAST unpublished 429 case, never full rerun."""
    if not results:
        raise ValueError("No failed case to resume")
    last = results[-1]
    affected = [r for r in requests if r.get("run_id") == last.get("run_id")]
    if (
        last.get("status") != "FAILED"
        or last.get("reply")
        or last.get("previous_attempts")
        or not affected
        or not any(r.get("http_status") == 429 for r in affected)
        or any(r.get("http_status") in {401, 403} for r in affected)
    ):
        raise ValueError(
            "Resume requires a last unpublished 429 failure with no previous resume"
        )
    from bac.agent.provider_errors import provider_diagnostic

    delays = [
        provider_diagnostic(
            429,
            {"error": {"message": r.get("error_message", "")}},
            {},
            r.get("retry_after_seconds"),
        ).get("retry_after_seconds", 60)
        for r in affected
        if r.get("http_status") == 429
    ]
    return last["number"], max(delays or [60])
