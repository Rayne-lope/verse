from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np

from verse.config import AlwaysOnConfig
from verse.wake_word import PorcupineWakeWordListener


class FakePorcupine:
    sample_rate = 16_000
    frame_length = 4

    def __init__(self) -> None:
        self.deleted = False

    def process(self, _pcm: list[int]) -> int:
        return 0

    def delete(self) -> None:
        self.deleted = True


def test_wake_word_listener_detects_keyword(monkeypatch):
    created: dict[str, object] = {}

    def create(**kwargs):
        created.update(kwargs)
        return FakePorcupine()

    class FakeInputStream:
        def __init__(self, *, callback, **kwargs):
            self.callback = callback
            created["stream_kwargs"] = kwargs

        def start(self):
            frame = np.array([[1], [2], [3], [4]], dtype=np.int16)
            self.callback(frame, 4, None, None)

        def stop(self):
            created["stopped"] = True

        def close(self):
            created["closed"] = True

    monkeypatch.setitem(sys.modules, "pvporcupine", SimpleNamespace(create=create))
    monkeypatch.setattr("verse.wake_word.sd.InputStream", FakeInputStream)
    monkeypatch.setenv("PICOVOICE_ACCESS_KEY", "test-key")

    wakes: list[int] = []
    statuses: list[tuple[bool, str]] = []
    listener = PorcupineWakeWordListener(
        AlwaysOnConfig(enabled=True, keyword="picovoice", keyword_path=""),
        on_wake=wakes.append,
        on_status=lambda active, mode: statuses.append((active, mode)),
    )

    assert listener.start() is True

    assert created["access_key"] == "test-key"
    assert created["keywords"] == ["picovoice"]
    assert created["sensitivities"] == [0.65]
    assert wakes == [0]
    assert statuses == [(False, "off")]


def test_wake_word_listener_reports_missing_access_key(monkeypatch):
    monkeypatch.delenv("PICOVOICE_ACCESS_KEY", raising=False)
    monkeypatch.setattr("verse.wake_word.get_api_key", lambda _name: None)

    errors: list[str] = []
    listener = PorcupineWakeWordListener(
        AlwaysOnConfig(enabled=True, keyword="picovoice", keyword_path=""),
        on_wake=lambda _idx: None,
        on_error=errors.append,
    )

    assert listener.start() is False
    assert "Picovoice AccessKey" in errors[0]
