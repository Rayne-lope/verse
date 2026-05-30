import asyncio
import numpy as np
import pytest
from unittest.mock import MagicMock

from pathlib import Path

from verse.config import AppConfig, VADConfig, HotkeyConfig
from verse.orchestrator import Orchestrator
from verse.state import State, StateMachine
from verse.audio.vad import VADState
from verse.llm.base import LLMResponse
from verse.tools.registry import ToolRegistry


class FakeVADManager:
    def __init__(self, available=True):
        self._available = available
        self.reset_called = 0
        self.predictions = []

    @property
    def is_available(self):
        return self._available

    def reset(self):
        self.reset_called += 1

    def predict(self, frame):
        self.predictions.append(frame)
        return 0.8


class FakeVADStateMachine:
    def __init__(self, sequence=None):
        self.reset_called = 0
        self._sequence = list(sequence or [])
        self.frames_processed = []
        self.elapsed_ms = 0.0

    def reset(self):
        self.reset_called += 1

    def process_frame(self, frame, probability):
        self.frames_processed.append((frame, probability))
        if self._sequence:
            return self._sequence.pop(0)
        return VADState.WAITING_FOR_SPEECH, None


class FakeRecorder:
    def __init__(self):
        self.is_recording = False
        self.started = 0
        self._queue = asyncio.Queue()

    def start_recording(self, on_audio_level=None):
        self.is_recording = True
        self.started += 1
        self.on_audio_level = on_audio_level

    def stop_recording(self):
        self.is_recording = False
        return b"wav_data"

    async def read_chunk(self):
        return await self._queue.get()


class FakeSTT:
    def __init__(self):
        self.calls = []

    async def transcribe(self, audio, language=None):
        self.calls.append((audio, language))
        return "fake transcript"


class FakeLLM:
    async def chat(self, messages, tools=None):
        return LLMResponse(text="fake reply", tool_calls=[])


class FakeTTS:
    async def synthesize(self, text):
        return text.encode()


def test_orchestrator_initializes_default_vad_components():
    config = AppConfig()
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=StateMachine(),
        config=config,
    )
    assert orch.vad_manager is not None
    assert orch.vad_state_machine is not None
    assert str(orch.vad_manager.model_path) == str(Path(config.vad.model_path).expanduser())


def test_orchestrator_uses_injected_vad_components():
    vad_manager = FakeVADManager()
    vad_state_machine = FakeVADStateMachine()
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=StateMachine(),
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )
    assert orch.vad_manager is vad_manager
    assert orch.vad_state_machine is vad_state_machine


def test_start_auto_listening_fallback_when_disabled():
    # Enabled but not available
    vad_manager = FakeVADManager(available=False)
    vad_state_machine = FakeVADStateMachine()
    config = AppConfig(vad=VADConfig(enabled=True))
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=StateMachine(),
        config=config,
        recorder=FakeRecorder(),
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )
    
    orch.start_auto_listening()
    
    assert orch._auto_listening is True
    # Should NOT have started VAD loop task since unavailable
    assert orch._vad_task is None
    # Reset should not be called
    assert vad_manager.reset_called == 0


@pytest.mark.anyio
async def test_start_auto_listening_spawns_vad_task():
    vad_manager = FakeVADManager(available=True)
    vad_state_machine = FakeVADStateMachine()
    config = AppConfig(vad=VADConfig(enabled=True))
    recorder = FakeRecorder()
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=StateMachine(),
        config=config,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )
    
    orch.start_auto_listening()
    
    assert orch._auto_listening is True
    assert orch._vad_task is not None
    assert vad_manager.reset_called == 1
    assert vad_state_machine.reset_called == 1
    
    # Cleanup task
    orch._cancel_vad_task()


@pytest.mark.anyio
async def test_run_vad_loop_ended_state():
    # Setup test event loop
    loop = asyncio.get_running_loop()
    
    # Configure precise state updates
    frame_speech = np.ones((512, 1), dtype=np.float32)
    fake_speech_frames = [np.ones(512, dtype=np.float32)]
    
    vad_manager = FakeVADManager(available=True)
    # VAD State Machine outputs WAITING then ENDED with speech chunks
    vad_state_machine = FakeVADStateMachine([
        (VADState.WAITING_FOR_SPEECH, None),
        (VADState.ENDED, fake_speech_frames)
    ])
    
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    config = AppConfig(hotkey=HotkeyConfig(conversation_mode=False))
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        config=config,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
        play=lambda audio: None,
    )
    
    orch._loop = loop
    orch._auto_listening = True
    recorder.is_recording = True
    
    # Enqueue two frames into recorder
    await recorder._queue.put(frame_speech)
    await recorder._queue.put(frame_speech)
    
    # Run the VAD loop task
    task = loop.create_task(orch._run_vad_loop())
    orch._vad_task = task
    
    # Wait for the task to finish
    await task
    
    # Recorder should have been stopped
    assert recorder.is_recording is False
    assert orch._auto_listening is False
    assert orch._vad_task is None
    
    # Verify the state machine transitioned correctly
    assert machine.state is State.IDLE


