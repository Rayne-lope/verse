import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from verse.config import TTSConfig
from verse.tts.google import GoogleTTSAdapter


def test_google_tts_adapter_init_defaults():
    adapter = GoogleTTSAdapter()
    assert adapter.lang == "id"


def test_google_tts_adapter_init_config():
    config = TTSConfig(voice_id="en", speed=1.0)
    adapter = GoogleTTSAdapter(config)
    assert adapter.lang == "en"

    # Edge TTS voices should fallback to id
    config_edge = TTSConfig(voice_id="id-ID-ArdiNeural", speed=1.0)
    adapter_edge = GoogleTTSAdapter(config_edge)
    assert adapter_edge.lang == "id"


@pytest.mark.anyio
async def test_google_tts_adapter_synthesize(monkeypatch):
    adapter = GoogleTTSAdapter()

    # Mock requests.get
    mock_response = MagicMock()
    mock_response.content = b"fake mp3 bytes"
    mock_response.raise_for_status = MagicMock()
    
    mock_get = MagicMock(return_value=mock_response)
    monkeypatch.setattr("requests.get", mock_get)

    # Mock subprocess.run for afconvert
    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    # Mock read_bytes and write_bytes
    fake_wav_bytes = b"fake wav bytes"

    with patch.object(Path, "read_bytes", return_value=fake_wav_bytes), \
         patch.object(Path, "write_bytes") as mock_write:
        result = await adapter.synthesize("hello")
        assert result == fake_wav_bytes
        mock_write.assert_called_once_with(b"fake mp3 bytes")

    # Verify requests.get was called
    mock_get.assert_called_once()
    mock_run.assert_called_once()
