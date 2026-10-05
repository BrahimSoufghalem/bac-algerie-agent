"""Narrow provider compatibility, not arbitrary URL/model guessing."""

from urllib.parse import urlsplit


def google_openai(base):
    url = urlsplit(base)
    return (
        url.scheme == "https"
        and url.hostname == "generativelanguage.googleapis.com"
        and url.port in (None, 443)
        and not url.username
        and not url.password
        and not url.query
        and not url.fragment
        and url.path.rstrip("/")
        in ("/v1beta/openai", "/v1beta/openai/chat/completions")
    )


def model_identity(base, model):
    # Google lists models/NAME but its OpenAI completion examples use NAME.
    # Do not strip real namespaces from OpenRouter or other providers.
    return model.removeprefix("models/") if google_openai(base) else model


def automatic_prefix_cache(base):
    """Known direct automatic-cache endpoints; no assumptions about intermediaries."""
    url = urlsplit(base)
    return (
        url.scheme == "https"
        and url.hostname in {"api.deepseek.com", "api.openai.com"}
        and url.port in (None, 443)
        and not url.username
        and not url.password
        and not url.query
        and not url.fragment
    )


def google_answer_tools(tools):
    """Google's forced-function mode rejects the answer's discriminated union.

    Expose the same fields as a plain wire object. PresentedAnswer remains the
    strict server-owned validator; no source, graph or field guard is relaxed.
    """
    import copy

    result = copy.deepcopy(tools)
    string = {"type": "string"}
    strings = {"type": "array", "items": string}
    for tool in result:
        fn = tool.get("function", {})
        if fn.get("name") != "render_answer":
            continue
        block = {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["text", "equation", "table", "code", "graph"]},
                "text": string,
                "latex": string,
                "headers": strings,
                "rows": {"type": "array", "items": strings},
                "language": string,
                "result_id": string,
                "result_ids": strings,
            },
            "required": ["type"],
        }
        fn["parameters"] = {
            "type": "object",
            "properties": {
                "blocks": {"type": "array", "items": block},
                "source_ids": strings,
                "warnings": strings,
                "response_kind": {"type": "string", "enum": ["teaching", "calculation", "conversation", "clarification", "refusal"]},
            },
            "required": ["blocks"],
        }
        fn["description"] += (
            " Block fields: text requires text; equation requires latex; table requires headers and rows; "
            "code requires text and optional language; graph requires a real returned result_id. "
            "Use only fields belonging to the selected block type. Source IDs must be actual relevant reads."
        )
    return result
