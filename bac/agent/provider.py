from abc import ABC, abstractmethod
import json
import httpx
from bac.vendor.bookforge.vision.provider import validate_base_url
from bac.agent.rate_limit import reserve_input
from bac.agent.compat import (
    answer_tools,
    google_answer_tools,
    google_openai,
    model_identity,
)
from bac.agent.provider_errors import (
    read_error_payload,
    provider_diagnostic,
    request_topology,
)


class ModelError(Exception):
    def __init__(self, code, diagnostic=None):
        super().__init__(code)
        self.diagnostic = diagnostic


def check_error(payload, topology=None):
    if payload.get("error"):
        error = payload["error"]
        code = error.get("code") if isinstance(error, dict) else None
        if isinstance(code, int) and not isinstance(code, bool) and 400 <= code <= 599:
            raise ModelError(
                "HTTP_" + str(code), provider_diagnostic(code, payload, topology or {})
            )
        raise ModelError("INVALID_MODEL_RESPONSE")


def merge_signature(target, incoming):
    """Forward only the opaque continuity token; never thought text/other extras."""
    extra = incoming.get("extra_content")
    google = extra.get("google") if isinstance(extra, dict) else None
    signature = google.get("thought_signature") if isinstance(google, dict) else None
    if signature is None:
        return
    if not isinstance(signature, str):
        raise ModelError("INVALID_MODEL_RESPONSE")
    if len(signature) > 64000:
        raise ModelError("PROVIDER_METADATA_TOO_LARGE")
    if not signature:
        return
    previous = (
        target.get("extra_content", {}).get("google", {}).get("thought_signature")
    )
    if previous is not None and previous != signature:
        # A continuity token is an atom, not text to concatenate or fabricate.
        raise ModelError("INVALID_MODEL_RESPONSE")
    target["extra_content"] = {"google": {"thought_signature": signature}}


def canonical_message(message):
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise ModelError("INVALID_MODEL_RESPONSE")
    calls = []
    for call in message.get("tool_calls") or []:
        fn = call["function"]
        if not isinstance(fn["name"], str) or not isinstance(fn["arguments"], str):
            raise ModelError("INVALID_MODEL_RESPONSE")
        if len(fn["arguments"]) > 100000:
            raise ModelError("TOOL_ARGUMENTS_TOO_LARGE")
        target = {
            "id": call["id"],
            "type": "function",
            "function": {"name": fn["name"], "arguments": fn["arguments"]},
        }
        merge_signature(target, call)
        calls.append(target)
    if sum(len(json.dumps(c.get("extra_content", {}))) for c in calls) > 256000:
        raise ModelError("PROVIDER_METADATA_TOO_LARGE")
    if not content and not calls:
        raise ModelError("EMPTY_MODEL_RESPONSE")
    return {"role": "assistant", "content": content or None, "tool_calls": calls}


class ChatProvider(ABC):
    # Capability flags. Engine freezes declarations only for known automatic
    # cache providers, reported hits, or mandatory protocol continuity. Unknown
    # uncached providers may shrink final declarations to save cold input cost.
    # Server-side allowlists and forced final calls still restrict execution.
    stable_tool_manifest = True
    stable_request_prefix = True

    @abstractmethod
    async def stream(self, messages, tools):
        yield {}

    async def decision_stream(self, messages, tools):
        async for item in self.stream(messages, tools):
            yield item

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

    async def decision_stream(self, messages, tools):
        async for item in self._stream(messages, tools, tool_choice={"type": "function", "function": {"name": "assess_context"}}):
            yield item

    async def _stream(self, messages, tools, tool_choice=None):
        cfg = self.config
        if self.transport is None:
            await validate_base_url(cfg["base_url"], self.allow_private)
        endpoint = cfg["base_url"].rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint += "/chat/completions"
        body = {
            "model": model_identity(cfg["base_url"], cfg["model"]),
            "messages": messages,
            "tools": (
                google_answer_tools(tools)
                if google_openai(cfg["base_url"])
                else answer_tools(tools)
            ),
            "temperature": cfg.get("temperature", 0.2),
            "max_tokens": cfg.get("max_tokens", 4000),
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        pacer, reservation = await reserve_input(cfg, self.key, body, self.transport)
        topology = request_topology(body)
        content = ""
        calls = {}
        call_ids = {}
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
                        # Bounded, transient inspection: no raw error body enters logs/events.
                        payload = await read_error_payload(response)
                        raise ModelError(
                            "HTTP_" + str(response.status_code),
                            provider_diagnostic(
                                response.status_code,
                                payload,
                                topology,
                                response.headers.get("retry-after"),
                            ),
                        )
                    if "text/event-stream" not in response.headers.get(
                        "content-type", ""
                    ):
                        payload = await response.aread()
                        if len(payload) > 2_000_000:
                            raise ModelError("RESPONSE_TOO_LARGE")
                        result = json.loads(payload)
                        check_error(result, topology)
                        usage = result.get("usage", {})
                        choice = result["choices"][0]
                        message = canonical_message(choice["message"])
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
                        check_error(payload, topology)
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
                                index = tc.get("index")
                                call_id = tc.get("id")
                                if index is None and google_openai(cfg["base_url"]):
                                    # Google may emit complete parallel calls with IDs
                                    # but no OpenAI index. Do not collapse them into 0.
                                    if isinstance(call_id, str) and call_id:
                                        index = call_ids.get(call_id)
                                        if index is None:
                                            index = max(calls, default=-1) + 1
                                    elif len(calls) == 1:
                                        index = next(iter(calls))
                                    else:
                                        raise ModelError("AMBIGUOUS_TOOL_CALL_DELTA")
                                elif index is None:
                                    index = 0
                                if type(index) is not int or index < 0:
                                    raise ModelError("INVALID_MODEL_RESPONSE")
                                if call_id:
                                    if not isinstance(call_id, str):
                                        raise ModelError("INVALID_MODEL_RESPONSE")
                                    prior_index = call_ids.get(call_id)
                                    if prior_index is not None and prior_index != index:
                                        raise ModelError("INVALID_MODEL_RESPONSE")
                                    previous_id = calls.get(index, {}).get("id")
                                    if previous_id and previous_id != call_id:
                                        raise ModelError("INVALID_MODEL_RESPONSE")
                                    call_ids[call_id] = index
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
                                merge_signature(target, tc)
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
                "message": canonical_message(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": [calls[i] for i in sorted(calls)],
                    }
                ),
            }
        except ModelError as exc:
            if pacer and str(exc) == "HTTP_429":
                pacer.rate_limited((exc.diagnostic or {}).get("retry_after_seconds"))
            raise
        except (httpx.TimeoutException, httpx.NetworkError):
            raise ModelError("NETWORK_OR_TIMEOUT") from None
        except (ValueError, KeyError, TypeError, httpx.HTTPError):
            raise ModelError("INVALID_MODEL_RESPONSE") from None
        finally:
            if pacer:
                pacer.settle(reservation, usage.get("prompt_tokens"))
