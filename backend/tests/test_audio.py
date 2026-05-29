import numpy as np

from verse.audio.capture import AudioRecorder, samples_to_wav_bytes
from verse.audio.playback import play_audio, wav_bytes_to_samples


def test_samples_round_trip_to_wav_bytes():
    samples = np.array([[0.0], [0.25], [-0.25]], dtype="float32")

    audio_bytes = samples_to_wav_bytes(samples, 16_000)
    decoded, sample_rate = wav_bytes_to_samples(audio_bytes)

    assert sample_rate == 16_000
    assert decoded.shape == samples.shape


def test_audio_recorder_uses_sounddevice_stream(monkeypatch):
    streams = []

    class FakeInputStream:
        def __init__(self, *, callback, **_kwargs):
            self.callback = callback
            streams.append(self)

        def start(self):
            self.callback(np.ones((2, 1), dtype="float32"), 2, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("verse.audio.capture.sd.InputStream", FakeInputStream)

    recorder = AudioRecorder(sample_rate=8_000)
    recorder.start_recording()
    audio_bytes = recorder.stop_recording()
    decoded, sample_rate = wav_bytes_to_samples(audio_bytes)

    assert sample_rate == 8_000
    assert decoded.shape == (2, 1)
    assert len(streams) == 1


def test_play_audio_sends_samples_to_sounddevice(monkeypatch):
    played = {}

    monkeypatch.setattr(
        "verse.audio.playback.sd.play",
        lambda samples, sample_rate: played.update(
            {"shape": samples.shape, "sample_rate": sample_rate}
        ),
    )
    monkeypatch.setattr("verse.audio.playback.sd.wait", lambda: played.update(waited=True))

    audio_bytes = samples_to_wav_bytes(np.ones((4, 1), dtype="float32"), 22_050)
    play_audio(audio_bytes)

    assert played == {"shape": (4, 1), "sample_rate": 22_050, "waited": True}


def test_audio_recorder_calls_on_audio_level(monkeypatch):
    levels = []

    class FakeInputStream:
        def __init__(self, *, callback, **_kwargs):
            self.callback = callback

        def start(self):
            self.callback(np.ones((512, 1), dtype="float32"), 512, None, None)

        def stop(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("verse.audio.capture.sd.InputStream", FakeInputStream)

    recorder = AudioRecorder(sample_rate=8_000)
    recorder.start_recording(on_audio_level=levels.append)
    recorder.stop_recording()

    assert len(levels) == 1
    assert levels[0] == 1.0


def test_play_audio_calls_on_audio_level(monkeypatch):
    levels = []

    class FakeOutputStream:
        def __init__(self, *, callback, finished_callback, **_kwargs):
            self.callback = callback
            self.finished_callback = finished_callback

        def __enter__(self):
            outdata = np.zeros((512, 1), dtype="float32")
            try:
                self.callback(outdata, 512, None, None)
            except Exception:
                pass
            self.finished_callback()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr("verse.audio.playback.sd.OutputStream", FakeOutputStream)

    audio_bytes = samples_to_wav_bytes(np.ones((1024, 1), dtype="float32"), 16_000)
    play_audio(audio_bytes, blocking=True, on_audio_level=levels.append)

    assert len(levels) >= 1
