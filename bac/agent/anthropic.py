"""Native Anthropic message/tool adapter. No thinking enabled or hidden retries."""

import json
import httpx
from bac.agent.provider import ChatProvider, ModelError
from bac.agent.provider_errors import provider_diagnostic, request_topology, read_error_payload
from bac.agent.presets import auth_headers
from bac.agent.compat import answer_tools
from bac.vendor.bookforge.vision.provider import validate_base_url


def messages_for_anthropic(messages):
    system, converted = [], []
    for m in messages:
        role = m["role"]
        if role == "system":
            system.append(m["content"])
            continue
        if role == "tool":
            blocks = [
                {
                    "type": "tool_result",
                    "tool_use_id": m["tool_call_id"],
                    "content": m["content"],
                }
            ]
            role = "user"
        else:
            content = m.get("content")
            blocks = (
                [{"type": "text", "text": content}]
                if isinstance(content, str) and content
                else []
            )
            if isinstance(content, list):
                for b in content:
                    if b["type"] == "text":
                        blocks.append({"type": "text", "text": b["text"]})
                    elif b["type"] == "image_url":
                        url = b["image_url"]["url"]
                        if not url.startswith("data:image/"):
                            raise ModelError("INVALID_MODEL_RESPONSE")
                        mime, data = url.split(";base64,", 1)
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": mime[5:],
                                    "data": data,
                                },
                            }
                        )
            for c in m.get("tool_calls", []):
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": c["id"],
                        "name": c["function"]["name"],
                        "input": json.loads(c["function"]["arguments"]),
                    }
                )
        if not blocks:
            continue
        if converted and converted[-1]["role"] == role:
            converted[-1]["content"].extend(blocks)
        else:
            converted.append({"role": role, "content": blocks})
    return "\n\n".join(system), converted


class AnthropicChat(ChatProvider):
    def __init__(self, config, key, allow_private=False, transport=None):
        self.config, self.key, self.allow_private, self.transport = (
            config,
            key,
            allow_private,
            transport,
        )

    async def stream(self, messages, tools):
        async for x in self._stream(messages, tools):
            yield x

    async def final_stream(self, messages, tools):
        async for x in self._stream(messages, tools, True):
            yield x

    async def _stream(self, messages, tools, final=False):
        cfg = self.config
        if self.transport is None:
            await validate_base_url(cfg["base_url"], self.allow_private)
        system, converted = messages_for_anthropic(messages)
        body = {
            "model": cfg["model"],
            "system": system,
            "messages": converted,
            "max_tokens": cfg.get("max_tokens", 4000),
            "temperature": cfg.get("temperature", 0.2),
            "stream": True,
        }
        if tools:
            body["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"]["parameters"],
                }
                for t in answer_tools(tools)
            ]
        if final:
            body["tool_choice"] = {
                "type": "tool",
                "name": final if isinstance(final, str) else "render_answer",
            }
        text = ""
        calls = {}
        usage = {}
        finish = None
        total = 0
        try:
            async with httpx.AsyncClient(
                timeout=cfg.get("timeout", 90),
                transport=self.transport,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                async with client.stream(
                    "POST",
                    cfg["base_url"].rstrip("/") + "/messages",
                    json=body,
                    headers=auth_headers(cfg, self.key),
                ) as r:
                    if r.status_code != 200:
                        raise ModelError(
                            "HTTP_" + str(r.status_code),
                            provider_diagnostic(r.status_code, await read_error_payload(r), request_topology(body, "anthropic")),
                        )
                    async for line in r.aiter_lines():
                        total += len(line)
                        if total > 2_000_000:
                            raise ModelError("RESPONSE_TOO_LARGE")
                        if not line.startswith("data:"):
                            continue
                        p = json.loads(line[5:])
                        kind = p.get("type")
                        if kind == "error":
                            raise ModelError("INVALID_MODEL_RESPONSE")
                        if kind == "message_start":
                            usage.update(p.get("message", {}).get("usage", {}))
                        elif kind == "content_block_start":
                            b = p["content_block"]
                            if b["type"] == "tool_use":
                                calls[p["index"]] = {
                                    "id": b["id"],
                                    "name": b["name"],
                                    "initial": b.get("input", {}),
                                    "args": "",
                                }
                            elif b["type"] == "text":
                                text += b.get("text", "")
                        elif kind == "content_block_delta":
                            d = p["delta"]
                            if d["type"] == "text_delta":
                                text += d["text"]
                                yield {"type": "delta", "text": d["text"]}
                            elif d["type"] == "input_json_delta":
                                c = calls[p["index"]]
                                c["args"] += d["partial_json"]
                                if len(c["args"]) > 100000:
                                    raise ModelError("TOOL_ARGUMENTS_TOO_LARGE")
                        elif kind == "message_delta":
                            finish = p["delta"].get("stop_reason")
                            usage.update(p.get("usage", {}))
            if finish == "max_tokens":
                raise ModelError("OUTPUT_TRUNCATED")
            if finish not in {"end_turn", "tool_use", "stop_sequence"}:
                raise ModelError("MODEL_DID_NOT_COMPLETE")
            if not text and not calls:
                raise ModelError("EMPTY_MODEL_RESPONSE")
            reported = {
                "prompt_tokens": usage.get("input_tokens"),
                "completion_tokens": usage.get("output_tokens"),
            }
            cached = usage.get("cache_read_input_tokens")
            created = usage.get("cache_creation_input_tokens")
            if type(reported["prompt_tokens"]) is int:
                reported["prompt_tokens"] += sum(
                    v for v in (cached, created) if type(v) is int
                )
            if type(cached) is int:
                reported["prompt_tokens_details"] = {"cached_tokens": cached}
            yield {"type": "usage", "data": reported}
            yield {
                "type": "result",
                "message": {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": [
                        {
                            "id": c["id"],
                            "type": "function",
                            "function": {
                                "name": c["name"],
                                "arguments": c["args"] or json.dumps(c["initial"]),
                            },
                        }
                        for _, c in sorted(calls.items())
                    ],
                },
            }
        except ModelError:
            raise
        except (httpx.NetworkError, httpx.TimeoutException):
            raise ModelError("NETWORK_OR_TIMEOUT") from None
        except (ValueError, KeyError, TypeError, httpx.HTTPError):
            raise ModelError("INVALID_MODEL_RESPONSE") from None
