from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator


class TTSAdapter(ABC):
    @abstractmethod
    async def stream(self, text: str) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError

    async def synthesize(self, text: str) -> bytes:
        chunks = []
        async for chunk in self.stream(text):
            chunks.append(chunk)
        return b"".join(chunks)


class RealtimeTTSAdapter(ABC):
    @property
    def sample_rate(self) -> int:
        return 24000

    @property
    def channels(self) -> int:
        return 1

    @abstractmethod
    async def stream_pcm(self, text: str) -> AsyncGenerator[bytes, None]:
        raise NotImplementedError
