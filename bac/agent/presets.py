"""Explicit endpoint/protocol presets. No key guessing or implicit generation."""

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
        "slots": ["agent", "extraction", "selector"],
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
        if slot == "selector" and p["id"] in {"vercel", "custom"}:
            p.update(protocol="evaluation", model="convaiinnovations/laya")
        items.append(p)
    return items


def validate_preset(config, slot):
    if config.protocol == "evaluation" and slot != "selector":
        raise ValueError("Evaluation is only supported in the context-selector slot")
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
    return (
        {"x-api-key": key, "anthropic-version": "2023-06-01"}
        if cfg.get("protocol") == "anthropic"
        else {"Authorization": "Bearer " + key}
    )
