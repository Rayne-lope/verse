import asyncio
import time
import numpy as np
import pytest
import sounddevice as sd
from unittest.mock import AsyncMock, patch

from verse.tts.segmenter import TextSegmenter
from verse.tts.base import RealtimeTTSAdapter
from verse.tts.edge_tts import EdgeTTSAdapter
from verse.audio.streaming_player import StreamingPlayer


def test_text_segmenter_punctuation():
    # Min length of 10
    segmenter = TextSegmenter(min_length=10)
    
    # 1. Major punctuation splits immediately
    res1 = segmenter.push("Halo.")
    assert res1 == ["Halo."]
    
    # 2. Minor punctuation under min_length does not split
    res2 = segmenter.push(" Ya,")
    assert res2 == []
    
    # 3. Minor punctuation over min_length splits
    res3 = segmenter.push(" ini adalah segmen yang panjang,")
    assert res3 == ["Ya, ini adalah segmen yang panjang,"]
    
    # 4. Flush outputs the remaining text
    res4 = segmenter.push(" sisa kata")
    assert res4 == []
    res5 = segmenter.flush()
    assert res5 == ["sisa kata"]


def test_text_segmenter_max_length():
    # Max length of 30
    segmenter = TextSegmenter(max_length=30)
    
    # Push text longer than max_length.
    # It should split at the last space before index 30.
    # "This is a very long sentence that goes on" (length 41)
    # Characters up to 30: "This is a very long sentence t"
    # Last space before index 30 is at index 28 (after "sentence").
    # So it should split at index 29: "This is a very long sentence"
    res = segmenter.push("This is a very long sentence that goes on")
    assert len(res) >= 1
    assert res[0] == "This is a very long sentence"
    assert segmenter._buffer == "that goes on"


def test_text_segmenter_should_flush():
    segmenter = TextSegmenter()
    assert not segmenter.should_flush(0.1)
    
    segmenter.push("Halo")
    assert not segmenter.should_flush(10.0)
    
    time.sleep(0.1)
    assert segmenter.should_flush(0.01)


@pytest.mark.anyio
async def test_streaming_player_buffering(monkeypatch):
    # Mock sounddevice OutputStream to avoid C thread creation and hardware access
    class FakeOutputStream:
        def __init__(self, **kwargs):
            self.active = True
        def start(self):
            pass
        def stop(self):
            self.active = False
        def close(self):
            self.active = False

    monkeypatch.setattr("verse.audio.streaming_player.sd.OutputStream", FakeOutputStream)

    levels = []
    player = StreamingPlayer(on_audio_level=levels.append)
    
    # 1. Enqueue chunk
    chunk_data = np.ones(240, dtype=np.int16) * 123
    await player.enqueue(chunk_data.tobytes())
    
    assert len(player._chunks) == 1
    assert player._playing is True
    
    # 2. Callback drains the chunk
    outdata = np.zeros((480, 1), dtype=np.int16)
    player._callback(outdata, 480, None, None)
    
    # The first 240 should be filled with 123, rest with 0 (silence)
    assert np.all(outdata[:240, 0] == 123)
    assert np.all(outdata[240:, 0] == 0)
    assert len(levels) == 1
    assert levels[0] > 0.0
    
    # 3. Wait for playback to stop when playing=False and buffer is empty
    player.signal_end()
    assert player._playing is False
    
    with pytest.raises(sd.CallbackStop):
        player._callback(outdata, 480, None, None)
    
    player.close()


@pytest.mark.anyio
async def test_edge_tts_adapter_stream_pcm(monkeypatch):
    adapter = EdgeTTSAdapter()
    assert isinstance(adapter, RealtimeTTSAdapter)
    
    # Mock communicating stream
    async def mock_stream(text):
        yield b"mp3_chunk_1"
        yield b"mp3_chunk_2"
        
    monkeypatch.setattr(adapter, "stream", mock_stream)
    
    # Mock asyncio.create_subprocess_exec to mock ffmpeg
    mock_proc = AsyncMock()
    mock_proc.stdin = AsyncMock()
    mock_proc.stdout = AsyncMock()
    mock_proc.stdout.read = AsyncMock(side_effect=[b"pcm_chunk_1", b"pcm_chunk_2", b""])
    mock_proc.returncode = 0
    
    mock_exec = AsyncMock(return_value=mock_proc)
    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_exec)
    
    chunks = []
    async for chunk in adapter.stream_pcm("Halo dunia"):
        chunks.append(chunk)
        
    assert chunks == [b"pcm_chunk_1", b"pcm_chunk_2"]
    
    # Verify create_subprocess_exec arguments
    mock_exec.assert_called_once_with(
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", "pipe:0",
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", "24000",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    
    # Verify we closed stdin
    mock_proc.stdin.close.assert_called_once()
