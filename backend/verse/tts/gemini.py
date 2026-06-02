from __future__ import annotations

import asyncio
import base64
import io
import os
import wave
from collections.abc import AsyncGenerator
from typing import Any

from verse.config import TTSConfig
from verse.persistence.keychain import get_api_key
from verse.tts.base import TTSAdapter, RealtimeTTSAdapter


GEMINI_TTS_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
GEMINI_TTS_SAMPLE_RATE = 24000
GEMINI_TTS_CHANNELS = 1
GEMINI_TTS_SAMPLE_WIDTH = 2

_EDGE_VOICE_FALLBACKS = {
    "id-ID-ArdiNeural",
    "id-ID-GadisNeural",
    "en-US-AriaNeural",
    "en-US-GuyNeural",
}


class GeminiTTSAdapter(TTSAdapter, RealtimeTTSAdapter):
    """Gemini API text-to-speech adapter.

    Gemini TTS returns raw 24 kHz 16-bit mono PCM. Verse's playback path already
    accepts WAV bytes, so synthesize() wraps the PCM payload in a WAV container.
    """

    def __init__(
        self,
        config: TTSConfig | None = None,
        *,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.config = config or TTSConfig(provider="gemini")
        self.model = self.config.model or TTSConfig.model
        self.base_url = self.config.base_url or GEMINI_TTS_BASE_URL
        self.voice_name = _gemini_voice_name(self.config.voice_id)
        self.api_key = api_key
        self._client = client

    @property
    def sample_rate(self) -> int:
        return GEMINI_TTS_SAMPLE_RATE

    @property
    def channels(self) -> int:
        return GEMINI_TTS_CHANNELS

    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        audio = await self.synthesize(text)
        if audio:
            yield audio

    async def stream_pcm(self, text: str) -> AsyncGenerator[bytes, None]:
        pcm = await asyncio.to_thread(self._generate_pcm_sync, text)
        if pcm:
            yield pcm

    async def synthesize(self, text: str) -> bytes:
        pcm = await asyncio.to_thread(self._generate_pcm_sync, text)
        if not pcm:
            return b""
        return _pcm_to_wav(pcm)

    def _generate_pcm_sync(self, text: str) -> bytes:
        text = (text or "").strip()
        if not text:
            return b""

        try:
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError(
                "google-genai is required for GeminiTTSAdapter. Install backend dependencies first."
            ) from exc

        response = self.client.models.generate_content(
            model=self.model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=self.voice_name
                        )
                    )
                ),
            ),
        )
        data = _extract_inline_audio_data(response)
        if data is None:
            raise RuntimeError("Gemini TTS response did not include inline audio data.")
        return data

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise RuntimeError(
                    "google-genai is required for GeminiTTSAdapter. Install backend dependencies first."
                ) from exc

            api_key = (
                self.api_key
                or os.getenv("GEMINI_API_KEY")
                or get_api_key("gemini")
                or get_api_key("gemini_api_key")
            )
            if not api_key:
                raise RuntimeError("Gemini API key not found in env or Keychain")

            self._client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(base_url=self.base_url),
            )
        return self._client


def _gemini_voice_name(voice_id: str) -> str:
    value = (voice_id or "").strip()
    if not value or value in _EDGE_VOICE_FALLBACKS or value.lower() in {"id", "auto"}:
        return "Kore"
    return value


def _extract_inline_audio_data(response: Any) -> bytes | None:
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline_data = getattr(part, "inline_data", None) or getattr(part, "inlineData", None)
            if inline_data is None:
                continue
            data = getattr(inline_data, "data", None)
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                return base64.b64decode(data)
    return None


def _pcm_to_wav(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(GEMINI_TTS_CHANNELS)
        wf.setsampwidth(GEMINI_TTS_SAMPLE_WIDTH)
        wf.setframerate(GEMINI_TTS_SAMPLE_RATE)
        wf.writeframes(pcm)
    return buffer.getvalue()
