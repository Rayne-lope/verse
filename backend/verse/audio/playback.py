from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO
import threading
from typing import Any, Callable

import numpy as np
import sounddevice as sd
import soundfile as sf


def play_audio(
    audio_bytes: bytes,
    *,
    blocking: bool = True,
    on_audio_level: Callable[[float], None] | None = None,
) -> None:
    samples, sample_rate = wav_bytes_to_samples(audio_bytes)
    if samples.size == 0:
        return

    if on_audio_level is None:
        sd.play(samples, sample_rate)
        if blocking:
            sd.wait()
        return

    # If on_audio_level is provided, play via OutputStream to measure amplitude
    event = threading.Event()
    cursor = 0
    num_samples = len(samples)
    channels = samples.shape[1]

    def callback(outdata: np.ndarray, frames: int, time: Any, status: sd.CallbackFlags) -> None:
        nonlocal cursor
        remainder = num_samples - cursor
        if remainder <= 0:
            outdata.fill(0)
            raise sd.CallbackStop

        chunk_size = min(frames, remainder)
        outdata[:chunk_size] = samples[cursor : cursor + chunk_size]
        if chunk_size < frames:
            outdata[chunk_size:].fill(0)

        # Calculate RMS amplitude
        rms = np.sqrt(np.mean(np.square(outdata[:chunk_size])))
        level = min(1.0, max(0.0, float(rms) * 5.0))
        on_audio_level(level)

        cursor += chunk_size
        if cursor >= num_samples:
            raise sd.CallbackStop

    stream = sd.OutputStream(
        samplerate=sample_rate,
        channels=channels,
        dtype=samples.dtype,
        callback=callback,
        blocksize=512,
        finished_callback=event.set,
    )

    def run_stream() -> None:
        with stream:
            event.wait()

    if blocking:
        run_stream()
    else:
        t = threading.Thread(target=run_stream, daemon=True)
        t.start()


def play_stream(
    chunks: Iterable[bytes],
    *,
    blocking: bool = True,
    on_audio_level: Callable[[float], None] | None = None,
) -> None:
    for chunk in chunks:
        play_audio(chunk, blocking=blocking, on_audio_level=on_audio_level)


def wav_bytes_to_samples(audio_bytes: bytes) -> tuple[np.ndarray[Any, Any], int]:
    samples, sample_rate = sf.read(BytesIO(audio_bytes), dtype="float32", always_2d=True)
    return samples, int(sample_rate)
