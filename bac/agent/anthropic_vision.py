"""Native Claude extraction through an explicit schema tool, never chat endpoint emulation."""

import base64, json
from bac.agent.anthropic import AnthropicChat
from bac.agent.provider import ModelError
from bac.vendor.bookforge.vision.provider import VisionProvider, ProviderError
from bac.vendor.bookforge.models.page import PageDocument
import yaml


class AnthropicVision(VisionProvider):
    def __init__(self, cfg, key, settings):
        self.cfg, self.key, self.settings = cfg, key, settings

    async def extract(self, image, page, width, height):
        prompt = yaml.safe_load(self.settings.prompt_file.read_text())["vision"]
        raw = image.read_bytes()
        mime = "image/png" if raw.startswith(b"\x89PNG") else "image/jpeg"
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"PDF page={page}; width={width}; height={height}. Call extract_page with the complete structured transcription.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": "data:"
                            + mime
                            + ";base64,"
                            + base64.b64encode(raw).decode()
                        },
                    },
                ],
            },
        ]
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "extract_page",
                    "description": "Return the transcribed page exactly; unknown content remains unknown.",
                    "parameters": PageDocument.model_json_schema(),
                },
            }
        ]
        usage = {}
        message = None
        try:
            provider = AnthropicChat(
                self.cfg, self.key, self.settings.allow_private_model_urls
            )
            async for item in provider._stream(messages, tools, "extract_page"):
                if item["type"] == "usage":
                    usage = item["data"]
                elif item["type"] == "result":
                    message = item["message"]
            calls = message.get("tool_calls", []) if message else []
            if len(calls) != 1 or calls[0]["function"]["name"] != "extract_page":
                raise ValueError()
            return PageDocument.model_validate(
                json.loads(calls[0]["function"]["arguments"])
            ), usage
        except ModelError as exc:
            raise ProviderError(
                str(exc),
                retryable=str(exc) in {"HTTP_429", "HTTP_503", "NETWORK_OR_TIMEOUT"},
            ) from None
        except (ValueError, KeyError, TypeError):
            raise ProviderError(
                "INVALID_EXTRACTION_RESPONSE", retryable=False
            ) from None
