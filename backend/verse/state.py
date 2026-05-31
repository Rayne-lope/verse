from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import RLock, Timer
from typing import Any, Callable


class State(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    THINKING = "thinking"
    PREPARING_AUDIO = "preparing_audio"
    SPEAKING = "speaking"
    ERROR = "error"


class StateTrigger(StrEnum):
    HOTKEY_PRESS = "hotkey_press"
    HOTKEY_RELEASE = "hotkey_release"
    TTS_READY = "tts_ready"
    PLAYBACK_START = "playback_start"
    AUDIO_DONE = "audio_done"
    ERROR = "error"
    ERROR_TIMEOUT = "error_timeout"


class InvalidTransitionError(ValueError):
    """Raised when a trigger is not valid for the current state."""


@dataclass(frozen=True)
class StateChangedEvent:
    previous_state: State
    state: State
    trigger: StateTrigger
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


Subscriber = Callable[[StateChangedEvent], None]


class StateMachine:
    _TRANSITIONS: dict[tuple[State, StateTrigger], State] = {
        (State.IDLE, StateTrigger.HOTKEY_PRESS): State.LISTENING,
        (State.LISTENING, StateTrigger.HOTKEY_RELEASE): State.THINKING,
        (State.LISTENING, StateTrigger.AUDIO_DONE): State.IDLE,
        (State.THINKING, StateTrigger.TTS_READY): State.PREPARING_AUDIO,
        (State.PREPARING_AUDIO, StateTrigger.PLAYBACK_START): State.SPEAKING,
        (State.PREPARING_AUDIO, StateTrigger.AUDIO_DONE): State.IDLE,
        (State.SPEAKING, StateTrigger.AUDIO_DONE): State.IDLE,
        (State.ERROR, StateTrigger.ERROR_TIMEOUT): State.IDLE,
    }

    def __init__(
        self,
        initial_state: State = State.IDLE,
        *,
        error_reset_seconds: float = 3.0,
    ) -> None:
        self._state = State(initial_state)
        self._error_reset_seconds = error_reset_seconds
        self._subscribers: list[Subscriber] = []
        self._lock = RLock()
        self._error_timer: Timer | None = None

    @property
    def state(self) -> State:
        with self._lock:
            return self._state

    @property
    def is_idle(self) -> bool:
        return self.state is State.IDLE

    def subscribe(self, subscriber: Subscriber) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(subscriber)

        def unsubscribe() -> None:
            with self._lock:
                if subscriber in self._subscribers:
                    self._subscribers.remove(subscriber)

        return unsubscribe

    def transition(
        self,
        trigger: StateTrigger | str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> StateChangedEvent:
        trigger = StateTrigger(trigger)
        metadata = dict(metadata or {})

        with self._lock:
            previous_state = self._state
            next_state = self._next_state(previous_state, trigger)
            self._state = next_state
            if trigger is not StateTrigger.ERROR:
                self._cancel_error_timer()
            event = StateChangedEvent(
                previous_state=previous_state,
                state=next_state,
                trigger=trigger,
                metadata=metadata,
            )
            subscribers = tuple(self._subscribers)

            if next_state is State.ERROR:
                self._schedule_error_reset()

        for subscriber in subscribers:
            subscriber(event)

        return event

    def fail(self, message: str | None = None, **metadata: Any) -> StateChangedEvent:
        if message is not None:
            metadata["message"] = message
        return self.transition(StateTrigger.ERROR, metadata=metadata)

    def hotkey_pressed(self) -> StateChangedEvent:
        return self.transition(StateTrigger.HOTKEY_PRESS)

    def hotkey_released(self) -> StateChangedEvent:
        return self.transition(StateTrigger.HOTKEY_RELEASE)

    def tts_ready(self) -> StateChangedEvent:
        return self.transition(StateTrigger.TTS_READY)

    def playback_started(self) -> StateChangedEvent:
        return self.transition(StateTrigger.PLAYBACK_START)

    def audio_done(self) -> StateChangedEvent:
        return self.transition(StateTrigger.AUDIO_DONE)

    def force_idle(self) -> StateChangedEvent | None:
        with self._lock:
            if self._state == State.IDLE:
                return None
            previous_state = self._state
            self._state = State.IDLE
            self._cancel_error_timer()
            event = StateChangedEvent(
                previous_state=previous_state,
                state=State.IDLE,
                trigger=StateTrigger.AUDIO_DONE,
                metadata={},
            )
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            subscriber(event)
        return event

    def force_thinking(self) -> StateChangedEvent | None:
        with self._lock:
            if self._state == State.THINKING:
                return None
            previous_state = self._state
            self._state = State.THINKING
            self._cancel_error_timer()
            event = StateChangedEvent(
                previous_state=previous_state,
                state=State.THINKING,
                trigger=StateTrigger.HOTKEY_RELEASE,
                metadata={},
            )
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            subscriber(event)
        return event

    def close(self) -> None:
        with self._lock:
            self._cancel_error_timer()

    def _next_state(self, state: State, trigger: StateTrigger) -> State:
        if trigger is StateTrigger.ERROR:
            return State.ERROR

        next_state = self._TRANSITIONS.get((state, trigger))
        if next_state is None:
            raise InvalidTransitionError(
                f"Cannot apply trigger {trigger.value!r} while state is {state.value!r}"
            )
        return next_state

    def _schedule_error_reset(self) -> None:
        self._cancel_error_timer()
        if self._error_reset_seconds < 0:
            return
        self._error_timer = Timer(
            self._error_reset_seconds,
            lambda: self.transition(StateTrigger.ERROR_TIMEOUT),
        )
        self._error_timer.daemon = True
        self._error_timer.start()

    def _cancel_error_timer(self) -> None:
        if self._error_timer is not None:
            self._error_timer.cancel()
            self._error_timer = None


default_state_machine = StateMachine()
