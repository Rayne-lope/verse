from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO
from typing import Any

import numpy as np
import sounddevice as sd
import soundfile as sf


def play_audio(audio_bytes: bytes, *, blocking: bool = True) -> None:
    samples, sample_rate = wav_bytes_to_samples(audio_bytes)
    if samples.size == 0:
        return
    sd.play(samples, sample_rate)
    if blocking:
        sd.wait()


def play_stream(chunks: Iterable[bytes], *, blocking: bool = True) -> None:
    for chunk in chunks:
        play_audio(chunk, blocking=blocking)


def wav_bytes_to_samples(audio_bytes: bytes) -> tuple[np.ndarray[Any, Any], int]:
    samples, sample_rate = sf.read(BytesIO(audio_bytes), dtype="float32", always_2d=True)
    return samples, int(sample_rate)
