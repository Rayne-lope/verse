from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from verse.config import AppConfig, load_config, update_config_key
from verse.hotkey import HotkeyListener
from verse.orchestrator import build_orchestrator
from verse.ws.protocol import (
    assistant_text_message,
    audio_level_message,
    error_message,
    mic_status_message,
    tool_executed_message,
    transcript_message,
    pipeline_event_message,
    user_partial_transcript_message,
    user_final_transcript_message,
)
from verse.ws.server import WebSocketServer

logger = logging.getLogger(__name__)


def _get_api_keys_status() -> dict[str, bool]:
    from verse.persistence.keychain import get_api_key
    return {
        k: get_api_key(k) is not None
        for k in ("groq", "deepseek", "brave", "spotify", "picovoice")
    }


def build_client_message_handler(
    engine,
    config_holder: list[AppConfig],
    *,
    on_config_changed: Callable[[AppConfig], None] | None = None,
):
    async def handle_client_message(
        _server: WebSocketServer,
        _client,
        message: dict,
    ) -> None:
        msg_type = message.get("type")

        if msg_type == "interrupt":
            if hasattr(engine, "request_barge_in"):
                engine.request_barge_in()
            return

        if msg_type == "get_config":
            from verse.ws.protocol import config_data_message
            _server.enqueue(config_data_message(config_holder[0], _get_api_keys_status()))
            return

        if msg_type == "update_config":
            from verse.ws.protocol import config_data_message, config_updated_message
            section = message.get("section", "")
            key = message.get("key", "")
            value = message.get("value")
            try:
                new_cfg = update_config_key(section, key, value)
                config_holder[0] = new_cfg
                _server.enqueue(config_updated_message(success=True))
                _server.enqueue(config_data_message(new_cfg, _get_api_keys_status()))
                if on_config_changed is not None:
                    on_config_changed(new_cfg)
            except Exception as exc:
                logger.exception("update_config failed for %r.%r", section, key)
                _server.enqueue(config_updated_message(success=False, error=str(exc)))
            return

        if msg_type == "set_api_key":
            from verse.persistence.keychain import set_api_key
            from verse.ws.protocol import api_key_set_message, config_data_message
            key_name = message.get("key_name", "")
            value = message.get("value", "")
            try:
                set_api_key(key_name, value)
                _server.enqueue(api_key_set_message(key_name, success=True))
                _server.enqueue(config_data_message(config_holder[0], _get_api_keys_status()))
                if on_config_changed is not None:
                    on_config_changed(config_holder[0])
            except Exception as exc:
                logger.exception("set_api_key failed for %r", key_name)
                _server.enqueue(api_key_set_message(key_name, success=False))
            return

        if msg_type != "manual_trigger":
            return

        action = message.get("action")
        try:
            if action == "start_listening":
                engine.start_listening()
            elif action == "stop_listening":
                await engine.stop_and_respond()
            elif action == "toggle_conversation":
                from verse.state import State

                if engine.state_machine.state is State.IDLE:
                    if hasattr(engine, "start_auto_listening"):
                        engine.start_auto_listening()
                elif hasattr(engine, "deactivate_conversation"):
                    engine.deactivate_conversation()
            elif action == "deactivate_conversation":
                if hasattr(engine, "deactivate_conversation"):
                    engine.deactivate_conversation()
        except Exception:
            logger.exception("Manual trigger %r failed", action)

    return handle_client_message


def _build_engine(config: AppConfig, force_classic: bool = False, debug_logger = None):
    """Return (engine, is_gemini). Both engines are fully compliant with
    VoiceEngine and duck-type compatible with main.py runner wiring."""
    if not force_classic and config.voice.engine == "gemini_live":
        from verse.engines.live import LiveRealtimeEngine
        from verse.state import StateMachine
        from verse.tools.registry import build_default_registry

        registry = build_default_registry(config.tools.enabled)
        state_machine = StateMachine()
        return LiveRealtimeEngine(config, registry, state_machine), True

    orchestrator = build_orchestrator(config, debug_logger=debug_logger)
    from verse.engines.classic import ClassicPipelineEngine
    return ClassicPipelineEngine(orchestrator), False


