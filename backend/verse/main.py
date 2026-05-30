from __future__ import annotations

import asyncio
import logging

from verse.config import AppConfig, load_config
from verse.hotkey import HotkeyListener
from verse.orchestrator import build_orchestrator
from verse.ws.protocol import (
    assistant_text_message,
    audio_level_message,
    error_message,
    tool_executed_message,
    transcript_message,
    pipeline_event_message,
)
from verse.ws.server import WebSocketServer

logger = logging.getLogger(__name__)


def build_client_message_handler(engine):
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

        if msg_type != "manual_trigger":
            return

        action = message.get("action")
        try:
            if action == "start_listening":
                engine.start_listening()
            elif action == "stop_listening":
                await engine.stop_and_respond()
            elif action == "deactivate_conversation":
                if hasattr(engine, "deactivate_conversation"):
                    engine.deactivate_conversation()
        except Exception:
            logger.exception("Manual trigger %r failed", action)

    return handle_client_message


def _build_engine(config: AppConfig, force_classic: bool = False):
    """Return (engine, is_gemini). Gemini engine is duck-type compatible
    with Orchestrator so the wiring below is identical for both."""
    if not force_classic and config.voice.engine == "gemini_live":
        from verse.engines.gemini_live import GeminiLiveEngine
        from verse.state import StateMachine
        from verse.tools.registry import build_default_registry

        registry = build_default_registry(config.tools.enabled)
        state_machine = StateMachine()
        return GeminiLiveEngine(config, registry, state_machine), True

    return build_orchestrator(config), False


def _wire_callbacks(engine, ws_server: WebSocketServer) -> None:
    # partial=False default keeps Orchestrator (1-arg call) backward compatible;
    # GeminiLiveEngine calls on_transcript(text, partial=True/False) for deltas.
    engine.on_transcript = lambda text, partial=False: ws_server.enqueue(
        transcript_message(text, partial=partial)
    )
    engine.on_assistant_text = lambda text: ws_server.enqueue(
        assistant_text_message(text)
    )
    engine.on_tool_executed = lambda name, res: ws_server.enqueue(
        tool_executed_message(name, res)
    )
    engine.on_audio_level = lambda level: ws_server.enqueue(audio_level_message(level))
    engine.on_vad_state = lambda state, prob: ws_server.enqueue(
        {"type": "vad_update", "state": state, "probability": prob}
    )
    engine.on_pipeline_event = lambda stage, event, metadata: ws_server.enqueue(
        pipeline_event_message(stage, event, **metadata)
    )


async def _startup(config: AppConfig, ws_server: WebSocketServer):
    """Start WS server, select engine, wire callbacks, with Gemini fallback."""
    await ws_server.start()

    engine, is_gemini = _build_engine(config)
    ws_server.attach_state_machine(engine.state_machine)
    _wire_callbacks(engine, ws_server)
    ws_server.on_client_message = build_client_message_handler(engine)

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
            engine, _ = _build_engine(config, force_classic=True)
            ws_server.attach_state_machine(engine.state_machine)
            _wire_callbacks(engine, ws_server)
            ws_server.on_client_message = build_client_message_handler(engine)

    return engine


def main() -> None:
    config = load_config()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    ws_server = WebSocketServer()

    try:
        engine = loop.run_until_complete(_startup(config, ws_server))
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

        if engine.state_machine.state is State.SPEAKING and hasattr(engine, "request_barge_in"):
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
