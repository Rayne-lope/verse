from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable

import websockets
from websockets.asyncio.server import Server, ServerConnection, serve

from verse.state import StateChangedEvent, StateMachine
from verse.ws.protocol import state_change_message

ClientMessageHandler = Callable[
    ["WebSocketServer", ServerConnection, dict[str, Any]], Awaitable[None] | None
]

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 8765


class WebSocketServer:
    """Broadcasts backend events to all connected frontend clients.

    The state machine emits events synchronously from arbitrary threads, so the
    sync->async bridge schedules every message onto the server's event loop via
    ``loop.call_soon_threadsafe`` before broadcasting.
    """

    def __init__(self, *, on_client_message: ClientMessageHandler | None = None) -> None:
        self._clients: set[ServerConnection] = set()
        self._on_client_message = on_client_message
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._unsubscribe_state: Callable[[], None] | None = None
        self._state_machine: StateMachine | None = None
        self._server: Server | None = None
        self._consumer: asyncio.Task | None = None
        self._config: Any | None = None
        self._mic_status: dict[str, Any] | None = None
        self._now_playing: dict[str, Any] | None = None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def on_client_message(self) -> ClientMessageHandler | None:
        return self._on_client_message

    @on_client_message.setter
    def on_client_message(self, handler: ClientMessageHandler | None) -> None:
        self._on_client_message = handler

    def register(self, client: ServerConnection) -> None:
        self._clients.add(client)

    def unregister(self, client: ServerConnection) -> None:
        self._clients.discard(client)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self._clients:
            return

        payload = json.dumps(message)
        dead: list[ServerConnection] = []
        for client in tuple(self._clients):
            try:
                await client.send(payload)
            except (websockets.ConnectionClosed, RuntimeError):
                dead.append(client)

        for client in dead:
            self.unregister(client)

    def attach_state_machine(self, machine: StateMachine) -> Callable[[], None]:
        from verse.state import State
        from verse.ws.protocol import error_message

        def on_state_changed(event: StateChangedEvent) -> None:
            self.enqueue(state_change_message(event))
            if event.state == State.ERROR:
                msg = event.metadata.get("message", "Unknown error")
                self.enqueue(error_message(msg))

        self._state_machine = machine
        self._unsubscribe_state = machine.subscribe(on_state_changed)
        return self._unsubscribe_state

    def enqueue(self, message: dict[str, Any]) -> None:
        """Thread-safe entry point for producers running off the event loop."""
        if message.get("type") == "mic_status":
            self._mic_status = dict(message)
        elif message.get("type") == "now_playing":
            self._now_playing = dict(message)
        loop = self._loop
        if loop is None:
            self._queue.put_nowait(message)
            return
        loop.call_soon_threadsafe(self._queue.put_nowait, message)

    async def _drain_queue(self) -> None:
        while True:
            message = await self._queue.get()
            await self.broadcast(message)

    async def _handle_connection(self, client: ServerConnection) -> None:
        self.register(client)
        try:
            if self._state_machine is not None:
                await client.send(
                    json.dumps(
                        {"type": "state_change", "state": str(self._state_machine.state)}
                    )
                )
            if self._config is not None:
                from verse.persistence.keychain import get_api_key
                from verse.ws.protocol import config_data_message
                api_keys = {
                    k: get_api_key(k) is not None
                    for k in ("groq", "deepseek", "brave", "spotify", "picovoice")
                }
                await client.send(json.dumps(config_data_message(self._config, api_keys)))
            if self._mic_status is not None:
                await client.send(json.dumps(self._mic_status))
            if self._now_playing is not None:
                await client.send(json.dumps(self._now_playing))
            async for raw in client:
                if self._on_client_message is None:
                    continue
                try:
                    message = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                result = self._on_client_message(self, client, message)
                if asyncio.iscoroutine(result):
                    await result
        except websockets.ConnectionClosed:
            pass
        finally:
            self.unregister(client)

    async def start(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        self._loop = asyncio.get_running_loop()
        self._consumer = asyncio.create_task(self._drain_queue())
        try:
            self._server = await serve(self._handle_connection, host, port)
        except Exception:
            if self._consumer is not None:
                self._consumer.cancel()
                try:
                    await self._consumer
                except asyncio.CancelledError:
                    pass
            self._consumer = None
            self._loop = None
            raise

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._consumer is not None:
            self._consumer.cancel()
            try:
                await self._consumer
            except asyncio.CancelledError:
                pass
            self._consumer = None
        self._loop = None

    async def serve(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
        await self.start(host, port)
        try:
            await asyncio.Future()
        finally:
            await self.close()
