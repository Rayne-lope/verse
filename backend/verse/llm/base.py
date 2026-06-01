from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    raw: Any = None


@dataclass(frozen=True)
class LLMStreamEvent:
    type: Literal["text_delta", "tool_call_delta", "tool_call_done", "done", "error"]
    text: str = ""
    tool_call: dict[str, Any] | None = None
    raw: Any = None


class LLMAdapter(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        response = await self.chat(messages, tools=tools)
        if response.tool_calls:
            for tool_call in response.tool_calls:
                yield LLMStreamEvent(
                    type="tool_call_done",
                    tool_call=tool_call,
                    raw=response.raw,
                )
        elif response.text:
            yield LLMStreamEvent(
                type="text_delta",
                text=response.text,
                raw=response.raw,
            )
        yield LLMStreamEvent(type="done", raw=response.raw)
