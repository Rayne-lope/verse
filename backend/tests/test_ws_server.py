import asyncio
import socket

import pytest

from verse.config import AppConfig
from verse.main import build_client_message_handler
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

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class MessageClient(FakeClient):
    def __init__(self, messages: list[str]) -> None:
        super().__init__()
        self._messages = list(messages)

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


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
    assert protocol.mic_status_message(True, "ambient") == {
        "type": "mic_status",
        "active": True,
        "mode": "ambient",
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


def test_new_client_receives_current_state():
    server = WebSocketServer()
    machine = StateMachine(initial_state=State.THINKING)
    server.attach_state_machine(machine)
    client = FakeClient()

    asyncio.run(server._handle_connection(client))

    assert client.sent[0] == '{"type": "state_change", "state": "thinking"}'


def test_manual_trigger_message_handler_calls_orchestrator():
    class FakeOrchestrator:
        def __init__(self) -> None:
            self.started = 0
            self.stopped = 0

        def start_listening(self) -> bool:
            self.started += 1
            return True

        async def stop_and_respond(self) -> str:
            self.stopped += 1
            return "ok"

    async def run() -> FakeOrchestrator:
        orchestrator = FakeOrchestrator()
        handler = build_client_message_handler(orchestrator, [AppConfig()])
        await handler(server, client, {"type": "manual_trigger", "action": "start_listening"})
        await handler(server, client, {"type": "manual_trigger", "action": "stop_listening"})
        return orchestrator

    server = WebSocketServer()
    client = FakeClient()
    orchestrator = asyncio.run(run())

    assert orchestrator.started == 1
    assert orchestrator.stopped == 1


def test_manual_trigger_toggle_conversation_starts_auto_when_idle():
    class FakeOrchestrator:
        def __init__(self) -> None:
            self.state_machine = StateMachine(initial_state=State.IDLE)
            self.auto_started = 0
            self.deactivated = 0

        def start_auto_listening(self) -> None:
            self.auto_started += 1

        def deactivate_conversation(self) -> None:
            self.deactivated += 1

    async def run() -> FakeOrchestrator:
        orchestrator = FakeOrchestrator()
        handler = build_client_message_handler(orchestrator, [AppConfig()])
        await handler(server, client, {"type": "manual_trigger", "action": "toggle_conversation"})
        return orchestrator

    server = WebSocketServer()
    client = FakeClient()
    orchestrator = asyncio.run(run())

    assert orchestrator.auto_started == 1
    assert orchestrator.deactivated == 0


def test_manual_trigger_toggle_conversation_deactivates_when_busy():
    class FakeOrchestrator:
        def __init__(self) -> None:
            self.state_machine = StateMachine(initial_state=State.LISTENING)
            self.auto_started = 0
            self.deactivated = 0

        def start_auto_listening(self) -> None:
            self.auto_started += 1

        def deactivate_conversation(self) -> None:
            self.deactivated += 1

    async def run() -> FakeOrchestrator:
        orchestrator = FakeOrchestrator()
        handler = build_client_message_handler(orchestrator, [AppConfig()])
        await handler(server, client, {"type": "manual_trigger", "action": "toggle_conversation"})
        return orchestrator

    server = WebSocketServer()
    client = FakeClient()
    orchestrator = asyncio.run(run())

    assert orchestrator.auto_started == 0
    assert orchestrator.deactivated == 1


def test_interrupt_message_handler_calls_barge_in():
    class FakeOrchestrator:
        def __init__(self) -> None:
            self.interrupted = 0

        def request_barge_in(self) -> bool:
            self.interrupted += 1
            return True

    async def run() -> FakeOrchestrator:
        orchestrator = FakeOrchestrator()
        handler = build_client_message_handler(orchestrator, [AppConfig()])
        await handler(server, client, {"type": "interrupt"})
        return orchestrator

    server = WebSocketServer()
    client = FakeClient()
    orchestrator = asyncio.run(run())

    assert orchestrator.interrupted == 1


def test_server_dispatches_client_messages_to_handler():
    seen = []

    async def handler(_server, _client, message):
        seen.append(message)

    server = WebSocketServer(on_client_message=handler)
    client = MessageClient(['{"type": "manual_trigger", "action": "start_listening"}'])

    asyncio.run(server._handle_connection(client))

    assert seen == [{"type": "manual_trigger", "action": "start_listening"}]


def test_server_start_raises_when_port_is_occupied():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    port = sock.getsockname()[1]

    try:
        server = WebSocketServer()
        with pytest.raises(OSError):
            asyncio.run(server.start("127.0.0.1", port))
    finally:
        sock.close()


def test_all_state_transitions_are_broadcasted():
    server = WebSocketServer()
    machine = StateMachine()
    server.attach_state_machine(machine)

    # 1. idle -> listening
    machine.transition(StateTrigger.HOTKEY_PRESS)
    msg = server._queue.get_nowait()
    assert msg == {"type": "state_change", "state": "listening"}

    # 2. listening -> thinking
    machine.transition(StateTrigger.HOTKEY_RELEASE)
    msg = server._queue.get_nowait()
    assert msg == {"type": "state_change", "state": "thinking"}

    # 3. thinking -> preparing audio
    machine.transition(StateTrigger.TTS_READY)
    msg = server._queue.get_nowait()
    assert msg == {"type": "state_change", "state": "preparing_audio"}

    # 4. preparing audio -> speaking
    machine.transition(StateTrigger.PLAYBACK_START)
    msg = server._queue.get_nowait()
    assert msg == {"type": "state_change", "state": "speaking"}

    # 5. speaking -> idle
    machine.transition(StateTrigger.AUDIO_DONE)
    msg = server._queue.get_nowait()
    assert msg == {"type": "state_change", "state": "idle"}

    # 6. idle -> error
    machine.transition(StateTrigger.ERROR, metadata={"message": "test error"})
    msg1 = server._queue.get_nowait()
    assert msg1 == {"type": "state_change", "state": "error"}
    msg2 = server._queue.get_nowait()
    assert msg2 == {"type": "error", "message": "test error", "recoverable": True}
