from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncIterator, Literal

if TYPE_CHECKING:
    pass


class STTAdapter(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, language: str | None = None) -> str:
        raise NotImplementedError


@dataclass
class STTEvent:
    """Event emitted by a StreamingSTTAdapter.

    Attributes:
        type: One of "partial", "final", "speech_started", "speech_ended", "error".
        text: The transcript text (empty for speech_started/speech_ended/error).
        stability: Confidence 0.0–1.0 that the partial is stable (only set for "partial").
        timestamp_ms: Audio timestamp in milliseconds.
    """

    type: Literal["partial", "final", "speech_started", "speech_ended", "error"]
    text: str = ""
    stability: float | None = None
    timestamp_ms: int | None = None


class StreamingSTTAdapter(ABC):
    """Streaming STT adapter — receives PCM chunks incrementally and emits
    partial and final transcript events in real time."""

    @abstractmethod
    async def start_turn(self, language: str | None) -> None:
        """Begin a new streaming turn. Called once before any audio is sent."""
        raise NotImplementedError

    @abstractmethod
    async def send_audio(self, pcm_chunk: bytes) -> None:
        """Feed one PCM audio chunk (16-bit mono 16kHz) into the stream."""
        raise NotImplementedError

    @abstractmethod
    async def end_turn(self) -> None:
        """Signal end of audio input. No more chunks will be sent after this."""
        raise NotImplementedError

    @abstractmethod
    def events(self) -> AsyncIterator[STTEvent]:
        """Yield STT events as they arrive. Must be consumed after end_turn()
        to ensure all events are retrieved."""
        raise NotImplementedError