def _wire_callbacks(engine, ws_server: WebSocketServer) -> None:
    # partial=False default keeps Orchestrator (1-arg call) backward compatible;
    # GeminiLiveEngine calls on_transcript(text, partial=True/False) for deltas.
    engine.on_transcript = lambda text, partial=False: ws_server.enqueue(
        transcript_message(text, partial=partial, turn_id=getattr(engine, "current_turn_id", None))
    )
    engine.on_assistant_text = lambda text: ws_server.enqueue(
        assistant_text_message(text, turn_id=getattr(engine, "current_turn_id", None))
    )
    engine.on_tool_executed = lambda name, res: ws_server.enqueue(
        tool_executed_message(name, res, turn_id=getattr(engine, "current_turn_id", None))
    )
    engine.on_audio_level = lambda level: ws_server.enqueue(
        audio_level_message(level, turn_id=getattr(engine, "current_turn_id", None))
    )
    engine.on_vad_state = lambda state, prob: ws_server.enqueue(
        {"type": "vad_update", "state": state, "probability": prob, "turn_id": getattr(engine, "current_turn_id", None)}
    )
    engine.on_pipeline_event = lambda stage, event, metadata: ws_server.enqueue(
        pipeline_event_message(stage, event, turn_id=getattr(engine, "current_turn_id", None), **metadata)
    )
    # Streaming STT partial/final transcript callbacks (P6)
    if hasattr(engine, "on_user_partial_transcript"):
        engine.on_user_partial_transcript = (
            lambda text, stability=None: ws_server.enqueue(
                user_partial_transcript_message(text, stability, turn_id=getattr(engine, "current_turn_id", None))
            )
        )
    if hasattr(engine, "on_user_final_transcript"):
        engine.on_user_final_transcript = (
            lambda text: ws_server.enqueue(
                user_final_transcript_message(text, turn_id=getattr(engine, "current_turn_id", None))
            )
        )


