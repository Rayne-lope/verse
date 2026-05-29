from __future__ import annotations

from abc import ABC, abstractmethod


class STTAdapter(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, language: str | None = None) -> str:
        raise NotImplementedError
