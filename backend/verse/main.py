from __future__ import annotations

import asyncio

from verse.config import load_config
from verse.hotkey import HotkeyListener
from verse.orchestrator import build_orchestrator
from verse.ws.protocol import (
    assistant_text_message,
    audio_level_message,
    tool_executed_message,
    transcript_message,
)
from verse.ws.server import WebSocketServer


def main() -> None:
    config = load_config()
    orchestrator = build_orchestrator(config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    ws_server = WebSocketServer()
    ws_server.attach_state_machine(orchestrator.state_machine)

    # Wire up orchestrator callbacks to the WebSocket server
    orchestrator.on_transcript = lambda text: ws_server.enqueue(transcript_message(text))
    orchestrator.on_assistant_text = lambda text: ws_server.enqueue(assistant_text_message(text))
    orchestrator.on_tool_executed = lambda name, res: ws_server.enqueue(
        tool_executed_message(name, res)
    )
    orchestrator.on_audio_level = lambda level: ws_server.enqueue(audio_level_message(level))

    async def _respond() -> None:
        try:
            reply = await orchestrator.stop_and_respond()
            print(f"Verse: {reply}")
        except Exception as exc:
            print(f"Error: {exc}")

    def on_pressed() -> None:
        print("Listening...")
        orchestrator.start_listening()

    def on_released() -> None:
        asyncio.run_coroutine_threadsafe(_respond(), loop)

    listener = HotkeyListener(
        config.hotkey,
        on_pressed=on_pressed,
        on_released=on_released,
    )
    listener.start()
    print(f"Verse ready. Hold {config.hotkey.trigger} to talk. Press Ctrl+C to quit.")

    # Start the WebSocket server on the loop and retain a reference to prevent garbage collection
    background_tasks = set()
    ws_task = loop.create_task(ws_server.serve())
    background_tasks.add(ws_task)
    ws_task.add_done_callback(background_tasks.discard)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        listener.stop()
        loop.close()


if __name__ == "__main__":
    main()
