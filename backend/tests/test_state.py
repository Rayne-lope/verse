from time import sleep

import pytest

from verse.state import InvalidTransitionError, State, StateMachine, StateTrigger


def test_valid_state_flow_emits_events():
    machine = StateMachine()
    events = []
    machine.subscribe(events.append)

    machine.hotkey_pressed()
    machine.hotkey_released()
    machine.tts_ready()
    machine.audio_done()

    assert machine.state is State.IDLE
    assert [event.state for event in events] == [
        State.LISTENING,
        State.THINKING,
        State.SPEAKING,
        State.IDLE,
    ]


def test_invalid_transition_raises_without_changing_state():
    machine = StateMachine()

    with pytest.raises(InvalidTransitionError):
        machine.transition(StateTrigger.AUDIO_DONE)

    assert machine.state is State.IDLE


def test_error_transition_is_allowed_from_any_state_and_auto_resets():
    machine = StateMachine(error_reset_seconds=0.01)
    machine.hotkey_pressed()

    machine.fail("microphone unavailable")
    assert machine.state is State.ERROR

    sleep(0.03)
    assert machine.state is State.IDLE


def test_unsubscribe_stops_future_events():
    machine = StateMachine()
    events = []
    unsubscribe = machine.subscribe(events.append)

    machine.hotkey_pressed()
    unsubscribe()
    machine.hotkey_released()

    assert len(events) == 1
    assert events[0].state is State.LISTENING


def test_listening_to_idle_on_audio_done():
    machine = StateMachine()
    machine.hotkey_pressed()
    assert machine.state is State.LISTENING

    machine.audio_done()
    assert machine.state is State.IDLE