class _AlwaysOnRuntime:
    def __init__(
        self,
        engine,
        config_holder: list[AppConfig],
        ws_server: WebSocketServer,
    ) -> None:
        self._engine = engine
        self._config_holder = config_holder
        self._ws_server = ws_server
        self._listener = None
        self._unsubscribe: Callable[[], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if not hasattr(self._engine, "start_auto_listening"):
            return
        from verse.wake_word import PorcupineWakeWordListener

        self._loop = asyncio.get_running_loop()

        def on_wake(keyword_index: int) -> None:
            from verse.state import State

            self._ws_server.enqueue(
                pipeline_event_message(
                    "wake_word", "detected", keyword_index=keyword_index
                )
            )
            if self._engine.state_machine.state is State.IDLE:
                self._engine.start_auto_listening()

        def on_status(active: bool, mode: str) -> None:
            self._ws_server.enqueue(mic_status_message(active, mode))

        def on_error(message: str) -> None:
            self._ws_server.enqueue(error_message(message, recoverable=True))
            self._ws_server.enqueue(
                pipeline_event_message("wake_word", "error", message=message)
            )

        self._listener = PorcupineWakeWordListener(
            self._config_holder[0].always_on,
            on_wake=on_wake,
            on_status=on_status,
            on_error=on_error,
        )
        self._unsubscribe = self._engine.state_machine.subscribe(
            lambda _event: self.schedule_sync()
        )
        self.sync()

    def schedule_sync(self) -> None:
        loop = self._loop
        if loop is None:
            self.sync()
        else:
            loop.call_soon_threadsafe(self.sync)

    def sync(self, _config: AppConfig | None = None) -> None:
        if self._listener is None:
            return
        from verse.state import State

        config = self._config_holder[0].always_on
        self._listener.update_config(config)
        if config.enabled and self._engine.state_machine.state is State.IDLE:
            self._listener.start()
        else:
            self._listener.stop()

    def close(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        if self._listener is not None:
            self._listener.close()
            self._listener = None
        self._ws_server.enqueue(mic_status_message(False, "off"))


async def _startup(config: AppConfig, ws_server: WebSocketServer, debug_logger = None):
    """Start WS server, select engine, wire callbacks, with Gemini fallback."""
    await ws_server.start()

    config_holder: list[AppConfig] = [config]
    ws_server._config = config

    engine, is_gemini = _build_engine(config, debug_logger=debug_logger)
    ws_server.attach_state_machine(engine.state_machine, engine)
    _wire_callbacks(engine, ws_server)
    always_on_runtime = None

    if is_gemini:
        try:
            await engine.start()
        except Exception as exc:
            logger.error(
                "Gemini Live failed: %s — falling back to classic pipeline", exc
            )
            ws_server.enqueue(
                error_message(
                    f"Gemini Live unavailable ({exc}); using classic pipeline",
                    recoverable=True,
                )
            )
            engine, _ = _build_engine(config, force_classic=True, debug_logger=debug_logger)
            ws_server.attach_state_machine(engine.state_machine, engine)
            _wire_callbacks(engine, ws_server)

    if config_holder[0].voice.engine != "gemini_live":
        always_on_runtime = _AlwaysOnRuntime(engine, config_holder, ws_server)
        always_on_runtime.start()

    ws_server.on_client_message = build_client_message_handler(
        engine,
        config_holder,
        on_config_changed=always_on_runtime.sync if always_on_runtime else None,
    )

    from verse.ws.media import media_monitor_task
    ws_server._media_task = asyncio.create_task(media_monitor_task(ws_server))

    return engine, always_on_runtime


def main() -> None:
    config = load_config()

    debug_logger = None
    if getattr(config.debug, "session_logging", False):
        from verse.persistence.debug_logger import DebugSessionLogger
        debug_logger = DebugSessionLogger()
        logger.info(f"Initialized debug session logger: {debug_logger.session_id}")
        print(f"Debug session log directory: {debug_logger.session_dir}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    ws_server = WebSocketServer()

    try:
        engine, always_on_runtime = loop.run_until_complete(
            _startup(config, ws_server, debug_logger=debug_logger)
        )
    except OSError as exc:
        print(f"Error: WebSocket server could not start on localhost:8765: {exc}")
        loop.close()
        raise SystemExit(1) from exc

    async def _respond() -> None:
        try:
            result = await engine.stop_and_respond()
            if result:
                print(f"Verse: {result}")
        except Exception as exc:
            print(f"Error: {exc}")

    def on_pressed() -> None:
        from verse.state import State

        if engine.state_machine.state in (State.PREPARING_AUDIO, State.SPEAKING) and hasattr(engine, "request_barge_in"):
            print("Interrupting...")
            engine.request_barge_in()
            return
        print("Listening...")
        engine.start_listening()

    def on_released() -> None:
        asyncio.run_coroutine_threadsafe(_respond(), loop)

    def on_conversation_toggle() -> None:
        from verse.state import State

        async def _toggle() -> None:
            if engine.state_machine.state is not State.IDLE:
                print("Stopping conversation mode...")
                if hasattr(engine, "deactivate_conversation"):
                    engine.deactivate_conversation()
            else:
                print("Starting conversation mode...")
                if hasattr(engine, "start_auto_listening"):
                    engine.start_auto_listening()

        # Runs on the pynput listener thread; hop to the event loop so
        # get_running_loop() inside start_auto_listening resolves correctly
        # and the VAD turn-detection task actually gets scheduled.
        asyncio.run_coroutine_threadsafe(_toggle(), loop)

    listener = HotkeyListener(
        config.hotkey,
        on_pressed=on_pressed,
        on_released=on_released,
        on_conversation_toggle=on_conversation_toggle,
    )
    listener.start()

    engine_label = "Gemini Live" if config.voice.engine == "gemini_live" else "classic"
    print(
        f"Verse ready ({engine_label}). "
        f"Hold {config.hotkey.trigger} to talk. Press Ctrl+C to quit."
    )

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        listener.stop()

        async def _shutdown() -> None:
            if hasattr(ws_server, "_media_task") and ws_server._media_task:
                ws_server._media_task.cancel()
                try:
                    await ws_server._media_task
                except asyncio.CancelledError:
                    pass
            if always_on_runtime is not None:
                always_on_runtime.close()
            if hasattr(engine, "close"):
                try:
                    await engine.close()
                except Exception:
                    logger.exception("Engine shutdown failed")
            await ws_server.close()

        loop.run_until_complete(_shutdown())
        loop.close()


if __name__ == "__main__":
    main()
