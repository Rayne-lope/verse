from __future__ import annotations

import asyncio
import subprocess
import tempfile
from collections.abc import AsyncGenerator
from pathlib import Path

from verse.tts.base import TTSAdapter

DEFAULT_VOICE = "id-ID-GadisNeural"


class EdgeTTSAdapter(TTSAdapter):
    def __init__(
        self,
        voice: str = DEFAULT_VOICE,
        rate: str = "+0%",
    ) -> None:
        self.voice = voice
        self.rate = rate

    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is required for EdgeTTSAdapter. Run: poetry add edge-tts"
            ) from exc

        communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            return b""

        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is required for EdgeTTSAdapter. Run: poetry add edge-tts"
            ) from exc

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmppath = Path(tmp.name)

        try:
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            await communicate.save(str(tmppath))
            # afplay is macOS built-in and handles MP3 natively.
            await asyncio.to_thread(
                subprocess.run, ["afplay", str(tmppath)], check=True
            )
        finally:
            tmppath.unlink(missing_ok=True)

        # Playback already done inside synthesize; return empty so orchestrator
        # skips its own play() call.
        return b""
