import asyncio
import numpy as np
import pytest
from unittest.mock import MagicMock

from verse.config import AppConfig, VADConfig, HotkeyConfig
from verse.orchestrator import Orchestrator
from verse.state import State, StateMachine
from verse.audio.vad import VADState
from verse.llm.base import LLMResponse
from verse.tools.registry import Tool, ToolRegistry
from verse.ws.protocol import pipeline_event_message, MSG_PIPELINE_EVENT


class FakeVADManager:
    def __init__(self, available=True):
        self._available = available

    @property
    def is_available(self):
        return self._available

    def reset(self):
        pass

    def predict(self, frame):
        return 0.8


class FakeVADStateMachine:
    def __init__(self, sequence=None):
        self._sequence = list(sequence or [])
        self.elapsed_ms = 120.0

    def reset(self):
        pass

    def process_frame(self, frame, probability):
        if self._sequence:
            return self._sequence.pop(0)
        return VADState.WAITING_FOR_SPEECH, None


class FakeRecorder:
    def __init__(self):
        self.is_recording = True
        self._queue = asyncio.Queue()

    def start_recording(self, on_audio_level=None):
        self.is_recording = True

    def stop_recording(self):
        self.is_recording = False
        from verse.audio.capture import samples_to_wav_bytes
        return samples_to_wav_bytes(np.zeros(3200), 16000)

    async def read_chunk(self):
        return await self._queue.get()


class FakeSTT:
    def __init__(self, fail=False):
        self.fail = fail

    async def transcribe(self, audio, language=None):
        if self.fail:
            raise RuntimeError("STT error")
        return "fake transcript"


class FakeLLM:
    async def chat(self, messages, tools=None):
        return LLMResponse(text="fake reply", tool_calls=[])


class FakeTTS:
    async def synthesize(self, text):
        return text.encode()


def test_pipeline_event_message_formatting():
    msg = pipeline_event_message("vad", "speech_started", stop_reason="silence")
    assert msg == {
        "type": MSG_PIPELINE_EVENT,
        "stage": "vad",
        "event": "speech_started",
        "stop_reason": "silence"
    }


@pytest.mark.anyio
async def test_orchestrator_triggers_stt_and_tts_pipeline_events():
    events = []
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=StateMachine(initial_state=State.THINKING),
        play=lambda audio: None,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    
    from verse.audio.capture import samples_to_wav_bytes
    dummy_wav = samples_to_wav_bytes(np.zeros(3200), 16000)
    
    await orch.handle_audio(dummy_wav)
    
    # Assert STT and TTS events are dispatched in order
    assert ("stt", "started", {}) in events
    assert ("stt", "completed", {"text": "fake transcript"}) in events
    assert ("tts", "started", {}) in events
    assert ("tts", "completed", {}) in events


@pytest.mark.anyio
async def test_orchestrator_triggers_tool_pipeline_events():
    events = []
    
    def my_test_tool():
        return "tool success"
        
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="my_test_tool",
            description="test tool",
            parameters={"type": "object", "properties": {}},
            handler=my_test_tool,
        )
    )
    
    tool_call = {
        "id": "c1",
        "type": "function",
        "function": {"name": "my_test_tool", "arguments": "{}"},
    }
    
    class ToolLLM:
        def __init__(self):
            self.first = True
        async def chat(self, messages, tools=None):
            if self.first:
                self.first = False
                return LLMResponse(text="", tool_calls=[tool_call])
            return LLMResponse(text="final reply", tool_calls=[])
            
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=ToolLLM(),
        tts=FakeTTS(),
        registry=registry,
        state_machine=StateMachine(initial_state=State.THINKING),
        play=lambda audio: None,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    
    from verse.audio.capture import samples_to_wav_bytes
    dummy_wav = samples_to_wav_bytes(np.zeros(3200), 16000)
    
    await orch.handle_audio(dummy_wav)
    
    # Assert Tool events are dispatched
    assert ("tool", "started", {"name": "my_test_tool"}) in events
    assert ("tool", "completed", {"name": "my_test_tool", "result": "tool success"}) in events


@pytest.mark.anyio
async def test_orchestrator_triggers_error_pipeline_event():
    events = []
    
    orch = Orchestrator(
        stt=FakeSTT(fail=True),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=StateMachine(initial_state=State.THINKING, error_reset_seconds=-1),
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    
    from verse.audio.capture import samples_to_wav_bytes
    dummy_wav = samples_to_wav_bytes(np.zeros(3200), 16000)
    
    with pytest.raises(RuntimeError):
        await orch.handle_audio(dummy_wav)
        
    assert len(events) >= 2
    assert ("stt", "started", {}) in events
    # The last event should be a recoverable error
    error_event = events[-1]
    assert error_event[0] == "error"
    assert error_event[1] == "recoverable_error"
    assert error_event[2]["code"] == "pipeline_failure"
    assert "STT error" in error_event[2]["message"]


@pytest.mark.anyio
async def test_orchestrator_triggers_vad_pipeline_events():
    events = []
    loop = asyncio.get_running_loop()
    
    frame = np.ones((512, 1), dtype=np.float32)
    fake_speech_frames = [np.ones(512, dtype=np.float32)]
    
    vad_manager = FakeVADManager(available=True)
    # Transitions: WAITING -> SPEECH_ACTIVE -> ENDED
    vad_state_machine = FakeVADStateMachine([
        (VADState.WAITING_FOR_SPEECH, None),
        (VADState.SPEECH_ACTIVE, None),
        (VADState.ENDED, fake_speech_frames)
    ])
    
    recorder = FakeRecorder()
    
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=False),
        vad=VADConfig(enabled=True)
    )
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=StateMachine(initial_state=State.LISTENING),
        config=config,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
        play=lambda audio: None,
    )
    orch._loop = loop
    orch._auto_listening = True
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    
    await recorder._queue.put(frame)
    await recorder._queue.put(frame)
    await recorder._queue.put(frame)
    
    task = loop.create_task(orch._run_vad_loop())
    orch._vad_task = task
    await task
    
    # Verify speech_started, speech_ended, and debug are emitted
    assert ("vad", "speech_started", {}) in events
    assert ("vad", "speech_ended", {"stop_reason": "silence"}) in events
    
    # Verify debug was emitted
    debug_events = [e for e in events if e[0] == "vad" and e[1] == "debug"]
    assert len(debug_events) > 0
    assert debug_events[0][2]["elapsed_ms"] == 120.0
