from __future__ import annotations

from collections import deque
from enum import StrEnum
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


class VADState(StrEnum):
    WAITING_FOR_SPEECH = "waiting_for_speech"
    SPEECH_ACTIVE = "speech_active"
    ENDED = "ended"
    TIMEOUT = "timeout"


class VADEndpointingStateMachine:
    def __init__(self, config: Any = None) -> None:
        from verse.config import VADConfig
        self.config = config or VADConfig()
        self._state = VADState.WAITING_FOR_SPEECH
        
        # Frame duration is exactly 32ms (512 samples at 16000Hz)
        self._frame_ms = 32
        pre_roll_frames = max(1, self.config.pre_roll_ms // self._frame_ms)
        self._pre_roll: deque[np.ndarray] = deque(maxlen=pre_roll_frames)
        
        self._speech_frames: list[np.ndarray] = []
        self._consecutive_speech_frames = 0
        self._consecutive_silence_frames = 0
        self._elapsed_ms = 0.0

    @property
    def state(self) -> VADState:
        return self._state

    @property
    def elapsed_ms(self) -> float:
        return self._elapsed_ms

    def reset(self) -> None:
        """Reset state machine counters and buffers."""
        self._state = VADState.WAITING_FOR_SPEECH
        self._pre_roll.clear()
        self._speech_frames.clear()
        self._consecutive_speech_frames = 0
        self._consecutive_silence_frames = 0
        self._elapsed_ms = 0.0

    def process_frame(
        self, frame: np.ndarray, probability: float
    ) -> tuple[VADState, list[np.ndarray] | None]:
        """Process a single frame of 512 samples with its speech probability.
        
        Returns:
            A tuple of (current_state, final_utterance_chunks).
            The final_utterance_chunks is a list of frames if the state is ENDED, otherwise None.
        """
        self._elapsed_ms += self._frame_ms

        if self._state is VADState.WAITING_FOR_SPEECH:
            self._pre_roll.append(frame)
            if probability >= self.config.start_threshold:
                self._consecutive_speech_frames += 1
            else:
                self._consecutive_speech_frames = 0

            if self._consecutive_speech_frames * self._frame_ms >= self.config.speech_start_ms:
                self._state = VADState.SPEECH_ACTIVE
                # Preload speech frames with all buffered pre-roll chunks
                self._speech_frames = list(self._pre_roll)
                self._consecutive_speech_frames = 0
            elif self._elapsed_ms >= self.config.followup_timeout_s * 1000:
                self._state = VADState.TIMEOUT

        elif self._state is VADState.SPEECH_ACTIVE:
            self._speech_frames.append(frame)
            if probability < self.config.end_threshold:
                self._consecutive_silence_frames += 1
            else:
                self._consecutive_silence_frames = 0

            speech_duration_ms = len(self._speech_frames) * self._frame_ms

            if self._consecutive_silence_frames * self._frame_ms >= self.config.end_silence_ms:
                if speech_duration_ms >= self.config.min_utterance_ms:
                    self._state = VADState.ENDED
                    return self._state, list(self._speech_frames)
                else:
                    # Discard too short noise, and go back to waiting
                    logger.debug("Discarded too short noise (duration: %d ms)", speech_duration_ms)
                    self._state = VADState.WAITING_FOR_SPEECH
                    self._speech_frames.clear()
                    self._pre_roll.clear()
                    self._consecutive_speech_frames = 0
                    self._consecutive_silence_frames = 0

            elif speech_duration_ms >= self.config.max_utterance_ms:
                self._state = VADState.ENDED
                return self._state, list(self._speech_frames)

        return self._state, None

