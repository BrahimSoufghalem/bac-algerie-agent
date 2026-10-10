"""Strictly redacted error vocabulary + structural topology, never raw request data."""

import json
import re

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
    result["error_message"] = safe_error_message(value.get("error_message"))
    fields = value.get("error_fields")
    result["error_fields"] = (
        [clean for f in fields[:12] if (clean := safe_field_path(f))]
        if isinstance(fields, list)
        else []
    )
    result["request_shape"] = safe_request_shape(value.get("request_shape"))
    return result


def request_topology(body, protocol="openai"):
    declared = {t.get("function", t).get("name") for t in body.get("tools", [])}
    calls = [
        c
        for m in body.get("messages", [])
        if m.get("role") == "assistant"
        for c in m.get("tool_calls", [])
    ]
    choice = body.get("tool_choice")
    choice = choice if isinstance(choice, dict) else {}
    return {
        "forced_final": choice.get("function", {}).get("name", choice.get("name"))
        == "render_answer",
        "request_shape": request_shape(body, protocol),
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
    raw_text = text
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
    fields = []
    details = error.get("details") if isinstance(error, dict) else None
    for detail in details[:12] if isinstance(details, list) else []:
        if not isinstance(detail, dict):
            continue
        violations = detail.get("fieldViolations")
        for violation in violations[:12] if isinstance(violations, list) else []:
            if isinstance(violation, dict):
                fields.append(violation.get("field"))
    return safe_provider_diagnostic(
        {
            **topology,
            "http_status": code,
            "status": status,
            "hint": hint,
            "error_message": safe_error_message(raw_text),
            "error_fields": fields[:12],
        }
    )


# Only protocol vocabulary survives provider error messages. Arbitrary prose,
# quoted values, URLs, headers, identifiers and signatures become [redacted].
ERROR_WORDS = set(
    "invalid argument arguments missing required not found defined declared declaration function call response tool schema parameters properties property items type object array string number integer boolean role message messages content contents system user assistant model expected received must should match matching previous prior last first allowed unsupported unknown token tokens context length window input output limit maximum minimum exceeds exceeded signature thought_signature thought signature rejected empty duplicate index indices field fields one of too many malformed request requests choice tool_choice function_calling_config allowed_function_names mime mime_type media image format generatecontent stream max_tokens maxoutputtokens thinkingconfig thinkinglevel additionalproperties response_format json_schema json_object cannot unable parse parsing sequence consecutive alternating bad unexpected either exactly only incomplete response schema depth nesting enum nullable null anyof oneof description name id temperature stop_reason".split()
)
ROLES = {"system", "user", "assistant", "tool", "model", "unknown"}
SHAPE_COUNTS = {
    "message_count",
    "omitted_message_count",
    "text_chars",
    "image_count",
    "unpaired_tool_reply_count",
    "max_output_tokens",
    "schema_count",
}
MESSAGE_COUNTS = {"text_chars", "image_count", "tool_calls", "tool_replies"}
FIELD_NAMES = set(
    "messages contents parts role content tools function functionDeclarations functionCall functionResponse parameters properties items required type name arguments tool_choice functionCallingConfig allowedFunctionNames toolConfig generationConfig maxOutputTokens thinkingConfig thinkingLevel temperature max_tokens stream stream_options response_format json_schema systemInstruction text inlineData mimeType data input_schema tool_use tool_result system".split()
)


def safe_error_message(text):
    if not isinstance(text, str):
        return ""
    words = re.findall(r"[A-Za-z_]+", text[:ERROR_BODY_LIMIT])[:100]
    output = []
    for word in words:
        clean = word.lower()
        token = clean if clean in ERROR_WORDS else "[redacted]"
        if token != "[redacted]" or not output or output[-1] != token:
            output.append(token)
    return " ".join(output[:64])[:600]


def safe_field_path(value):
    if not isinstance(value, str) or len(value) > 300:
        return None
    parts = value.split(".")[:12]
    clean = []
    for part in parts:
        match = re.fullmatch(r"([A-Za-z_]+)(?:\[(\d{1,3})\])?", part)
        if not match or match[1] not in FIELD_NAMES:
            clean.append("*")
        else:
            clean.append(match[1] + ("[" + match[2] + "]" if match[2] else ""))
    return ".".join(clean) if any(p != "*" for p in clean) else None


def bounded_count(value):
    return value if type(value) is int and 0 <= value <= 100000000 else 0


def safe_request_shape(value):
    if not isinstance(value, dict) or not value:
        return {}
    protocol = value.get("protocol")
    result = {
        "protocol": protocol
        if isinstance(protocol, str) and protocol in {"openai", "google", "anthropic"}
        else "unknown"
    }
    result.update({k: bounded_count(value.get(k)) for k in SHAPE_COUNTS})
    messages = value.get("messages")
    result["messages"] = []
    for message in messages[:40] if isinstance(messages, list) else []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        result["messages"].append(
            {
                "role": role if isinstance(role, str) and role in ROLES else "unknown",
                **{k: bounded_count(message.get(k)) for k in MESSAGE_COUNTS},
            }
        )
    schemas = value.get("schemas")
    result["schemas"] = []
    for schema in schemas[:40] if isinstance(schemas, list) else []:
        if not isinstance(schema, dict):
            continue
        typ = schema.get("type")
        result["schemas"].append(
            {
                "type": typ
                if isinstance(typ, str)
                and typ.lower()
                in {"object", "array", "string", "number", "integer", "boolean"}
                else "unknown",
                "property_count": bounded_count(schema.get("property_count")),
                "required_count": bounded_count(schema.get("required_count")),
            }
        )
    return result


def request_shape(body, protocol="openai"):
    """Structural lengths/counts only: no model, endpoint, headers, text, args or IDs."""
    native = protocol == "google"
    shapes, seen_calls, replies = [], set(), []
    raw_messages = body.get("contents", []) if native else body.get("messages", [])
    for message in raw_messages:
        content = message.get("parts", []) if native else message.get("content")
        texts, images, calls, tool_replies = (
            [],
            0,
            message.get("tool_calls", []) or [],
            0,
        )
        if isinstance(content, str):
            texts = [content]
        elif isinstance(content, list):
            for block in content:
                if isinstance(block.get("text"), str):
                    texts.append(block["text"])
                if block.get("type") in {"image", "image_url"} or "inlineData" in block:
                    images += 1
                if block.get("type") == "tool_use" or "functionCall" in block:
                    calls = [*calls, block]
                if block.get("type") == "tool_result" or "functionResponse" in block:
                    tool_replies += 1
                    if block.get("tool_use_id"):
                        replies.append(block["tool_use_id"])
        for call in calls:
            if isinstance(call.get("id"), str):
                seen_calls.add(call["id"])
        if message.get("role") == "tool":
            tool_replies += 1
            replies.append(message.get("tool_call_id"))
        shapes.append(
            {
                "role": message.get("role"),
                "text_chars": sum(map(len, texts)),
                "image_count": images,
                "tool_calls": len(calls),
                "tool_replies": tool_replies,
            }
        )
    schemas = []
    for tool in body.get("tools", []):
        functions = (
            tool.get("functionDeclarations", [])
            if native
            else [tool.get("function", tool)]
        )
        for function in functions:
            schema = function.get("parameters", function.get("input_schema", {}))
            schemas.append(
                {
                    "type": schema.get("type"),
                    "property_count": len(schema.get("properties", {})),
                    "required_count": len(schema.get("required", [])),
                }
            )
    result = {
        "protocol": protocol,
        "message_count": len(shapes),
        "omitted_message_count": max(0, len(shapes) - 40),
        "messages": shapes[-40:],
        "text_chars": sum(m["text_chars"] for m in shapes),
        "image_count": sum(m["image_count"] for m in shapes),
        "unpaired_tool_reply_count": sum(r not in seen_calls for r in replies),
        "schema_count": len(schemas),
        "schemas": schemas[:40],
        "max_output_tokens": body.get("generationConfig", {}).get(
            "maxOutputTokens", body.get("max_tokens")
        ),
    }
    return safe_request_shape(result)


async def read_error_payload(response):
    """Bounded transient response inspection; never return raw bytes to persistence."""
    raw = bytearray()
    async for chunk in response.aiter_bytes():
        raw.extend(chunk[: ERROR_BODY_LIMIT + 1 - len(raw)])
        if len(raw) > ERROR_BODY_LIMIT:
            return {}
    try:
        result = json.loads(raw)
        return result if isinstance(result, (dict, list)) else {}
    except (ValueError, TypeError):
        return {}
