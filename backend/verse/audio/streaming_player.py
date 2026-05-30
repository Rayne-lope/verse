from __future__ import annotations

import threading
from typing import Callable

import numpy as np
import sounddevice as sd


class StreamingPlayer:
    """
    Plays 24 kHz int16 mono PCM chunks in real time as they arrive.
    Audio is appended to an in-memory numpy buffer; a sounddevice callback
    drains it continuously. Supports immediate barge-in via clear().
    """

    SAMPLE_RATE = 24_000
    CHANNELS = 1
    DTYPE = "int16"
    BLOCKSIZE = 480  # 20 ms @ 24 kHz

    def __init__(
        self,
        on_audio_level: Callable[[float], None] | None = None,
    ) -> None:
        self._on_audio_level = on_audio_level
        self._lock = threading.Lock()
        self._buffer = np.empty(0, dtype=np.int16)
        self._playing = False          # True while more audio is expected this turn
        self._stream: sd.OutputStream | None = None
        self._finished = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, pcm_bytes: bytes) -> None:
        """Append a PCM chunk. Starts the OutputStream if it isn't running."""
        chunk = np.frombuffer(pcm_bytes, dtype=np.int16)
        with self._lock:
            self._buffer = np.concatenate([self._buffer, chunk])
            self._playing = True
        if self._stream is None or not self._stream.active:
            self._start_stream()

    def signal_end(self) -> None:
        """Mark end of turn — the stream will drain remaining audio then stop."""
        with self._lock:
            self._playing = False

    async def wait_drained(self) -> None:
        """Wait until the current buffer has fully played out."""
        import asyncio
        if self._stream is None or not self._stream.active:
            return
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._finished.wait, 10.0)

    async def clear(self) -> None:
        """Immediately discard buffered audio and stop playback (barge-in)."""
        import asyncio
        with self._lock:
            self._buffer = np.empty(0, dtype=np.int16)
            self._playing = False
        # Allow callback two ticks to see the empty buffer and raise CallbackStop.
        await asyncio.sleep(0.05)
        self._close_stream()

    def close(self) -> None:
        """Release all resources."""
        with self._lock:
            self._playing = False
            self._buffer = np.empty(0, dtype=np.int16)
        self._close_stream()

    @property
    def is_playing(self) -> bool:
        return self._stream is not None and self._stream.active

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _start_stream(self) -> None:
        self._close_stream()
        self._finished.clear()
        self._stream = sd.OutputStream(
            samplerate=self.SAMPLE_RATE,
            channels=self.CHANNELS,
            dtype=self.DTYPE,
            blocksize=self.BLOCKSIZE,
            callback=self._callback,
            finished_callback=self._finished.set,
        )
        self._stream.start()

    def _close_stream(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        with self._lock:
            available = len(self._buffer)
            if available == 0:
                outdata.fill(0)
                if not self._playing:
                    raise sd.CallbackStop
                return  # silence; more audio expected

            n = min(frames, available)
            outdata[:n, 0] = self._buffer[:n]
            if n < frames:
                outdata[n:].fill(0)
            chunk = self._buffer[:n].copy()
            self._buffer = self._buffer[n:]

        if self._on_audio_level is not None:
            rms = float(np.sqrt(np.mean((chunk.astype(np.float32) / 32767.0) ** 2)))
            level = min(1.0, rms * 5.0)
            try:
                self._on_audio_level(level)
            except Exception:
                pass
