import asyncio

from verse.state import State, StateMachine, StateTrigger
from verse.ws import protocol
from verse.ws.server import WebSocketServer


class FakeClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[str] = []
        self._fail = fail

    async def send(self, payload: str) -> None:
        if self._fail:
            raise RuntimeError("client gone")
        self.sent.append(payload)


def test_state_change_message_serializes_state():
    machine = StateMachine()
    event = machine.hotkey_pressed()

    assert protocol.state_change_message(event) == {
        "type": "state_change",
        "state": "listening",
    }


def test_message_builders_match_protocol():
    assert protocol.audio_level_message(0.73) == {"type": "audio_level", "level": 0.73}
    assert protocol.transcript_message("hi") == {
        "type": "transcript",
        "text": "hi",
        "partial": False,
    }
    assert protocol.assistant_text_message("ok") == {
        "type": "assistant_text",
        "text": "ok",
    }
    assert protocol.tool_executed_message("play_music", "ok") == {
        "type": "tool_executed",
        "name": "play_music",
        "result": "ok",
    }
    assert protocol.error_message("boom", recoverable=False) == {
        "type": "error",
        "message": "boom",
        "recoverable": False,
    }


def test_broadcast_sends_to_all_clients_and_drops_dead_ones():
    server = WebSocketServer()
    good = FakeClient()
    bad = FakeClient(fail=True)
    server.register(good)
    server.register(bad)

    asyncio.run(server.broadcast(protocol.audio_level_message(0.5)))

    assert good.sent == ['{"type": "audio_level", "level": 0.5}']
    assert server.client_count == 1  # dead client dropped


def test_attach_state_machine_enqueues_state_change():
    server = WebSocketServer()
    machine = StateMachine()
    server.attach_state_machine(machine)

    machine.transition(StateTrigger.HOTKEY_PRESS)

    message = server._queue.get_nowait()
    assert message == {"type": "state_change", "state": "listening"}
    assert machine.state is State.LISTENING
