import asyncio

import pytest

from verse.stt.groq import GroqWhisperAdapter


class FakeTranscriptions:
    def __init__(self):
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return {"text": "halo verse"}


class FakeAudio:
    def __init__(self):
        self.transcriptions = FakeTranscriptions()


class FakeGroqClient:
    def __init__(self):
        self.audio = FakeAudio()


def test_groq_whisper_adapter_transcribes_with_language():
    client = FakeGroqClient()
    adapter = GroqWhisperAdapter(client=client)

    text = asyncio.run(adapter.transcribe(b"fake wav bytes", language="id"))

    assert text == "halo verse"
    assert client.audio.transcriptions.request["model"] == "whisper-large-v3-turbo"
    assert client.audio.transcriptions.request["language"] == "id"
    assert client.audio.transcriptions.request["file"][0] == "audio.wav"


def test_groq_whisper_adapter_rejects_empty_audio():
    adapter = GroqWhisperAdapter(client=FakeGroqClient())

    with pytest.raises(ValueError):
        asyncio.run(adapter.transcribe(b""))
