"""Narrow provider compatibility, not arbitrary URL/model guessing."""

from urllib.parse import urlsplit
import copy


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


def answer_tools(tools):
    """Remove server-owned answer fields from every provider's generation schema.

    Do not discard fields from actual responses: strict server validation still
    rejects a model that supplies result data or unauthorized result/source IDs.
    """
    result = copy.deepcopy(tools)

    def clean(schema):
        if isinstance(schema, list):
            for item in schema:
                clean(item)
        elif isinstance(schema, dict):
            props = schema.get("properties", {})
            kind = props.get("type", {}).get("const")
            if kind in {"graph", "verification"} and "result_id" in props:
                props.pop("result", None)
                if "required" in schema:
                    schema["required"] = [
                        field for field in schema["required"] if field != "result"
                    ]
            for value in schema.values():
                clean(value)

    for tool in result:
        fn = tool.get("function", {})
        if fn.get("name") == "render_answer":
            clean(fn.get("parameters", {}))
    return result


def google_answer_tools(tools):
    """Google's forced-function mode rejects the answer's discriminated union.

    Expose the same fields as a plain wire object. PresentedAnswer remains the
    strict server-owned validator; no source, graph or field guard is relaxed.
    """
    result = answer_tools(tools)
    string = {"type": "string"}
    strings = {"type": "array", "items": string}
    for tool in result:
        fn = tool.get("function", {})
        if fn.get("name") != "render_answer":
            continue
        block = {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["text", "equation", "table", "code", "graph"],
                    "description": "Required type field on EVERY block; not a wrapper key.",
                },
                "text": string,
                "latex": string,
                "headers": strings,
                "rows": {"type": "array", "items": strings},
                "language": string,
                "result_id": {
                    "type": "string",
                    "description": "For a graph, the actual current-run computed result_id; never chart data or a graph object.",
                },
                "result_ids": strings,
            },
            "required": ["type"],
        }
        fn["parameters"] = {
            "type": "object",
            "properties": {
                "blocks": {"type": "array", "items": block},
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Only actual relevant read IDs as strings, not source objects.",
                },
                "warnings": strings,
                "response_kind": {
                    "type": "string",
                    "enum": [
                        "teaching",
                        "calculation",
                        "conversation",
                        "clarification",
                        "refusal",
                    ],
                },
            },
            "required": ["blocks"],
        }
        fn["description"] += (
            " Block fields: text requires text; equation requires latex; table requires headers and rows; "
            "code requires text and optional language; graph requires a real returned result_id. "
            "Use only fields belonging to the selected block type. Source IDs must be actual relevant reads."
        )
    return result
