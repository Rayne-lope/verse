from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from verse.audio.streaming_player import StreamingPlayer


@dataclass
class TurnContext:
    """
    Tracks state and metadata for a single user turn, enabling prompt
    interruption/cancellation across LLM, TTS, and audio playback tasks.
    """
    id: str
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False
    playback: StreamingPlayer | None = None
    playback_stop_event: threading.Event | None = None
    llm_task: asyncio.Task | None = None
    tts_task: asyncio.Task | None = None
    tool_tasks: set[asyncio.Task] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_cancelled(self) -> bool:
        """Returns True if this turn has been cancelled."""
        return self.cancelled or self.cancel_event.is_set()

    def cancel(self, reason: str | None = None) -> None:
        """Cancels this turn and discards any active audio playback."""
        self.cancelled = True
        self.cancel_event.set()
        if reason:
            self.metadata["cancel_reason"] = reason
        if self.playback_stop_event is not None:
            self.playback_stop_event.set()
        for task in [self.llm_task, self.tts_task, *self.tool_tasks]:
            if task is not None and not task.done():
                task.cancel()
        if self.playback:
            try:
                # Discard buffered chunks immediately
                asyncio.create_task(self.playback.clear())
            except Exception:
                pass
