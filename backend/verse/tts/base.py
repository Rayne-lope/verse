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
