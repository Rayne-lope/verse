from __future__ import annotations

import asyncio
from collections.abc import Callable
from io import BytesIO
from time import sleep
from typing import Any

import numpy as np
import sounddevice as sd
import soundfile as sf


class AudioRecorder:
    def __init__(
        self,
        *,
        sample_rate: int = 16_000,
        channels: int = 1,
        dtype: str = "float32",
        pre_vad_audio_hook: Callable[[np.ndarray[Any, Any]], np.ndarray[Any, Any]] | None = None,
        post_recording_audio_hook: Callable[[np.ndarray[Any, Any]], np.ndarray[Any, Any]] | None = None,
        clean_for_stt: Callable[[bytes], bytes] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self.pre_vad_audio_hook = pre_vad_audio_hook
        self.post_recording_audio_hook = post_recording_audio_hook
        self.clean_for_stt = clean_for_stt
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray[Any, Any]] = []
        self._recording = False
        self._queue: asyncio.Queue[np.ndarray[Any, Any]] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_recording(self) -> bool:
        return self._recording

    async def read_chunk(self) -> np.ndarray[Any, Any]:
        """Read a chunk from the bounded asyncio queue asynchronously."""
        if self._queue is None:
            raise RuntimeError("Recording is not running or no event loop configured")
        return await self._queue.get()

    def start_recording(self, on_audio_level: Callable[[float], None] | None = None) -> None:
        if self._recording:
            raise RuntimeError("Audio recording is already running")

        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

        if self._loop is not None:
            self._queue = asyncio.Queue(maxsize=128)
        else:
            self._queue = None

        self._chunks = []
        self._on_audio_level = on_audio_level
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            callback=self._on_audio,
            blocksize=512,
        )
        self._stream.start()
        self._recording = True

    def stop_recording(self) -> bytes:
        if not self._recording or self._stream is None:
            raise RuntimeError("Audio recording is not running")

        stream = self._stream
        self._stream = None
        self._recording = False
        stream.stop()
        stream.close()

        if self._chunks:
            samples = np.concatenate(self._chunks, axis=0)
        else:
            samples = np.empty((0, self.channels), dtype=self.dtype)

        if self.post_recording_audio_hook is not None:
            samples = self.post_recording_audio_hook(samples)

        wav_bytes = samples_to_wav_bytes(samples, self.sample_rate)
        if self.clean_for_stt is not None:
            wav_bytes = self.clean_for_stt(wav_bytes)
        return wav_bytes

    def record_for_seconds(self, seconds: float) -> bytes:
        self.start_recording()
        sleep(seconds)
        return self.stop_recording()

    def _on_audio(
        self,
        indata: np.ndarray[Any, Any],
        _frames: int,
        _time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            # sounddevice status flags are diagnostics; keep recording and retain data.
            pass
        chunk = indata.copy()
        if self.pre_vad_audio_hook is not None:
            chunk = self.pre_vad_audio_hook(chunk)
        self._chunks.append(chunk)

        if self._loop is not None and self._queue is not None:
            def safe_put(frame: np.ndarray[Any, Any]) -> None:
                try:
                    self._queue.put_nowait(frame)
                except asyncio.QueueFull:
                    try:
                        self._queue.get_nowait()
                        self._queue.put_nowait(frame)
                    except Exception:
                        pass
            self._loop.call_soon_threadsafe(safe_put, chunk)

        if hasattr(self, "_on_audio_level") and self._on_audio_level:
            # Calculate RMS amplitude
            rms = np.sqrt(np.mean(np.square(indata)))
            # Scale and clip between 0.0 and 1.0
            level = min(1.0, max(0.0, float(rms) * 5.0))
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._on_audio_level, level)
            else:
                self._on_audio_level(level)


def samples_to_wav_bytes(samples: np.ndarray[Any, Any], sample_rate: int) -> bytes:
    buffer = BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV")
    return buffer.getvalue()


_default_recorder = AudioRecorder()


def start_recording(on_audio_level: Callable[[float], None] | None = None) -> None:
    _default_recorder.start_recording(on_audio_level=on_audio_level)


def stop_recording() -> bytes:
    return _default_recorder.stop_recording()


def record_for_seconds(seconds: float) -> bytes:
    return _default_recorder.record_for_seconds(seconds)
