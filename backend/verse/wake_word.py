from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
import sounddevice as sd

from verse.config import AlwaysOnConfig
from verse.persistence.keychain import get_api_key

logger = logging.getLogger(__name__)


class WakeWordUnavailableError(RuntimeError):
    """Raised when always-on wake word mode cannot be started."""


class PorcupineWakeWordListener:
    """Low-power ambient wake word listener backed by Picovoice Porcupine."""

    def __init__(
        self,
        config: AlwaysOnConfig,
        *,
        on_wake: Callable[[int], None],
        on_status: Callable[[bool, str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> None:
        self.config = config
        self._on_wake = on_wake
        self._on_status = on_status
        self._on_error = on_error
        self._porcupine: Any | None = None
        self._stream: sd.InputStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._active = False
        self._triggered = False
        self._failed = False

    @property
    def is_active(self) -> bool:
        return self._active

    def update_config(self, config: AlwaysOnConfig) -> None:
        if config == self.config:
            return
        self.close()
        self.config = config
        self._failed = False

    def start(self) -> bool:
        if self._active:
            return True
        if self._failed or not self.config.enabled:
            return False

        try:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                self._loop = None

            porcupine = self._ensure_porcupine()
            self._triggered = False
            self._stream = sd.InputStream(
                samplerate=porcupine.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=porcupine.frame_length,
                callback=self._on_audio,
            )
            self._active = True
            self._stream.start()
            if self._active:
                self._emit_status(True, "ambient")
                logger.info("Always-on wake word listener started.")
            return True
        except Exception as exc:
            self._failed = True
            self._close_stream()
            self._delete_porcupine()
            self._emit_status(False, "off")
            message = f"Always-on wake word unavailable: {exc}"
            logger.warning(message)
            if self._on_error is not None:
                self._on_error(message)
            return False

    def stop(self) -> None:
        was_active = self._active or self._stream is not None
        self._close_stream()
        self._triggered = False
        if was_active:
            self._emit_status(False, "off")
            logger.info("Always-on wake word listener stopped.")

    def close(self) -> None:
        self.stop()
        self._delete_porcupine()

    def _ensure_porcupine(self) -> Any:
        if self._porcupine is not None:
            return self._porcupine

        import pvporcupine

        access_key = _get_picovoice_access_key()
        if not access_key:
            raise WakeWordUnavailableError(
                "set Picovoice AccessKey in Keychain as 'picovoice' or PICOVOICE_ACCESS_KEY"
            )

        kwargs: dict[str, Any] = {
            "access_key": access_key,
            "sensitivities": [_clamp_sensitivity(self.config.sensitivity)],
        }

        keyword_path = self.config.keyword_path.strip()
        keyword = self.config.keyword.strip()
        if keyword_path:
            expanded = Path(keyword_path).expanduser()
            if not expanded.exists():
                if keyword:
                    kwargs["keywords"] = [keyword]
                else:
                    raise WakeWordUnavailableError(
                        f"wake word file not found: {expanded}"
                    )
            else:
                kwargs["keyword_paths"] = [str(expanded)]
        elif keyword:
            kwargs["keywords"] = [keyword]
        else:
            raise WakeWordUnavailableError(
                "configure always_on.keyword_path or always_on.keyword"
            )

        model_path = self.config.model_path.strip()
        if model_path:
            kwargs["model_path"] = str(Path(model_path).expanduser())

        device = self.config.device.strip()
        if device:
            kwargs["device"] = device

        self._porcupine = pvporcupine.create(**kwargs)
        return self._porcupine

    def _on_audio(
        self,
        indata: np.ndarray[Any, Any],
        _frames: int,
        _time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.debug("Wake word stream status: %s", status)
        if self._triggered or self._porcupine is None:
            return

        pcm = np.asarray(indata[:, 0], dtype=np.int16)
        if pcm.shape[0] != self._porcupine.frame_length:
            return

        try:
            keyword_index = self._porcupine.process(pcm.tolist())
        except Exception as exc:
            self._handle_error(f"Wake word processing failed: {exc}")
            return

        if keyword_index >= 0:
            self._triggered = True
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._handle_detection, keyword_index)
            else:
                self._handle_detection(keyword_index)

    def _handle_detection(self, keyword_index: int) -> None:
        self.stop()
        try:
            self._on_wake(keyword_index)
        except Exception as exc:
            self._handle_error(f"Wake word callback failed: {exc}")

    def _handle_error(self, message: str) -> None:
        logger.warning(message)
        self.stop()
        if self._on_error is not None:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._on_error, message)
            else:
                self._on_error(message)

    def _close_stream(self) -> None:
        stream = self._stream
        self._stream = None
        self._active = False
        if stream is None:
            return
        try:
            stream.stop()
        finally:
            stream.close()

    def _delete_porcupine(self) -> None:
        porcupine = self._porcupine
        self._porcupine = None
        if porcupine is not None:
            porcupine.delete()

    def _emit_status(self, active: bool, mode: str) -> None:
        if self._on_status is not None:
            self._on_status(active, mode)


def _get_picovoice_access_key() -> str | None:
    return get_api_key("picovoice") or os.getenv("PICOVOICE_ACCESS_KEY")


def _clamp_sensitivity(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
