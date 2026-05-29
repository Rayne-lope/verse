import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path

from verse.config import TTSConfig
from verse.tts.edge_tts import EdgeTTSAdapter


def test_edge_tts_adapter_init_defaults():
    adapter = EdgeTTSAdapter()
    assert adapter.voice == "id-ID-GadisNeural"
    assert adapter.rate == "+0%"


def test_edge_tts_adapter_init_config():
    # Test rate mapping for speed > 1.0
    config = TTSConfig(voice_id="en-US-AriaNeural", speed=1.2)
    adapter = EdgeTTSAdapter(config)
    assert adapter.voice == "en-US-AriaNeural"
    assert adapter.rate == "+20%"

    # Test rate mapping for speed < 1.0
    config_slow = TTSConfig(voice_id="en-US-GuyNeural", speed=0.85)
    adapter_slow = EdgeTTSAdapter(config_slow)
    assert adapter_slow.rate == "-15%"


@pytest.mark.anyio
async def test_edge_tts_adapter_synthesize(monkeypatch):
    adapter = EdgeTTSAdapter(voice="en-US-AriaNeural")

    # Mock edge_tts.Communicate
    mock_communicate_instance = MagicMock()
    mock_communicate_instance.save = AsyncMock()

    mock_communicate_class = MagicMock(return_value=mock_communicate_instance)
    monkeypatch.setattr("edge_tts.Communicate", mock_communicate_class)

    # Mock subprocess.run for afconvert
    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    # Mock read_bytes to return fake WAV bytes
    fake_wav_bytes = b"fake wav bytes"

    with patch.object(Path, "read_bytes", return_value=fake_wav_bytes):
        result = await adapter.synthesize("hello")
        assert result == fake_wav_bytes

    # Verify edge_tts was called with correct parameters
    mock_communicate_class.assert_called_once_with("hello", "en-US-AriaNeural", rate="+0%")
    mock_communicate_instance.save.assert_called_once()
    mock_run.assert_called_once()
