from __future__ import annotations

import asyncio
import subprocess
import tempfile
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from verse.config import TTSConfig
from verse.tts.base import TTSAdapter, RealtimeTTSAdapter

logger = logging.getLogger(__name__)
DEFAULT_VOICE = "id-ID-GadisNeural"


class EdgeTTSAdapter(TTSAdapter, RealtimeTTSAdapter):
    def __init__(
        self,
        config: TTSConfig | None = None,
        *,
        voice: str | None = None,
        rate: str | None = None,
    ) -> None:
        if config is not None:
            self.voice = config.voice_id or DEFAULT_VOICE
            speed_diff = int(round((config.speed - 1.0) * 100))
            self.rate = f"{'+' if speed_diff >= 0 else ''}{speed_diff}%"
        else:
            self.voice = voice or DEFAULT_VOICE
            self.rate = rate or "+0%"

    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is required for EdgeTTSAdapter. Run: poetry install"
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
                "edge-tts is required for EdgeTTSAdapter. Run: poetry install"
            ) from exc

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3_tmp:
            mp3_path = Path(mp3_tmp.name)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_tmp:
            wav_path = Path(wav_tmp.name)

        try:
            communicate = edge_tts.Communicate(text, self.voice, rate=self.rate)
            await communicate.save(str(mp3_path))

            # Convert MP3 to WAV using macOS built-in afconvert
            await asyncio.to_thread(
                subprocess.run,
                ["afconvert", "-f", "WAVE", "-d", "LEI16", str(mp3_path), str(wav_path)],
                check=True,
            )

            wav_bytes = wav_path.read_bytes()
            return wav_bytes
        finally:
            mp3_path.unlink(missing_ok=True)
            wav_path.unlink(missing_ok=True)

    async def stream_pcm(self, text: str) -> AsyncGenerator[bytes, None]:
        if not text.strip():
            return

        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError(
                "edge-tts is required for EdgeTTSAdapter. Run: poetry install"
            ) from exc

        proc = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-i", "pipe:0",
            "-f", "s16le",
            "-acodec", "pcm_s16le",
            "-ac", "1",
            "-ar", "24000",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
        )

        async def feed_mp3():
            try:
                async for mp3_chunk in self.stream(text):
                    proc.stdin.write(mp3_chunk)
                    await proc.stdin.drain()
            except Exception as exc:
                logger.error(f"Error feeding MP3 to ffmpeg: {exc}")
            finally:
                try:
                    proc.stdin.close()
                    await proc.stdin.wait_closed()
                except Exception:
                    pass

        feed_task = asyncio.create_task(feed_mp3())

        try:
            while True:
                pcm = await proc.stdout.read(4096)
                if not pcm:
                    break
                yield pcm
        finally:
            await feed_task
            try:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            except Exception:
                pass
