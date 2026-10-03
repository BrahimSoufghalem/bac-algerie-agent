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
