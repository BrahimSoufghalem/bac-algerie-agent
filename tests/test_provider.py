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
