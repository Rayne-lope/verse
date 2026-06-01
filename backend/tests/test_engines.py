from __future__ import annotations

import asyncio
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
        
        # Test basic event enqueueing and callback dispatches
        engine.on_transcript = MagicMock()
        engine.on_assistant_text = MagicMock()
        
        engine._enqueue_event("transcript", {"text": "Gemini speaking", "partial": True})
        
        events_iter = engine.events()
        ev = await anext(events_iter)
        assert ev.type == "transcript"
        assert ev.payload == {"text": "Gemini speaking", "partial": True}
        
        engine.on_transcript.assert_called_once_with("Gemini speaking", True)
