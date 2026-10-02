from abc import ABC, abstractmethod
import json
import httpx
from bac.vendor.bookforge.vision.provider import validate_base_url


class ModelError(Exception):
    pass


class ChatProvider(ABC):
    @abstractmethod
    async def stream(self, messages, tools):
        yield {}

    async def final_stream(self, messages, tools):
        """Compatibility default: adapters may force the advertised final tool."""
        async for item in self.stream(messages, tools):
            yield item


class OpenAIChat(ChatProvider):
    def __init__(self, config, key, allow_private=False, transport=None):
        self.config = config
        self.key = key
        self.allow_private = allow_private
        self.transport = transport

    async def stream(self, messages, tools):
        async for item in self._stream(messages, tools):
            yield item

    async def final_stream(self, messages, tools):
        async for item in self._stream(
            messages,
            tools,
            tool_choice={"type": "function", "function": {"name": "render_answer"}},
        ):
            yield item

    async def _stream(self, messages, tools, tool_choice=None):
        cfg = self.config
        if self.transport is None:
            await validate_base_url(cfg["base_url"], self.allow_private)
        endpoint = cfg["base_url"].rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        body = {
            "model": cfg["model"],
            "messages": messages,
            "tools": tools,
            "temperature": cfg.get("temperature", 0.2),
            "max_tokens": cfg.get("max_tokens", 4000),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        content = ""
        calls = {}
        finish = "stop"
        usage = {}
        total = 0
        try:
            async with httpx.AsyncClient(
                timeout=cfg.get("timeout", 90),
                transport=self.transport,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                async with client.stream(
                    "POST",
                    endpoint,
                    json=body,
                    headers={"Authorization": "Bearer " + self.key},
                ) as response:
                    if response.status_code != 200:
                        raise ModelError("HTTP_" + str(response.status_code))
                    if "text/event-stream" not in response.headers.get(
                        "content-type", ""
                    ):
                        payload = await response.aread()
                        if len(payload) > 2_000_000:
                            raise ModelError("RESPONSE_TOO_LARGE")
                        result = json.loads(payload)
                        usage = result.get("usage", {})
                        choice = result["choices"][0]
                        message = choice["message"]
                        finish = choice.get("finish_reason", "stop")
                        if message.get("content"):
                            yield {"type": "delta", "text": message["content"]}
                        if finish == "length":
                            raise ModelError("OUTPUT_TRUNCATED")
                        yield {"type": "usage", "data": usage}
                        yield {"type": "result", "message": message}
                        return
                    async for line in response.aiter_lines():
                        total += len(line)
                        if total > 2_000_000:
                            raise ModelError("RESPONSE_TOO_LARGE")
                        if not line.startswith("data:"):
                            continue
                        text = line[5:].strip()
                        if text == "[DONE]":
                            break
                        payload = json.loads(text)
                        if payload.get("usage"):
                            usage = payload["usage"]
                        for choice in payload.get("choices", []):
                            delta = choice.get("delta", {})
                            if choice.get("finish_reason"):
                                finish = choice["finish_reason"]
                            # reasoning_content and other internal model traces are deliberately ignored.
                            if delta.get("content"):
                                content += delta["content"]
                                yield {"type": "delta", "text": delta["content"]}
                            for tc in delta.get("tool_calls", []):
                                index = tc.get("index", 0)
                                target = calls.setdefault(
                                    index,
                                    {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    },
                                )
                                if tc.get("id"):
                                    target["id"] = tc["id"]
                                fn = tc.get("function", {})
                                target["function"]["name"] += fn.get("name", "")
                                target["function"]["arguments"] += fn.get(
                                    "arguments", ""
                                )
                                if len(target["function"]["arguments"]) > 100000:
                                    raise ModelError("TOOL_ARGUMENTS_TOO_LARGE")
            if finish == "length":
                raise ModelError("OUTPUT_TRUNCATED")
            if finish not in ("stop", "tool_calls", "function_call"):
                raise ModelError("MODEL_DID_NOT_COMPLETE")
            if not content and not calls:
                raise ModelError("EMPTY_MODEL_RESPONSE")
            yield {"type": "usage", "data": usage}
            yield {
                "type": "result",
                "message": {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [calls[i] for i in sorted(calls)],
                },
            }
        except ModelError:
            raise
        except (httpx.TimeoutException, httpx.NetworkError):
            raise ModelError("NETWORK_OR_TIMEOUT") from None
        except (ValueError, KeyError, TypeError, httpx.HTTPError):
            raise ModelError("INVALID_MODEL_RESPONSE") from None