@pytest.mark.anyio
async def test_run_vad_loop_timeout_state():
    loop = asyncio.get_running_loop()
    frame_silence = np.zeros((512, 1), dtype=np.float32)
    
    vad_manager = FakeVADManager(available=True)
    # VAD State Machine outputs TIMEOUT
    vad_state_machine = FakeVADStateMachine([
        (VADState.TIMEOUT, None)
    ])
    
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    events = []
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    
    orch._loop = loop
    orch._auto_listening = True
    recorder.is_recording = True
    
    await recorder._queue.put(frame_silence)
    
    task = loop.create_task(orch._run_vad_loop())
    orch._vad_task = task
    await task
    
    assert recorder.is_recording is False
    assert orch._auto_listening is False
    assert machine.state is State.IDLE
    assert ("vad", "timeout", {}) in events


def test_manual_push_to_talk_bypasses_vad():
    vad_manager = FakeVADManager(available=True)
    vad_state_machine = FakeVADStateMachine()
    recorder = FakeRecorder()
    machine = StateMachine()
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )
    
    # In manual mode, we call start_listening() directly with is_auto=False
    success = orch.start_listening(is_auto=False)
    
    assert success is True
    assert recorder.is_recording is True
    assert orch._auto_listening is False
    assert orch._vad_task is None


def test_stop_and_respond_discards_short_audio():
    vad_manager = FakeVADManager()
    vad_state_machine = FakeVADStateMachine()
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )
    
    recorder.is_recording = True
    
    from verse.audio.capture import samples_to_wav_bytes
    empty_wav = samples_to_wav_bytes(np.zeros(10), 16000)
    recorder.stop_recording = lambda: empty_wav
    
    result = asyncio.run(orch.stop_and_respond())
    
    assert result == ""
    assert machine.state is State.IDLE


def test_stop_and_respond_discards_short_audio_restarts_auto_listening():
    vad_manager = FakeVADManager()
    vad_state_machine = FakeVADStateMachine()
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=True),
        vad=VADConfig(enabled=True)
    )
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        config=config,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )
    
    recorder.is_recording = True
    
    from verse.audio.capture import samples_to_wav_bytes
    empty_wav = samples_to_wav_bytes(np.zeros(10), 16000)
    def mock_stop():
        recorder.is_recording = False
        return empty_wav
    recorder.stop_recording = mock_stop
    
    result = asyncio.run(orch.stop_and_respond())
    
    assert result == ""
    # Should transition to LISTENING state since auto-listening restarts
    assert machine.state is State.LISTENING
    assert orch._auto_listening is True


@pytest.mark.anyio
async def test_auto_respond_with_utterance_discards_short_audio_restarts_auto_listening():
    vad_manager = FakeVADManager()
    vad_state_machine = FakeVADStateMachine()
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=True),
        vad=VADConfig(enabled=True)
    )
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        config=config,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )
    
    recorder.is_recording = True
    
    # We pass an empty list of chunks, which yields short/empty audio
    await orch._auto_respond_with_utterance([])
    
    # Should transition to LISTENING state since auto-listening restarts
    assert machine.state is State.LISTENING
    assert orch._auto_listening is True


@pytest.mark.anyio
async def test_auto_respond_with_valid_utterance_processes_and_restarts_auto_listening():
    vad_manager = FakeVADManager(available=True)
    vad_state_machine = FakeVADStateMachine()
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=True),
        vad=VADConfig(enabled=False),
    )
    stt = FakeSTT()

    orch = Orchestrator(
        stt=stt,
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        config=config,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
        play=lambda audio: None,
    )

    recorder.is_recording = True
    speech_frames = [np.ones(512, dtype=np.float32) for _ in range(20)]

    await orch._auto_respond_with_utterance(speech_frames)

    assert len(stt.calls) == 1
    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True


@pytest.mark.anyio
async def test_auto_respond_with_utterance_surfaces_pipeline_errors():
    class BrokenSTT:
        async def transcribe(self, audio, language=None):
            raise RuntimeError("STT exploded")

    events = []
    vad_manager = FakeVADManager(available=True)
    vad_state_machine = FakeVADStateMachine()
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING, error_reset_seconds=-1)
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=False),
        vad=VADConfig(enabled=True),
    )

    orch = Orchestrator(
        stt=BrokenSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        config=config,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
        play=lambda audio: None,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))

    recorder.is_recording = True
    speech_frames = [np.ones(512, dtype=np.float32) for _ in range(20)]

    await orch._auto_respond_with_utterance(speech_frames)

    error_events = [event for event in events if event[0] == "error"]
    assert error_events
    assert error_events[-1][1] == "recoverable_error"
    assert "STT exploded" in error_events[-1][2]["message"]
    assert machine.state is State.ERROR


def test_deactivate_conversation():
    vad_manager = FakeVADManager()
    vad_state_machine = FakeVADStateMachine()
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=True),
        vad=VADConfig(enabled=True)
    )

    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        config=config,
        recorder=recorder,
        vad_manager=vad_manager,
        vad_state_machine=vad_state_machine,
    )

    recorder.is_recording = True
    orch._auto_listening = True

    orch.deactivate_conversation()

    assert orch._conversation_mode_active is False
    assert orch._auto_listening is False
    assert recorder.is_recording is False
    assert machine.state is State.IDLE

