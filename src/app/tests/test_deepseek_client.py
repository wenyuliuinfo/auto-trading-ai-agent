"""DeepSeek tool-calling loop tests (graceful cap + normal completion)."""

from __future__ import annotations

from typing import Any

import pytest

from app.integrations.deepseek_client import MAX_TOOL_ROUNDS, DeepSeekClient


def _tool_message(tool_call_id: str = "call_1") -> dict[str, Any]:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tool_call_id,
                            "type": "function",
                            "function": {
                                "name": "search_sector",
                                "arguments": '{"keyword": "grid"}',
                            },
                        }
                    ],
                }
            }
        ]
    }


@pytest.mark.asyncio
async def test_tool_loop_caps_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    client = DeepSeekClient()
    calls = 0

    async def fake_post_chat(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _tool_message(f"call_{calls}")

    monkeypatch.setattr(client, "_post_chat", fake_post_chat)
    result = await client.complete_with_tools(
        model="deepseek-v4-pro",
        temperature=0.5,
        system="system",
        user_message="search",
        tools=[],
        handlers={"search_sector": lambda args: []},
    )
    assert result == ""
    assert calls == MAX_TOOL_ROUNDS


@pytest.mark.asyncio
async def test_tool_loop_returns_content_when_model_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = DeepSeekClient()
    responses = [
        _tool_message("call_1"),
        {
            "choices": [
                {"message": {"role": "assistant", "content": "final answer"}}
            ]
        },
    ]

    async def fake_post_chat(**_: Any) -> dict[str, Any]:
        return responses.pop(0)

    monkeypatch.setattr(client, "_post_chat", fake_post_chat)
    result = await client.complete_with_tools(
        model="deepseek-v4-pro",
        temperature=0.5,
        system="system",
        user_message="search",
        tools=[],
        handlers={"search_sector": lambda args: []},
    )
    assert result == "final answer"
