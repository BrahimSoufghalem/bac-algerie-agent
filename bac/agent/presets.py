"""Explicit endpoint/protocol presets. No key guessing or implicit generation."""

GENERATION_OUTPUT_MIN = 6000
FOCUSED_TEMPERATURE_MAX = 0.1


def generation_config(config, slot, *, effective=True):
    """Non-mutating compatibility defaults for old and new saved configurations.

    Focus is local temperature policy, NOT an invented provider reasoning option.
    Keep configured temperature when displaying/saving so disabling focus restores
    an owner's model-specific setting. Extraction settings are never changed.
    """
    result = dict(config)
    if slot not in {"agent", "selector"}:
        return result
    result["max_tokens"] = max(
        result.get("max_tokens") or GENERATION_OUTPUT_MIN, GENERATION_OUTPUT_MIN
    )
    result.setdefault("focused_mode", True)
    if slot == "selector":
        result["temperature"] = 0
    elif effective and result["focused_mode"]:
        result["temperature"] = min(
            result.get("temperature", FOCUSED_TEMPERATURE_MAX),
            FOCUSED_TEMPERATURE_MAX,
        )
    return result


PRESETS = [
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "protocol": "openai",
        "model": "gpt-4.1-mini",
        "temperature": 0.2,
        "slots": ["agent", "extraction", "selector"],
    },
    {
        "id": "google",
        "name": "Google AI Studio",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "protocol": "openai",
        "model": "gemini-3.5-flash-lite",
        "temperature": 1.0,
        "slots": ["agent", "extraction", "selector"],
    },
    {
        "id": "anthropic",
        "name": "Anthropic / Claude",
        "base_url": "https://api.anthropic.com/v1",
        "protocol": "anthropic",
        "model": "claude-sonnet-4-5",
        "temperature": 0.2,
        "slots": ["agent", "extraction"],
    },
    {
        "id": "vercel",
        "name": "Vercel AI Gateway",
        "base_url": "https://ai-gateway.vercel.sh/v1",
        "protocol": "openai",
        "model": "openai/gpt-4.1-mini",
        "temperature": 0.2,
        "slots": ["agent", "extraction", "selector"],
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "protocol": "openai",
        "model": "openai/gpt-4.1-mini",
        "temperature": 0.2,
        "slots": ["agent", "extraction", "selector"],
    },
    {
        "id": "custom",
        "name": "Custom / compatible API",
        "base_url": "",
        "protocol": "openai",
        "model": "",
        "temperature": 0.2,
        "slots": ["agent", "extraction", "selector"],
    },
]


def presets(slot):
    items = []
    for entry in PRESETS:
        if slot not in entry["slots"]:
            continue
        p = {**entry}
        if slot == "agent":
            p.update(
                temperature=FOCUSED_TEMPERATURE_MAX,
                max_tokens=GENERATION_OUTPUT_MIN,
                focused_mode=True,
            )
        if slot == "selector":
            p.update(temperature=0,max_tokens=GENERATION_OUTPUT_MIN)
        if slot == "selector" and p["id"] == "google":
            p.update(
                name="Google AI Studio / Gemini LLM router",
                base_url="https://generativelanguage.googleapis.com/v1beta",
                protocol="google",
                model="gemini-3.5-flash-lite",
                temperature=0,
                max_tokens=GENERATION_OUTPUT_MIN,
            )
        items.append(p)
    return items


def validate_preset(config, slot):
    if slot == "selector" and config.protocol not in {"openai", "google"}:
        raise ValueError("Reference routing requires an OpenAI-compatible or native Google LLM")
    if config.protocol == "google":
        if slot != "selector":
            raise ValueError(
                "Native Google routing is only supported in the selector slot"
            )
        if (
            config.base_url.rstrip("/")
            != "https://generativelanguage.googleapis.com/v1beta"
        ):
            raise ValueError(
                "Native Google routing requires the official Google endpoint"
            )
    if config.provider != "custom":
        preset = next((p for p in presets(slot) if p["id"] == config.provider), None)
        if (
            not preset
            or config.base_url.rstrip("/") != preset["base_url"].rstrip("/")
            or config.protocol != preset["protocol"]
        ):
            raise ValueError(
                "Provider preset endpoint/protocol mismatch; use Custom for another compatible endpoint"
            )


def auth_headers(cfg, key):
    if cfg.get("protocol") == "google":
        return {"x-goog-api-key": key}
    return (
        {"x-api-key": key, "anthropic-version": "2023-06-01"}
        if cfg.get("protocol") == "anthropic"
        else {"Authorization": "Bearer " + key}
    )
