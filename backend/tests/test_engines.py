from __future__ import annotations

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from verse.config import AppConfig
from verse.engines.base import VoiceEvent
from verse.engines.classic import ClassicPipelineEngine
from verse.engines.live import LiveRealtimeEngine
from verse.orchestrator import Orchestrator
from verse.state import State, StateMachine
from verse.tools.registry import ToolRegistry


class TestVoiceEvent:
    def test_voice_event_creation(self) -> None:
        event = VoiceEvent(type="test_event", payload={"key": "val"})
        assert event.type == "test_event"
        assert event.payload == {"key": "val"}


@pytest.mark.anyio
class TestClassicPipelineEngine:
    async def test_classic_engine_wrapping_and_events(self) -> None:
        mock_orchestrator = MagicMock(spec=Orchestrator)
        mock_orchestrator.state_machine = MagicMock(spec=StateMachine)
        
        engine = ClassicPipelineEngine(mock_orchestrator)
        assert engine.state_machine == mock_orchestrator.state_machine

        # Trigger callbacks and verify VoiceEvents are queued
        engine.orchestrator.on_transcript("Hello user", False)
        engine.orchestrator.on_assistant_text("Hello back")
        engine.orchestrator.on_audio_level(0.42)
        engine.orchestrator.on_pipeline_event("stt", "started", {"meta": 1})
        engine.orchestrator.on_tool_executed("play_music", "Playing music...")
        engine.orchestrator.on_vad_state("speech_active", 0.9)

        # Consume events
        events_iter = engine.events()
        
        ev = await anext(events_iter)
        assert ev.type == "transcript"
        assert ev.payload == {"text": "Hello user", "partial": False}

        ev = await anext(events_iter)
        assert ev.type == "assistant_text"
        assert ev.payload == {"text": "Hello back"}

        ev = await anext(events_iter)
        assert ev.type == "audio_level"
        assert ev.payload == {"level": 0.42}

        ev = await anext(events_iter)
        assert ev.type == "pipeline_event"
        assert ev.payload == {"stage": "stt", "event": "started", "metadata": {"meta": 1}}

        ev = await anext(events_iter)
        assert ev.type == "tool_call"
        assert ev.payload == {"name": "play_music", "result": "Playing music..."}

        ev = await anext(events_iter)
        assert ev.type == "vad_state"
        assert ev.payload == {"state": "speech_active", "probability": 0.9}

    async def test_classic_engine_send_audio(self) -> None:
        mock_orchestrator = MagicMock(spec=Orchestrator)
        mock_recorder = MagicMock()
        mock_recorder.is_recording = True
        mock_recorder._queue = asyncio.Queue()
        mock_recorder._chunks = []
        mock_orchestrator.recorder = mock_recorder

        engine = ClassicPipelineEngine(mock_orchestrator)

        # 16-bit Mono PCM chunk
        pcm = bytes([0] * 1024)
        await engine.send_audio(pcm)

        assert len(mock_recorder._chunks) == 1
        assert mock_recorder._queue.qsize() == 1
        
        arr = await mock_recorder._queue.get()
        assert isinstance(arr, np.ndarray)
        assert arr.shape == (512, 1)

    async def test_classic_engine_methods(self) -> None:
        mock_orchestrator = MagicMock(spec=Orchestrator)
        engine = ClassicPipelineEngine(mock_orchestrator)

        engine.start_listening(is_auto=True)
        mock_orchestrator.start_listening.assert_called_once_with(is_auto=True)

        engine.request_barge_in()
        mock_orchestrator.request_barge_in.assert_called_once()

        engine.start_auto_listening()
        mock_orchestrator.start_auto_listening.assert_called_once()

        engine.deactivate_conversation()
        mock_orchestrator.deactivate_conversation.assert_called_once()

    async def test_classic_engine_thread_safety(self) -> None:
        mock_orchestrator = MagicMock(spec=Orchestrator)
        engine = ClassicPipelineEngine(mock_orchestrator)

        event_called = asyncio.Event()

        def test_callback(text, partial):
            assert threading.current_thread() == threading.main_thread()
            event_called.set()

        engine.on_transcript = test_callback

        def run_in_thread():
            # Trigger orchestrator callback from a background thread
            mock_orchestrator.on_transcript("Threaded text", True)

        t = threading.Thread(target=run_in_thread)
        t.start()
        t.join()

        await asyncio.wait_for(event_called.wait(), timeout=1.0)
        assert event_called.is_set()

    async def test_classic_engine_bounded_queue(self) -> None:
        mock_orchestrator = MagicMock(spec=Orchestrator)
        engine = ClassicPipelineEngine(mock_orchestrator)

        # Fill the queue with transient audio levels
        for i in range(300):
            engine._enqueue_event("audio_level", {"level": float(i)})

        # The queue maxsize is 256. If it wasn't dropping, it would be full (size 256)
        # Verify it didn't block and queue size remains capped
        assert engine._event_queue.qsize() <= 256

        # Enqueue a critical event; even if full, it shouldn't raise exception
        engine._enqueue_event("transcript", {"text": "critical", "partial": False})


