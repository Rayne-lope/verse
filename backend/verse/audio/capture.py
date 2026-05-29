from __future__ import annotations

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
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype
        self._stream: sd.InputStream | None = None
        self._chunks: list[np.ndarray[Any, Any]] = []
        self._recording = False

    @property
    def is_recording(self) -> bool:
        return self._recording

    def start_recording(self) -> None:
        if self._recording:
            raise RuntimeError("Audio recording is already running")

        self._chunks = []
        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            callback=self._on_audio,
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
        return samples_to_wav_bytes(samples, self.sample_rate)

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
        self._chunks.append(indata.copy())


def samples_to_wav_bytes(samples: np.ndarray[Any, Any], sample_rate: int) -> bytes:
    buffer = BytesIO()
    sf.write(buffer, samples, sample_rate, format="WAV")
    return buffer.getvalue()


_default_recorder = AudioRecorder()


def start_recording() -> None:
    _default_recorder.start_recording()


def stop_recording() -> bytes:
    return _default_recorder.stop_recording()


def record_for_seconds(seconds: float) -> bytes:
    return _default_recorder.record_for_seconds(seconds)
