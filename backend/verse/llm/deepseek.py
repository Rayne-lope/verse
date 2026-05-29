from __future__ import annotations

import asyncio
import os
from typing import Any

from verse.config import LLMConfig
from verse.llm.base import LLMAdapter, LLMResponse
from verse.persistence.keychain import get_api_key


class DeepSeekAdapter(LLMAdapter):
    def __init__(
        self,
        config: LLMConfig | None = None,
        *,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config or LLMConfig()
        self.api_key = api_key
        self._client = client

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        return await asyncio.to_thread(self._chat_sync, messages, tools)

    def _chat_sync(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if tools:
            request["tools"] = tools

        response = self.client.chat.completions.create(**request)
        message = response.choices[0].message
        text = getattr(message, "content", None) or ""
        tool_calls = _serialize_tool_calls(getattr(message, "tool_calls", None))
        return LLMResponse(text=str(text), tool_calls=tool_calls, raw=response)

    @property
    def client(self) -> Any:
        if self._client is None:
            api_key = (
                self.api_key
                or os.getenv("DEEPSEEK_API_KEY")
                or get_api_key("deepseek")
            )
            if not api_key:
                raise RuntimeError("DeepSeek API key not found in env or Keychain")
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "openai is required for DeepSeekAdapter. Install backend dependencies first."
                ) from exc
            self._client = OpenAI(
                api_key=api_key,
                base_url=self.config.base_url,
            )
        return self._client


def _serialize_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    if not tool_calls:
        return []

    serialized = []
    for tool_call in tool_calls:
        if isinstance(tool_call, dict):
            serialized.append(tool_call)
            continue
        function = getattr(tool_call, "function", None)
        serialized.append(
            {
                "id": getattr(tool_call, "id", None),
                "type": getattr(tool_call, "type", None),
                "function": {
                    "name": getattr(function, "name", None),
                    "arguments": getattr(function, "arguments", None),
                },
            }
        )
    return serialized
