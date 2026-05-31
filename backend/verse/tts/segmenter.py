from __future__ import annotations

import time


class TextSegmenter:
    """
    Buffers streaming text chunks (deltas) and yields clean segments
    suitable for real-time Text-to-Speech synthesis.
    
    Rules:
    - Split immediately on major punctuation: . ! ? \n \r
    - Split on minor punctuation (, ; :) if the accumulated text length is >= min_length.
    - If the buffer exceeds max_length, force a split at the last space or punctuation.
    - Tracks last push time to allow the caller to detect idle timeouts and flush.
    """

    def __init__(
        self,
        min_length: int = 20,
        max_length: int = 150,
        major_punctuation: str = ".!?\n\r",
        minor_punctuation: str = ",;:，；：",
    ) -> None:
        self.min_length = min_length
        self.max_length = max_length
        self.major_punctuation = major_punctuation
        self.minor_punctuation = minor_punctuation
        
        self._buffer = ""
        self._last_push_time = time.time()

    def push(self, delta: str) -> list[str]:
        """
        Append new text delta and return any completed segments.
        """
        self._buffer += delta
        self._last_push_time = time.time()
        
        segments: list[str] = []
        
        while self._buffer:
            split_idx = -1
            
            # 1. Force split if buffer exceeds max_length
            if len(self._buffer) >= self.max_length:
                # Find the last space or punctuation before max_length
                for i in range(self.max_length - 1, -1, -1):
                    char = self._buffer[i]
                    if char.isspace() or char in self.major_punctuation or char in self.minor_punctuation:
                        split_idx = i + 1
                        break
                if split_idx == -1:
                    # Force split at max_length if no whitespace or punctuation found
                    split_idx = self.max_length

            # 2. Check for major or minor punctuation
            if split_idx == -1:
                for i, char in enumerate(self._buffer):
                    if char in self.major_punctuation:
                        split_idx = i + 1
                        break
                    elif char in self.minor_punctuation:
                        if i >= self.min_length:
                            split_idx = i + 1
                            break
            
            # 3. If a boundary was found, extract the segment
            if split_idx != -1:
                segment = self._buffer[:split_idx]
                self._buffer = self._buffer[split_idx:]
                cleaned = segment.strip()
                if cleaned:
                    segments.append(cleaned)
            else:
                break
                
        return segments

    def flush(self) -> list[str]:
        """
        Force-yield any remaining text in the buffer.
        """
        segments: list[str] = []
        if self._buffer:
            cleaned = self._buffer.strip()
            if cleaned:
                segments.append(cleaned)
            self._buffer = ""
        return segments

    def should_flush(self, idle_timeout: float = 1.0) -> bool:
        """
        Returns True if there is buffered text and the elapsed time since
        the last push exceeds the idle_timeout.
        """
        if not self._buffer.strip():
            return False
        return (time.time() - self._last_push_time) >= idle_timeout
