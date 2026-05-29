import asyncio

from verse.tts.elevenlabs import ElevenLabsAdapter
from verse.tts.macos_say import MacOSSayAdapter


def test_macos_say_adapter_streams_generated_file(monkeypatch):
    def fake_run(command, check, capture_output):
        assert check is True
        assert capture_output is True
        output_path = command[command.index("-o") + 1]
        with open(output_path, "wb") as output:
            output.write(b"aiff audio")

    monkeypatch.setattr("verse.tts.macos_say.subprocess.run", fake_run)
    adapter = MacOSSayAdapter(words_per_minute=150)

    async def collect():
        return [chunk async for chunk in adapter.stream("hello")]

    assert asyncio.run(collect()) == [b"aiff audio"]


def test_macos_say_adapter_returns_empty_bytes_for_blank_text():
    adapter = MacOSSayAdapter()

    assert asyncio.run(adapter.synthesize("   ")) == b""


def test_elevenlabs_adapter_is_explicit_stub():
    adapter = ElevenLabsAdapter()

    async def collect():
        return [chunk async for chunk in adapter.stream("hello")]

    try:
        asyncio.run(collect())
    except NotImplementedError as exc:
        assert "later phase" in str(exc)
    else:
        raise AssertionError("Expected ElevenLabsAdapter to be a stub")
