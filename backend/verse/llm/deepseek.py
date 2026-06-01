from __future__ import annotations

import asyncio
import os
import threading
from copy import deepcopy
from typing import Any, AsyncIterator, Iterator

from verse.config import LLMConfig
from verse.llm.base import LLMAdapter, LLMResponse, LLMStreamEvent
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

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[LLMStreamEvent | None] = asyncio.Queue()

        def produce() -> None:
            try:
                for event in self._stream_chat_sync(messages, tools):
                    loop.call_soon_threadsafe(queue.put_nowait, event)
            except Exception as exc:
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    LLMStreamEvent(type="error", raw=exc),
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        thread = threading.Thread(target=produce, daemon=True)
        thread.start()

        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

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

    def _stream_chat_sync(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[LLMStreamEvent]:
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "stream": True,
        }
        if tools:
            request["tools"] = tools

        stream = self.client.chat.completions.create(**request)
        pending_tool_calls: dict[int, dict[str, Any]] = {}
        emitted_tool_indexes: set[int] = set()

        for chunk in stream:
            choice = _first_choice(chunk)
            if choice is None:
                continue

            delta = _get_attr(choice, "delta")
            if delta is not None:
                content = _get_attr(delta, "content")
                if content:
                    yield LLMStreamEvent(
                        type="text_delta",
                        text=str(content),
                        raw=chunk,
                    )

                for tool_delta in _iter_tool_call_deltas(_get_attr(delta, "tool_calls")):
                    index = _get_attr(tool_delta, "index")
                    if index is None:
                        index = len(pending_tool_calls)
                    tool_call = pending_tool_calls.setdefault(
                        int(index),
                        {
                            "id": None,
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    _merge_tool_call_delta(tool_call, tool_delta)
                    yield LLMStreamEvent(
                        type="tool_call_delta",
                        tool_call=deepcopy(tool_call),
                        raw=chunk,
                    )

            finish_reason = _get_attr(choice, "finish_reason")
            if finish_reason == "tool_calls":
                for index, tool_call in sorted(pending_tool_calls.items()):
                    emitted_tool_indexes.add(index)
                    yield LLMStreamEvent(
                        type="tool_call_done",
                        tool_call=deepcopy(tool_call),
                        raw=chunk,
                    )

        for index, tool_call in sorted(pending_tool_calls.items()):
            if index in emitted_tool_indexes:
                continue
            yield LLMStreamEvent(
                type="tool_call_done",
                tool_call=deepcopy(tool_call),
                raw=None,
            )

        yield LLMStreamEvent(type="done", raw=None)

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


def _first_choice(chunk: Any) -> Any | None:
    choices = _get_attr(chunk, "choices", [])
    if not choices:
        return None
    return choices[0]


def _get_attr(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _iter_tool_call_deltas(tool_calls: Any) -> list[Any]:
    if not tool_calls:
        return []
    return list(tool_calls)


def _merge_tool_call_delta(tool_call: dict[str, Any], delta: Any) -> None:
    call_id = _get_attr(delta, "id")
    if call_id:
        tool_call["id"] = call_id

    call_type = _get_attr(delta, "type")
    if call_type:
        tool_call["type"] = call_type

    function = _get_attr(delta, "function")
    if function is None:
        return

    name = _get_attr(function, "name")
    if name:
        tool_call["function"]["name"] += str(name)

    arguments = _get_attr(function, "arguments")
    if arguments:
        tool_call["function"]["arguments"] += str(arguments)
