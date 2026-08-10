"""DeepSeek LLM client (OpenAI-compatible chat completions API).

The client enforces agent output schemas with Pydantic immediately after
the API call returns (CONVENTIONS.md §1.3) and supports the Screener's
function-calling loop. Agents never call a vendor API directly.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.logging_conf import get_logger

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 24


class DeepSeekClientError(RuntimeError):
    """Raised for transport, API, or schema errors from the LLM provider."""


class DeepSeekClient:
    """Thin async client over DeepSeek's OpenAI-compatible endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def complete_json(
        self,
        *,
        model: str,
        temperature: float,
        system: str,
        input_data: dict[str, Any],
        response_schema: type[BaseModel],
    ) -> dict[str, Any]:
        """One chat completion returning JSON validated against ``response_schema``."""
        content = await self._chat(
            model=model,
            temperature=temperature,
            system=system,
            user_message=json.dumps(input_data, default=str),
            response_format={"type": "json_object"},
        )
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise DeepSeekClientError("LLM returned invalid JSON") from exc
        try:
            return response_schema.model_validate(parsed).model_dump()
        except ValidationError as exc:
            raise DeepSeekClientError(f"LLM output failed schema validation: {exc}") from exc

    async def complete_text(
        self,
        *,
        model: str,
        temperature: float,
        system: str,
        input_data: dict[str, Any],
    ) -> str:
        """One chat completion returning the raw text content."""
        return await self._chat(
            model=model,
            temperature=temperature,
            system=system,
            user_message=json.dumps(input_data, default=str),
        )

    async def complete_with_tools(
        self,
        *,
        model: str,
        temperature: float,
        system: str,
        user_message: str,
        tools: list[dict[str, Any]],
        handlers: dict[str, Callable[[dict[str, Any]], list[dict[str, Any]]]],
    ) -> str:
        """Run the tool-calling loop until the model returns a final answer.

        ``handlers`` maps tool name -> sync function receiving parsed
        arguments; the client feeds results back as ``tool`` role
        messages. External tool output is returned as data, never as
        instruction-bearing message content (CONVENTIONS.md §3.3).

        The Screener may legitimately need one round per tool call (several
        sub-exposures x search_holdings/search_sector), so the cap is high.
        If the model is still issuing tool calls when the cap is hit, this
        logs a warning and returns the latest assistant text (possibly an
        empty string) instead of failing the Run; callers must treat that as
        "no final answer" and fall back to deterministic assembly.
        """
        if not self._settings.deepseek_api_key:
            raise DeepSeekClientError("DEEPSEEK_API_KEY is not configured")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        last_content = ""
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self._post_chat(
                model=model,
                temperature=temperature,
                messages=messages,
                tools=tools,
            )
            message = response["choices"][0]["message"]
            last_content = str(message.get("content") or "")
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                return last_content
            messages.append(message)
            for tool_call in tool_calls:
                name = tool_call["function"]["name"]
                try:
                    arguments = json.loads(tool_call["function"]["arguments"] or "{}")
                except json.JSONDecodeError as exc:
                    raise DeepSeekClientError(
                        f"tool call {name} had malformed arguments"
                    ) from exc
                handler = handlers.get(name)
                if handler is None:
                    raise DeepSeekClientError(f"no handler registered for tool {name}")
                result = handler(arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": json.dumps(result, default=str),
                    }
                )
        logger.warning(
            "tool_calling_loop_capped",
            rounds=MAX_TOOL_ROUNDS,
            reason="model kept issuing tool calls past the cap",
        )
        return last_content

    async def _chat(
        self,
        *,
        model: str,
        temperature: float,
        system: str,
        user_message: str,
        response_format: dict[str, str] | None = None,
    ) -> str:
        if not self._settings.deepseek_api_key:
            raise DeepSeekClientError("DEEPSEEK_API_KEY is not configured")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ]
        response = await self._post_chat(
            model=model,
            temperature=temperature,
            messages=messages,
            response_format=response_format,
        )
        content = response["choices"][0]["message"].get("content")
        return str(content or "")

    async def _post_chat(
        self,
        *,
        model: str,
        temperature: float,
        messages: list[dict[str, Any]],
        response_format: dict[str, str] | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": messages,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        if tools is not None:
            payload["tools"] = tools
        headers = {
            "Authorization": f"Bearer {self._settings.deepseek_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(
                base_url=self._settings.deepseek_base_url, timeout=90.0
            ) as client:
                response = await client.post("/chat/completions", json=payload, headers=headers)
                response.raise_for_status()
                return cast(dict[str, Any], response.json())
        except httpx.HTTPError as exc:
            raise DeepSeekClientError(f"DeepSeek request failed: {exc}") from exc


def stubbing_enabled() -> bool:
    """True when agents should use deterministic stubs instead of the LLM."""
    settings = get_settings()
    return bool(settings.stub_agents or not settings.deepseek_api_key)
