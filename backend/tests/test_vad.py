from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from verse.audio.vad import SileroVADManager, VAD_WINDOW_SAMPLES


def test_silero_vad_manager_init_fallback(monkeypatch):
    # If onnxruntime is missing/None
    monkeypatch.setattr("verse.audio.vad.ort", None)
    
    manager = SileroVADManager()
    assert manager.is_available is False
    assert manager.predict(np.zeros(512)) == 0.0


def test_silero_vad_manager_reset():
    # Mock ort to prevent actual ONNX load
    with patch("verse.audio.vad.ort.InferenceSession") as mock_session:
        manager = SileroVADManager()
        # Set dummy recurrent states
        manager._state = np.ones((2, 1, 128), dtype=np.float32)
        
        manager.reset()
        
        assert np.all(manager._state == 0.0)


def test_silero_vad_manager_predict_invalid_inputs():
    with patch("verse.audio.vad.ort.InferenceSession"):
        manager = SileroVADManager()
        # Make session appear loaded
        manager.session = MagicMock()

        # Wrong length (this ONNX build only accepts VAD_WINDOW_SAMPLES)
        assert manager.predict(np.zeros(512)) == 0.0


def test_silero_vad_manager_predict_success():
    with patch("verse.audio.vad.ort.InferenceSession") as mock_sess_class:
        mock_session_inst = MagicMock()
        mock_session_inst.run.return_value = (
            np.array([[0.85]], dtype=np.float32),  # probability output
            np.ones((2, 1, 128), dtype=np.float32) * 0.1,  # updated state
        )
        mock_sess_class.return_value = mock_session_inst

        # Patch ensure model exists to skip downloading
        with patch.object(SileroVADManager, "_ensure_model_exists"):
            manager = SileroVADManager()
            assert manager.is_available is True
            
            frame = np.zeros(VAD_WINDOW_SAMPLES, dtype=np.float32)
            prob = manager.predict(frame)

            assert prob == pytest.approx(0.85)
            assert np.allclose(manager._state, 0.1)
