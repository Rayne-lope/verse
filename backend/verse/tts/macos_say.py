from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
import subprocess
import tempfile

from verse.config import TTSConfig
from verse.tts.base import TTSAdapter


class MacOSSayAdapter(TTSAdapter):
    def __init__(
        self,
        config: TTSConfig | None = None,
        *,
        voice: str | None = None,
        words_per_minute: int = 180,
    ) -> None:
        self.config = config or TTSConfig(provider="macos_say")
        self.voice = voice or self.config.voice_id or None
        self.words_per_minute = words_per_minute

    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        audio = await asyncio.to_thread(self._synthesize_sync, text)
        yield audio

    def _synthesize_sync(self, text: str) -> bytes:
        if not text.strip():
            return b""

        with tempfile.NamedTemporaryFile(suffix=".aiff", delete=False) as output:
            output_path = Path(output.name)

        try:
            command = ["say", "-o", str(output_path), "-r", str(self.words_per_minute)]
            if self.voice:
                command.extend(["-v", self.voice])
            command.append(text)
            subprocess.run(command, check=True, capture_output=True)
            return output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)
