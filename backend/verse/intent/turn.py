from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

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

    def is_cancelled(self) -> bool:
        """Returns True if this turn has been cancelled."""
        return self.cancelled or self.cancel_event.is_set()

    def cancel(self) -> None:
        """Cancels this turn and discards any active audio playback."""
        self.cancelled = True
        self.cancel_event.set()
        if self.playback:
            try:
                # Discard buffered chunks immediately
                asyncio.create_task(self.playback.clear())
            except Exception:
                pass
