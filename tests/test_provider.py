import json
import httpx
import pytest
from bac.agent.provider import OpenAIChat, ModelError

CFG = {"base_url": "https://fixture.invalid/v1", "model": "fixture", "timeout": 5}


@pytest.mark.asyncio
async def test_actual_sse_parser_fragments_tools_usage_no_reasoning():
    async def handler(request):
        body = json.loads(request.content)
        assert body["stream"] and body["model"] == "fixture"
        chunks = [
            {
                "choices": [
                    {
                        "delta": {
                            "reasoning_content": "NEVER EXPOSE THIS",
                            "content": "مرحبًا ",
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "a",
                                    "function": {
                                        "name": "get_section",
                                        "arguments": '{"node_',
                                    },
                                }
                            ]
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {"index": 0, "function": {"arguments": 'id":"x"}'}}
                            ]
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            },
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 7,
                    "completion_tokens": 9,
                    "prompt_tokens_details": {"cached_tokens": 2},
                },
            },
        ]
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text="".join("data: " + json.dumps(c) + "\n\n" for c in chunks)
            + "data: [DONE]\n\n",
        )

    items = [
        i
        async for i in OpenAIChat(
            CFG, "test", transport=httpx.MockTransport(handler)
        ).stream([], [])
    ]
    assert "NEVER EXPOSE" not in json.dumps(items)
    assert (
        items[-1]["message"]["tool_calls"][0]["function"]["arguments"]
        == '{"node_id":"x"}'
    )
    assert items[-2]["data"]["prompt_tokens_details"]["cached_tokens"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(429, "HTTP_429"), (503, "HTTP_503")])
async def test_no_hidden_paid_provider_retry(status, expected):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    with pytest.raises(ModelError, match=expected):
        _ = [
            i
            async for i in OpenAIChat(
                CFG, "test", transport=httpx.MockTransport(handler)
            ).stream([], [])
        ]
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_truncation_never_accepted_as_finished():
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "partial"},
                        "finish_reason": "length",
                    }
                ]
            },
        )

    with pytest.raises(ModelError, match="OUTPUT_TRUNCATED"):
        _ = [
            i
            async for i in OpenAIChat(
                CFG, "test", transport=httpx.MockTransport(handler)
            ).stream([], [])
        ]


@pytest.mark.asyncio
async def test_final_round_forces_only_render_without_retry_or_sampling_change():
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "f",
                                    "type": "function",
                                    "function": {
                                        "name": "render_answer",
                                        "arguments": '{"blocks":[{"type":"text","text":"hello"}],"source_ids":[]}',
                                    },
                                }
                            ],
                        },
                    }
                ]
            },
        )

    tools = [
        {
            "type": "function",
            "function": {"name": "render_answer", "parameters": {"type": "object"}},
        }
    ]
    p = OpenAIChat(CFG, "fixture-only", transport=httpx.MockTransport(handler))
    results = [
        x async for x in p.final_stream([{"role": "user", "content": "hello"}], tools)
    ]
    assert len(seen) == 1 and seen[0]["tools"] == tools
    assert seen[0]["tool_choice"] == {
        "type": "function",
        "function": {"name": "render_answer"},
    }
    assert seen[0]["max_tokens"] == 4000
    assert (
        results[-1]["message"]["tool_calls"][0]["function"]["name"] == "render_answer"
    )


@pytest.mark.asyncio
async def test_final_choice_rejected_by_provider_has_no_hidden_paid_fallback():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(400)

    with pytest.raises(ModelError, match="HTTP_400"):
        _ = [
            i
            async for i in OpenAIChat(
                CFG, "fixture", transport=httpx.MockTransport(handler)
            ).final_stream([], [])
        ]
    assert len(calls) == 1
