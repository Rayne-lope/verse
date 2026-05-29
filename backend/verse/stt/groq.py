from __future__ import annotations

import asyncio
from io import BytesIO
import os
from typing import Any

from verse.persistence.keychain import get_api_key
from verse.stt.base import STTAdapter


class GroqWhisperAdapter(STTAdapter):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "whisper-large-v3-turbo",
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self._client = client

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
