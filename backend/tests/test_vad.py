from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from verse.audio.vad import SileroVADManager


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
        manager._h = np.ones((2, 1, 64), dtype=np.float32)
        manager._c = np.ones((2, 1, 64), dtype=np.float32)
        
        manager.reset()
        
        assert np.all(manager._h == 0.0)
        assert np.all(manager._c == 0.0)


def test_silero_vad_manager_predict_invalid_inputs():
    with patch("verse.audio.vad.ort.InferenceSession"):
        manager = SileroVADManager()
        # Make session appear loaded
        manager.session = MagicMock()
        
        # Wrong length
        assert manager.predict(np.zeros(256)) == 0.0


def test_silero_vad_manager_predict_success():
    with patch("verse.audio.vad.ort.InferenceSession") as mock_sess_class:
        mock_session_inst = MagicMock()
        mock_session_inst.run.return_value = (
            np.array([[0.85]], dtype=np.float32),  # probability output
            np.ones((2, 1, 64), dtype=np.float32) * 0.1,  # updated h
            np.ones((2, 1, 64), dtype=np.float32) * 0.2,  # updated c
        )
        mock_sess_class.return_value = mock_session_inst

        # Patch ensure model exists to skip downloading
        with patch.object(SileroVADManager, "_ensure_model_exists"):
            manager = SileroVADManager()
            assert manager.is_available is True
            
            frame = np.zeros(512, dtype=np.float32)
            prob = manager.predict(frame)
            
            assert prob == pytest.approx(0.85)
            assert np.allclose(manager._h, 0.1)
            assert np.allclose(manager._c, 0.2)
