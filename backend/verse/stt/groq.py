from __future__ import annotations

import asyncio
from io import BytesIO
import os
from typing import Any, AsyncIterator

from verse.persistence.keychain import get_api_key
from verse.stt.base import STTAdapter, STTEvent


class GroqWhisperAdapter(STTAdapter):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "whisper-large-v3-turbo",
        client: Any | None = None,
        partial_interval_ms: int = 1000,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client
        self.partial_interval_ms = partial_interval_ms

    async def transcribe(self, audio: bytes, language: str | None = None) -> str:
        return await asyncio.to_thread(self._transcribe_sync, audio, language)

    def _transcribe_sync(self, audio: bytes, language: str | None = None) -> str:
        if not audio:
            raise ValueError("Audio bytes cannot be empty")

        kwargs: dict[str, Any] = {
            "file": ("audio.wav", BytesIO(audio), "audio/wav"),
            "model": self.model,
        }
        if language and language != "auto":
            kwargs["language"] = language

        response = self.client.audio.transcriptions.create(**kwargs)
        text = getattr(response, "text", None)
        if text is None and isinstance(response, dict):
            text = response.get("text")
        if text is None:
            raise RuntimeError("Groq transcription response did not include text")
        return str(text)

    @property
    def client(self) -> Any:
        if self._client is None:
            api_key = self.api_key or os.getenv("GROQ_API_KEY") or get_api_key("groq")
            if not api_key:
                raise RuntimeError("Groq API key not found in env or Keychain")
            try:
                from groq import Groq
            except ImportError as exc:
                raise RuntimeError(
                    "groq is required for GroqWhisperAdapter. Install backend dependencies first."
                ) from exc
            self._client = Groq(api_key=api_key)
        return self._client

    async def stream_transcribe(
        self,
        audio_chunks: AsyncIterator[bytes],
        language: str | None = None,
    ) -> AsyncIterator[STTEvent]:
        """Chunked streaming STT — accumulates audio and yields partial transcripts
        every partial_interval_ms, then a final transcript on end_turn.

        Since Groq Whisper does not support true WebSocket streaming, this
        implements a chunked approach: every N ms we send accumulated audio to
        Groq and yield the partial response.
        """
        buffer = bytearray()
        partial_interval_s = self.partial_interval_ms / 1000.0
        last_send_time = 0.0
        turn_started = False

        async def send_and_yield() -> AsyncIterator[STTEvent]:
            nonlocal last_send_time
            if len(buffer) < 8000:  # ~0.5s of audio at 16kHz
                return
            audio_bytes = bytes(buffer)
            result = await asyncio.to_thread(
                self._transcribe_sync, audio_bytes, language
            )
            if result.strip():
                yield STTEvent(type="partial", text=result.strip(), stability=0.6)
            last_send_time = asyncio.get_running_loop().time()

        try:
            async for chunk in audio_chunks:
                if not turn_started:
                    turn_started = True
                buffer.extend(chunk)

                # Check if it's time to send a partial
                now = asyncio.get_running_loop().time()
                if now - last_send_time >= partial_interval_s:
                    async for event in send_and_yield():
                        yield event

        except asyncio.CancelledError:
            return

        # Final flush — send remaining audio
        if buffer:
            audio_bytes = bytes(buffer)
            result = await asyncio.to_thread(
                self._transcribe_sync, audio_bytes, language
            )
            yield STTEvent(type="final", text=result.strip() if result else "")
