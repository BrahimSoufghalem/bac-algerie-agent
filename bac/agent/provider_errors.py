"""Fixed error hints/topology only. Never persist provider messages or request data."""

ERROR_BODY_LIMIT = 16384
STATUSES = {
    "INVALID_ARGUMENT",
    "FAILED_PRECONDITION",
    "NOT_FOUND",
    "PERMISSION_DENIED",
    "UNAUTHENTICATED",
    "RESOURCE_EXHAUSTED",
    "UNAVAILABLE",
    "INTERNAL",
    "DEADLINE_EXCEEDED",
    "OUT_OF_RANGE",
    "UNIMPLEMENTED",
}
HINTS = {
    "THOUGHT_SIGNATURE_MISSING",
    "THOUGHT_SIGNATURE_REJECTED",
    "TOOL_DECLARATION_MISMATCH",
    "TOOL_HISTORY_REJECTED",
    "TOOL_SCHEMA_REJECTED",
    "TOOL_CHOICE_REJECTED",
    "MESSAGE_ROLE_REJECTED",
    "PROVIDER_CONTEXT_REJECTED",
    "MEDIA_INPUT_REJECTED",
    "REQUEST_INVALID_UNKNOWN",
}
COUNT_FIELDS = {
    "declared_tool_count",
    "prior_tool_calls",
    "missing_declaration_count",
    "signed_prior_tool_calls",
}


def safe_provider_diagnostic(value):
    """Re-sanitize even persisted/legacy or adapter-supplied payloads."""
    value = value if isinstance(value, dict) else {}
    status = value.get("status")
    hint = value.get("hint")
    result = {
        "status": status
        if isinstance(status, str) and status in STATUSES
        else "UNKNOWN",
        "hint": hint
        if isinstance(hint, str) and hint in HINTS
        else "REQUEST_INVALID_UNKNOWN",
        "forced_final": value.get("forced_final") is True,
    }
    http = value.get("http_status")
    result["http_status"] = http if type(http) is int and 400 <= http <= 599 else None
    for key in COUNT_FIELDS:
        count = value.get(key)
        result[key] = count if type(count) is int and 0 <= count <= 10000 else 0
    return result


def request_topology(body):
    declared = {t.get("function", {}).get("name") for t in body.get("tools", [])}
    calls = [
        c
        for m in body.get("messages", [])
        if m.get("role") == "assistant"
        for c in m.get("tool_calls", [])
    ]
    choice = body.get("tool_choice")
    choice = choice if isinstance(choice, dict) else {}
    return {
        "forced_final": choice.get("function", {}).get("name") == "render_answer",
        "declared_tool_count": len(declared),
        "prior_tool_calls": len(calls),
        "missing_declaration_count": sum(
            c.get("function", {}).get("name") not in declared for c in calls
        ),
        "signed_prior_tool_calls": sum(
            bool(c.get("extra_content", {}).get("google", {}).get("thought_signature"))
            for c in calls
        ),
    }


def provider_diagnostic(code, payload, topology):
    """Text is examined transiently to produce a hint, NOT a proved diagnosis."""
    if isinstance(payload, list) and len(payload) == 1:
        payload = payload[0]
    error = payload.get("error", {}) if isinstance(payload, dict) else {}
    status = error.get("status") if isinstance(error, dict) else None
    text = error.get("message", "") if isinstance(error, dict) else error
    text = text[:ERROR_BODY_LIMIT].lower() if isinstance(text, str) else ""
    hint = "REQUEST_INVALID_UNKNOWN"
    if "thought_signature" in text or "thought signature" in text:
        hint = (
            "THOUGHT_SIGNATURE_MISSING"
            if any(x in text for x in ("missing", "required", "not provided"))
            else "THOUGHT_SIGNATURE_REJECTED"
        )
    elif any(
        x in text
        for x in (
            "function declaration",
            "function_declaration",
            "declared function",
            "declared tool",
        )
    ) and any(
        x in text
        for x in (
            "not found",
            "not defined",
            "not declared",
            "missing",
            "match",
            "unknown",
        )
    ):
        hint = "TOOL_DECLARATION_MISMATCH"
    elif any(
        x in text
        for x in (
            "function response",
            "function_response",
            "tool response",
            "tool_call_id",
        )
    ):
        hint = "TOOL_HISTORY_REJECTED"
    elif any(
        x in text
        for x in (
            "tool_choice",
            "tool choice",
            "function_calling_config",
            "allowed_function_names",
        )
    ):
        hint = "TOOL_CHOICE_REJECTED"
    elif any(x in text for x in ("schema", "parameters", "properties")) and any(
        x in text for x in ("function", "tool")
    ):
        hint = "TOOL_SCHEMA_REJECTED"
    elif "role" in text and any(
        x in text for x in ("message", "content", "system", "user", "tool")
    ):
        hint = "MESSAGE_ROLE_REJECTED"
    elif any(
        x in text
        for x in ("context length", "context window", "input token", "too many tokens")
    ):
        hint = "PROVIDER_CONTEXT_REJECTED"
    elif any(
        x in text for x in ("image", "mime_type", "mime type", "inline_data", "media")
    ):
        hint = "MEDIA_INPUT_REJECTED"
    return safe_provider_diagnostic(
        {**topology, "http_status": code, "status": status, "hint": hint}
    )
