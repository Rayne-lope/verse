from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any

from verse.config import HotkeyConfig
from verse.state import StateMachine


HotkeyCallback = Callable[[], None]


@dataclass(frozen=True)
class HotkeyEvent:
    name: str
    latency_ms: float


class HotkeyListener:
    def __init__(
        self,
        config: HotkeyConfig | None = None,
        *,
        on_pressed: HotkeyCallback | None = None,
        on_released: HotkeyCallback | None = None,
        state_machine: StateMachine | None = None,
    ) -> None:
        self.config = config or HotkeyConfig()
        self.keys = parse_hotkey(self.config.trigger)
        self.on_pressed = on_pressed
        self.on_released = on_released
        self.state_machine = state_machine
        self._pressed_keys: set[str] = set()
        self._active = False
        self._listener: Any = None
        self._press_started_at: float | None = None

    @property
    def is_active(self) -> bool:
        return self._active

    def start(self) -> None:
        if self._listener is not None:
            return

        keyboard = _load_keyboard()
        self._listener = keyboard.Listener(
            on_press=self._handle_press,
            on_release=self._handle_release,
        )
        self._listener.start()

    def stop(self) -> None:
        if self._listener is None:
            return
        self._listener.stop()
        self._listener = None
        self._active = False
        self._pressed_keys.clear()

    def _handle_press(self, key: Any) -> None:
        normalized = normalize_key(key)
        if normalized is None:
            return

        self._pressed_keys.add(normalized)
        if self._active or not self.keys.issubset(self._pressed_keys):
            return

        self._active = True
        self._press_started_at = perf_counter()
        if self.state_machine is not None:
            self.state_machine.hotkey_pressed()
        if self.on_pressed is not None:
            self.on_pressed()

    def _handle_release(self, key: Any) -> None:
        normalized = normalize_key(key)
        if normalized is None:
            return

        was_active = self._active
        self._pressed_keys.discard(normalized)
        if normalized not in self.keys:
            return

        self._active = False
        if not was_active:
            return

        if self.state_machine is not None:
            self.state_machine.hotkey_released()
        if self.on_released is not None:
            self.on_released()


def parse_hotkey(trigger: str) -> frozenset[str]:
    keys = [normalize_key(part.strip().lower()) for part in trigger.split("+")]
    normalized = frozenset(key for key in keys if key)
    if not normalized:
        raise ValueError("Hotkey trigger cannot be empty")
    return normalized


def normalize_key(key: Any) -> str | None:
    if key is None:
        return None
    if isinstance(key, str):
        raw = key
    else:
        raw = getattr(key, "char", None) or getattr(key, "name", None) or str(key)

    raw = str(raw).lower().replace("key.", "").strip("'")
    aliases = {
        "alt_l": "alt",
        "alt_r": "alt",
        "option": "alt",
        "option_l": "alt",
        "option_r": "alt",
        "cmd": "command",
        "cmd_l": "command",
        "cmd_r": "command",
        "ctrl": "control",
        "ctrl_l": "control",
        "ctrl_r": "control",
        " ": "space",
    }
    return aliases.get(raw, raw)


def _load_keyboard() -> Any:
    try:
        from pynput import keyboard
    except ImportError as exc:
        raise RuntimeError(
            "pynput is required for global hotkeys. Install backend dependencies first."
        ) from exc
    return keyboard
