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
    for tool in result:
        fn = tool.get("function", {})
        if fn.get("name") != "render_answer":
            continue
        schema = fn["parameters"]
        definitions = schema.pop("$defs", {})

        def inline(value):
            if isinstance(value, list):
                return [inline(item) for item in value]
            if not isinstance(value, dict):
                return value
            if "$ref" in value:
                name = value["$ref"].removeprefix("#/$defs/")
                return inline(definitions[name] | {
                    k: v for k, v in value.items() if k != "$ref"
                })
            return {key: inline(item) for key, item in value.items()}

        # Only flatten the visible block union that Google cannot accept.
        # All top-level fields, bounds and provenance subcontracts come from
        # PresentedAnswer; a second hand-written schema must never drift again.
        variants = [
            inline(item)
            for item in schema["properties"]["blocks"]["items"]["oneOf"]
        ]
        properties, kinds = {}, []
        for variant in variants:
            kinds.append(variant["properties"]["type"]["const"])
            for name, field in variant["properties"].items():
                if name != "type":
                    if name in properties and properties[name] != field:
                        previous = properties[name]
                        if previous.get("type") != field.get("type"):
                            raise ValueError("Conflicting answer block field")
                        # A shared text field has different per-kind size caps.
                        # Admit either variant; the server enforces the chosen
                        # block kind's exact constraints.
                        merged = {
                            k: v for k, v in previous.items() if field.get(k) == v
                        }
                        for bound, combine in (
                            ("maxLength", max), ("maxItems", max),
                            ("minLength", min), ("minItems", min),
                        ):
                            if bound in previous and bound in field:
                                merged[bound] = combine(previous[bound], field[bound])
                        properties[name] = merged
                    else:
                        properties[name] = field
        block = {
            "type": "object",
            "additionalProperties": False,
            "properties": properties | {
                "type": {
                    "type": "string",
                    "enum": kinds,
                    "description": "Required type field on EVERY block; not a wrapper key.",
                },
            },
            "required": ["type"],
        }
        schema["properties"]["blocks"]["items"] = block
        fn["parameters"] = inline(schema)
        fn["description"] += (
            " Block fields: text requires text; equation requires latex; table requires headers and rows; "
            "code requires text and optional language; graph requires a real returned result_id. "
            "Use only fields belonging to the selected block type. Source IDs must be actual relevant reads."
        )
    return result