@pytest.mark.anyio
class TestLiveRealtimeEngine:
    async def test_live_engine_raises_error_without_api_key(self) -> None:
        config = AppConfig()
        registry = MagicMock(spec=ToolRegistry)
        state_machine = StateMachine()

        engine = LiveRealtimeEngine(config, registry, state_machine)
        
        with patch("keyring.get_password", return_value=None):
            with pytest.raises(RuntimeError, match="Gemini API key not set"):
                await engine.start_session()

    async def test_live_engine_session_and_events(self) -> None:
        config = AppConfig()
        registry = MagicMock(spec=ToolRegistry)
        state_machine = StateMachine()

        engine = LiveRealtimeEngine(config, registry, state_machine)
        engine._loop = asyncio.get_running_loop()
        
        # Test basic event enqueueing and callback dispatches
        engine.on_transcript = MagicMock()
        engine.on_assistant_text = MagicMock()
        
        engine._enqueue_event("transcript", {"text": "Gemini speaking", "partial": True})
        
        events_iter = engine.events()
        ev = await anext(events_iter)
        assert ev.type == "transcript"
        assert ev.payload == {"text": "Gemini speaking", "partial": True}
        
        engine.on_transcript.assert_called_once_with("Gemini speaking", True)

    async def test_live_engine_clear_queue(self) -> None:
        config = AppConfig()
        registry = MagicMock(spec=ToolRegistry)
        state_machine = StateMachine()

        engine = LiveRealtimeEngine(config, registry, state_machine)
        
        await engine.send_audio(b"audio chunk 1")
        await engine.send_audio(b"audio chunk 2")
        assert engine._audio_queue.qsize() == 2

        await engine.cancel_response()
        assert engine._audio_queue.qsize() == 0

    async def test_live_engine_error_broadcasting(self) -> None:
        config = AppConfig()
        registry = MagicMock(spec=ToolRegistry)
        state_machine = StateMachine()

        engine = LiveRealtimeEngine(config, registry, state_machine)
        engine._loop = asyncio.get_running_loop()

        mock_client = MagicMock()
        mock_client.aio.live.connect = MagicMock(side_effect=Exception("Connection refused"))

        # Limit the reconnect/session loop to stop immediately on error or close
        async def close_after_a_bit():
            await asyncio.sleep(0.1)
            await engine.close()

        asyncio.create_task(close_after_a_bit())
        
        # Start session loop (patch keyring to return a mock key and client)
        with patch("keyring.get_password", return_value="dummy_key"), \
             patch("google.genai.Client", return_value=mock_client):
            await engine.start_session()
            
            # Read first event from events iterator — should be connection error
            events_iter = engine.events()
            ev = await anext(events_iter)
            assert ev.type == "error"
            assert "Gemini Live error" in ev.payload["message"]
