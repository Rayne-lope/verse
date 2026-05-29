from verse.hotkey import HotkeyListener, normalize_key, parse_hotkey
from verse.state import State, StateMachine


def test_parse_hotkey_normalizes_aliases():
    assert parse_hotkey("alt+space") == frozenset({"alt", "space"})
    assert parse_hotkey("option+space") == frozenset({"alt", "space"})


def test_hotkey_listener_emits_press_and_release_once():
    pressed = []
    released = []
    listener = HotkeyListener(
        on_pressed=lambda: pressed.append(True),
        on_released=lambda: released.append(True),
    )

    listener._handle_press("alt")
    listener._handle_press("space")
    listener._handle_press("space")
    listener._handle_release("space")

    assert pressed == [True]
    assert released == [True]
    assert listener.is_active is False


def test_hotkey_listener_can_drive_state_machine():
    machine = StateMachine(error_reset_seconds=-1)
    listener = HotkeyListener(state_machine=machine)

    listener._handle_press("alt")
    listener._handle_press("space")
    assert machine.state is State.LISTENING

    listener._handle_release("space")
    assert machine.state is State.THINKING


def test_normalize_key_accepts_pynput_like_objects():
    key = type("Key", (), {"name": "alt_l"})()

    assert normalize_key(key) == "alt"
