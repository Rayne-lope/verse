from __future__ import annotations

from collections.abc import AsyncGenerator

from verse.tts.base import TTSAdapter


class ElevenLabsAdapter(TTSAdapter):
    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        _ = text
        raise NotImplementedError(
            "ElevenLabs streaming is planned for a later phase; use MacOSSayAdapter for now."
        )
        yield b""
