from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Callable

import numpy as np

from verse.engines.base import VoiceEngine, VoiceEvent
from verse.orchestrator import Orchestrator
from verse.state import StateMachine


class ClassicPipelineEngine(VoiceEngine):
    """
    Classic speech-to-speech voice pipeline wrapper.
    Adapts the local Orchestrator to comply with the VoiceEngine interface.
    """

    on_transcript: Callable[[str, bool], None] | None = None
    on_assistant_text: Callable[[str], None] | None = None
    on_audio_level: Callable[[float], None] | None = None
    on_tool_executed: Callable[[str, str], None] | None = None
    on_pipeline_event: Callable[[str, str, dict[str, Any]], None] | None = None
    on_vad_state: Callable[[str, float], None] | None = None
    on_user_partial_transcript: Callable[[str, float | None], None] | None = None
    on_user_final_transcript: Callable[[str], None] | None = None

    def __init__(self, orchestrator: Orchestrator) -> None:
        self.orchestrator = orchestrator
        self._event_queue: asyncio.Queue[VoiceEvent] = asyncio.Queue()
        self._loop = asyncio.get_event_loop()
        self._wire_callbacks()

    @property
    def state_machine(self) -> StateMachine:
        return self.orchestrator.state_machine

    def _wire_callbacks(self) -> None:
        # Wire orchestrator to our queue and external callbacks
        def handle_transcript(text: str, partial: bool = False) -> None:
            self._enqueue_event("transcript", {"text": text, "partial": partial})
            if self.on_transcript:
                self.on_transcript(text, partial)

        def handle_assistant_text(text: str) -> None:
            self._enqueue_event("assistant_text", {"text": text})
            if self.on_assistant_text:
                self.on_assistant_text(text)

        def handle_audio_level(lvl: float) -> None:
            self._enqueue_event("audio_level", {"level": lvl})
            if self.on_audio_level:
                self.on_audio_level(lvl)

        def handle_pipeline_event(stage: str, event: str, meta: dict[str, Any]) -> None:
            self._enqueue_event("pipeline_event", {"stage": stage, "event": event, "metadata": meta})
            if self.on_pipeline_event:
                self.on_pipeline_event(stage, event, meta)

        def handle_tool_executed(name: str, res: str) -> None:
            self._enqueue_event("tool_call", {"name": name, "result": res})
            if self.on_tool_executed:
                self.on_tool_executed(name, res)

        def handle_vad_state(state: str, prob: float) -> None:
            self._enqueue_event("vad_state", {"state": state, "probability": prob})
            if self.on_vad_state:
                self.on_vad_state(state, prob)

        self.orchestrator.on_transcript = handle_transcript
        self.orchestrator.on_assistant_text = handle_assistant_text
        self.orchestrator.on_audio_level = handle_audio_level
        self.orchestrator.on_pipeline_event = handle_pipeline_event
        self.orchestrator.on_tool_executed = handle_tool_executed
        self.orchestrator.on_vad_state = handle_vad_state

        if hasattr(self.orchestrator, "on_user_partial_transcript"):
            def handle_user_partial(text: str, stability: float | None = None) -> None:
                self._enqueue_event("user_partial_transcript", {"text": text, "stability": stability})
                if self.on_user_partial_transcript:
                    self.on_user_partial_transcript(text, stability)
            self.orchestrator.on_user_partial_transcript = handle_user_partial

        if hasattr(self.orchestrator, "on_user_final_transcript"):
            def handle_user_final(text: str) -> None:
                self._enqueue_event("user_final_transcript", {"text": text})
                if self.on_user_final_transcript:
                    self.on_user_final_transcript(text)
            self.orchestrator.on_user_final_transcript = handle_user_final

    def _enqueue_event(self, type_: str, payload: dict[str, Any]) -> None:
        event = VoiceEvent(type=type_, payload=payload)
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, event)
        else:
            self._event_queue.put_nowait(event)

    # ------------------------------------------------------------------
    # VoiceEngine Interface Compliance
    # ------------------------------------------------------------------

    async def start_session(self) -> None:
        """Begin listening locally."""
        self.start_listening()

    async def send_audio(self, pcm: bytes) -> None:
        """Route external PCM audio chunks directly to local VAD queue."""
        if self.orchestrator.recorder and self.orchestrator.recorder.is_recording:
            # Standard 16-bit 16kHz Mono PCM input
            arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            arr = arr.reshape(-1, 1)
            
            # Save chunk to chunks array so final WAV export compiles correctly
            self.orchestrator.recorder._chunks.append(arr)
            
            # Feed into local VAD queue
            if self.orchestrator.recorder._queue is not None:
                try:
                    self.orchestrator.recorder._queue.put_nowait(arr)
                except asyncio.QueueFull:
                    pass

    async def events(self) -> AsyncIterator[VoiceEvent]:
        """Stream orchestration events to listener."""
        while True:
            yield await self._event_queue.get()

    async def cancel_response(self) -> None:
        """Trigger immediate response interruption."""
        self.request_barge_in()

    async def close(self) -> None:
        """Shut down orchestrator."""
        if hasattr(self.orchestrator, "close"):
            await self.orchestrator.close()

    # ------------------------------------------------------------------
    # Compatibility methods mapped directly to Orchestrator
    # ------------------------------------------------------------------

    def start_listening(self, is_auto: bool = False) -> bool:
        return self.orchestrator.start_listening(is_auto=is_auto)

    async def stop_and_respond(self, *, history: list[dict[str, Any]] | None = None) -> str:
        return await self.orchestrator.stop_and_respond(history=history)

    def request_barge_in(self) -> None:
        if hasattr(self.orchestrator, "request_barge_in"):
            self.orchestrator.request_barge_in()

    def start_auto_listening(self) -> None:
        if hasattr(self.orchestrator, "start_auto_listening"):
            self.orchestrator.start_auto_listening()

    def deactivate_conversation(self) -> None:
        if hasattr(self.orchestrator, "deactivate_conversation"):
            self.orchestrator.deactivate_conversation()
