from __future__ import annotations

import asyncio
import subprocess
import tempfile
import urllib.parse
from collections.abc import AsyncGenerator
from pathlib import Path

import requests

from verse.config import TTSConfig
from verse.tts.base import TTSAdapter


class GoogleTTSAdapter(TTSAdapter):
    def __init__(self, config: TTSConfig | None = None) -> None:
        config = config or TTSConfig()
        # Default voice_id is the language code (e.g. id, en)
        self.lang = config.voice_id or "id"
        if self.lang == "id-ID-ArdiNeural" or self.lang == "id-ID-GadisNeural":
            self.lang = "id"

    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        audio = await self.synthesize(text)
        yield audio

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            return b""

        # Chunk the text to avoid Google's 400 Bad Request for long texts (max 100 chars)
        chunks = []
        current_chunk = []
        current_len = 0
        for word in text.split():
            word_len = len(word) + (1 if current_chunk else 0)
            if current_len + word_len > 100:
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = [word]
                    current_len = len(word)
                else:
                    chunks.append(word[:100])
                    word = word[100:]
                    current_chunk = [word]
                    current_len = len(word)
            else:
                current_chunk.append(word)
                current_len += word_len
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        combined_mp3 = b""
        loop = asyncio.get_running_loop()

        try:
            for chunk in chunks:
                if not chunk.strip():
                    continue
                quoted_text = urllib.parse.quote(chunk)
                url = f"https://translate.google.com/translate_tts?ie=UTF-8&tl={self.lang}&client=tw-ob&q={quoted_text}"
                response = await loop.run_in_executor(
                    None, lambda u=url: requests.get(u, timeout=10)
                )
                response.raise_for_status()
                combined_mp3 += response.content
        except Exception as exc:
            raise RuntimeError(f"Google TTS synthesis failed: {exc}") from exc

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3_tmp:
            mp3_path = Path(mp3_tmp.name)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_tmp:
            wav_path = Path(wav_tmp.name)

        try:
            await asyncio.to_thread(mp3_path.write_bytes, combined_mp3)

            # Convert MP3 to WAV using macOS built-in afconvert
            await asyncio.to_thread(
                subprocess.run,
                ["afconvert", "-f", "WAVE", "-d", "LEI16", str(mp3_path), str(wav_path)],
                check=True,
            )

            wav_bytes = wav_path.read_bytes()
            return wav_bytes
        except Exception as exc:
            raise RuntimeError(f"Google TTS conversion failed: {exc}") from exc
        finally:
            mp3_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)
