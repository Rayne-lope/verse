from __future__ import annotations

import logging
import os
from pathlib import Path
import urllib.parse
import numpy as np
import requests

try:
    import onnxruntime as ort
except ImportError:
    ort = None

logger = logging.getLogger(__name__)

SILERO_VAD_URL = "https://github.com/snakers4/silero-vad/raw/master/src/silero_vad/data/silero_vad.onnx"


class SileroVADManager:
    def __init__(self, model_path: str | Path = "~/.verse/models/silero_vad.onnx") -> None:
        self.model_path = Path(model_path).expanduser()
        self.session = None
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)
        
        if ort is None:
            logger.warning("onnxruntime is not installed. Silero VAD will not be available.")
            return

        try:
            self._ensure_model_exists()
            self._load_model()
        except Exception as exc:
            logger.error(f"Failed to initialize Silero VAD model: {exc}")
            self.session = None

    @property
    def is_available(self) -> bool:
        return self.session is not None

    def reset(self) -> None:
        """Reset the internal recurrent state (LSTM) of the VAD model."""
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def predict(self, frame: np.ndarray) -> float:
        """Predict speech probability for a 1D float32 NumPy array of 512 samples.
        
        Args:
            frame: A 1D array of exactly 512 samples (at 16000Hz).
            
        Returns:
            Speech probability as a float from 0.0 to 1.0. Returns 0.0 if VAD is unavailable.
        """
        if not self.is_available or len(frame) != 512:
            return 0.0

        try:
            # Ensure float32 and shape (1, 512)
            input_data = np.expand_dims(frame.astype(np.float32), axis=0)
            sr_data = np.array([16000], dtype=np.int64)

            inputs = {
                "input": input_data,
                "sr": sr_data,
                "h": self._h,
                "c": self._c,
            }

            # Run inference
            out, hn, cn = self.session.run(None, inputs)
            
            # Save updated recurrent states for the next prediction frame
            self._h = hn
            self._c = cn

            return float(out[0][0])
        except Exception as exc:
            logger.error(f"VAD inference error: {exc}")
            return 0.0

    def _ensure_model_exists(self) -> None:
        if self.model_path.exists():
            return

        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading Silero VAD ONNX model from {SILERO_VAD_URL}...")
        print(f"Downloading Silero VAD ONNX model to {self.model_path}...")
        
        try:
            response = requests.get(SILERO_VAD_URL, timeout=30)
            response.raise_for_status()
            self.model_path.write_bytes(response.content)
            logger.info("Silero VAD ONNX model downloaded successfully.")
            print("Silero VAD ONNX model downloaded successfully.")
        except Exception as exc:
            logger.error(f"Failed to download Silero VAD ONNX model: {exc}")
            print(f"Error: Failed to download Silero VAD ONNX model: {exc}")
            raise

    def _load_model(self) -> None:
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self.session = ort.InferenceSession(
            str(self.model_path),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
