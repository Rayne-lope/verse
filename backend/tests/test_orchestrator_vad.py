import asyncio
import numpy as np
import pytest
from unittest.mock import MagicMock

from pathlib import Path

from verse.config import AppConfig, VADConfig, HotkeyConfig
from verse.orchestrator import Orchestrator
from verse.state import State, StateMachine
from verse.audio.vad import VADState, VAD_WINDOW_SAMPLES, VAD_FRAME_MS
from verse.llm.base import LLMResponse
from verse.tools.registry import ToolRegistry


class FakeVADManager:
    def __init__(self, available=True, probability=0.8):
        self._available = available
        self.probability = probability
        self.reset_called = 0
        self.predictions = []

    @property
    def is_available(self):
        return self._available

    def reset(self):
        self.reset_called += 1

    def predict(self, frame):
        self.predictions.append(frame)
        return self.probability


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
    events = []
    
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
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    
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
    assert not [event for event in events if event[1].startswith("rms_")]


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
    timeout_events = [event for event in events if event[0] == "vad" and event[1] == "timeout"]
    assert timeout_events
    assert timeout_events[-1][2]["rms_fallback_armed"] is False


@pytest.mark.anyio
async def test_run_vad_loop_reframes_non_512_blocks():
    """Device blocks that aren't exactly VAD_WINDOW_SAMPLES (e.g. a 48kHz mic
    resampled to 16kHz) must be reframed into fixed-size frames, not dropped.
    Regression for conversation mode never endpointing ("orb grows but terminal
    silent")."""
    loop = asyncio.get_running_loop()

    vad_manager = FakeVADManager(available=True)
    fake_speech_frames = [np.ones(512, dtype=np.float32)]
    vad_state_machine = FakeVADStateMachine([
        (VADState.WAITING_FOR_SPEECH, None),
        (VADState.SPEECH_ACTIVE, None),
        (VADState.ENDED, fake_speech_frames),
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

    # Mismatched block sizes (480/1024/512) -> reframer must yield exact frames.
    await recorder._queue.put(np.ones((480, 1), dtype=np.float32))
    await recorder._queue.put(np.ones((1024, 1), dtype=np.float32))
    await recorder._queue.put(np.ones((512, 1), dtype=np.float32))

    task = loop.create_task(orch._run_vad_loop())
    orch._vad_task = task
    await asyncio.wait_for(task, timeout=2.0)

    # Frames must have reached the VAD (old code dropped every mismatched block)...
    assert vad_state_machine.frames_processed, "blocks were dropped, not reframed"
    # ...and every frame handed to the VAD must be exactly VAD_WINDOW_SAMPLES.
    assert all(len(frame) == VAD_WINDOW_SAMPLES for frame, _ in vad_state_machine.frames_processed)
    # Endpointed correctly.
    assert orch._auto_listening is False
    assert recorder.is_recording is False
    assert machine.state is State.IDLE


@pytest.mark.anyio
async def test_run_vad_loop_rms_fallback_processes_silero_blind_speech():
    loop = asyncio.get_running_loop()
    high = np.ones((VAD_WINDOW_SAMPLES, 1), dtype=np.float32) * 0.1
    silence = np.zeros((VAD_WINDOW_SAMPLES, 1), dtype=np.float32)
    events = []

    vad_manager = FakeVADManager(available=True, probability=0.01)
    vad_state_machine = FakeVADStateMachine()
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    stt = FakeSTT()
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=True),
        vad=VADConfig(
            enabled=True,
            speech_start_ms=32,
            min_utterance_ms=96,
            end_silence_ms=32,
            pre_roll_ms=32,
            followup_timeout_s=10.0,
            rms_fallback_enabled=True,
            rms_start_level=0.03,
            rms_end_level=0.02,
        ),
    )

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
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    orch._loop = loop
    orch._auto_listening = True
    orch._conversation_mode_active = True
    recorder.is_recording = True

    for _ in range(12):
        await recorder._queue.put(high)
    for _ in range(3):
        await recorder._queue.put(silence)

    task = loop.create_task(orch._run_vad_loop())
    orch._vad_task = task
    await asyncio.wait_for(task, timeout=2.0)

    assert len(stt.calls) == 1
    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True
    assert ("vad", "rms_speech_started") in [(stage, event) for stage, event, _ in events]
    assert ("vad", "rms_speech_ended") in [(stage, event) for stage, event, _ in events]
    assert not [event for event in events if event[1] == "speech_started"]
    orch._cancel_vad_task()


@pytest.mark.anyio
async def test_run_vad_loop_silent_timeout_rearms_conversation(capsys):
    loop = asyncio.get_running_loop()
    frame_silence = np.zeros((VAD_WINDOW_SAMPLES, 1), dtype=np.float32)
    events = []

    vad_manager = FakeVADManager(available=True, probability=0.01)
    vad_state_machine = FakeVADStateMachine([
        (VADState.TIMEOUT, None),
    ])
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=True),
        vad=VADConfig(enabled=True, rms_fallback_enabled=True),
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
        play=lambda audio: None,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    orch._loop = loop
    orch._auto_listening = True
    orch._conversation_mode_active = True
    recorder.is_recording = True

    await recorder._queue.put(frame_silence)
    task = loop.create_task(orch._run_vad_loop())
    orch._vad_task = task
    await asyncio.wait_for(task, timeout=2.0)

    output = capsys.readouterr().out
    assert "Still listening..." in output
    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True
    timeout_events = [event for event in events if event[0] == "vad" and event[1] == "timeout"]
    assert timeout_events[-1][2]["rms_fallback_armed"] is False
    orch._cancel_vad_task()


@pytest.mark.anyio
async def test_run_vad_loop_short_rms_noise_discards_and_rearms():
    from verse.audio.vad import VADEndpointingStateMachine

    loop = asyncio.get_running_loop()
    high = np.ones((VAD_WINDOW_SAMPLES, 1), dtype=np.float32) * 0.1
    silence = np.zeros((VAD_WINDOW_SAMPLES, 1), dtype=np.float32)
    events = []
    stt = FakeSTT()
    config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=True),
        vad=VADConfig(
            enabled=True,
            speech_start_ms=16,
            min_utterance_ms=500,
            end_silence_ms=32,
            followup_timeout_s=0.25,
            rms_fallback_enabled=True,
            rms_start_level=0.03,
            rms_end_level=0.02,
        ),
    )

    vad_manager = FakeVADManager(available=True, probability=0.01)
    vad_state_machine = VADEndpointingStateMachine(config.vad)
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.LISTENING)

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
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    orch._loop = loop
    orch._auto_listening = True
    orch._conversation_mode_active = True
    recorder.is_recording = True

    await recorder._queue.put(high)
    for _ in range(24):
        await recorder._queue.put(silence)

    task = loop.create_task(orch._run_vad_loop())
    orch._vad_task = task
    await asyncio.wait_for(task, timeout=2.0)

    assert stt.calls == []
    assert ("vad", "rms_speech_discarded") in [(stage, event) for stage, event, _ in events]
    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True
    orch._cancel_vad_task()


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
    orch._conversation_mode_active = True

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
    orch._conversation_mode_active = True

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
    orch._conversation_mode_active = True
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


def test_predict_window_guard_accepts_256_rejects_512():
    """The model expects VAD_WINDOW_SAMPLES windows. predict() must run inference
    for a correctly-sized frame and reject other sizes -- a 512-sample frame
    silently returns ~0 from this ONNX build, so the size guard short-circuits it
    to 0.0 without ever touching the model."""
    from verse.audio.vad import SileroVADManager

    mgr = SileroVADManager.__new__(SileroVADManager)
    mgr._state = np.zeros((2, 1, 128), dtype=np.float32)
    mgr.session = MagicMock()
    mgr.session.run.return_value = (
        np.array([[0.73]], dtype=np.float32),
        np.zeros((2, 1, 128), dtype=np.float32),
    )

    # Correct window size -> inference runs, real probability flows through.
    prob = mgr.predict(np.zeros(VAD_WINDOW_SAMPLES, dtype=np.float32))
    assert isinstance(prob, float)
    assert prob == pytest.approx(0.73, abs=1e-4)
    mgr.session.run.assert_called_once()

    # Wrong window size (512) -> guard returns 0.0, model is not called again.
    assert mgr.predict(np.zeros(512, dtype=np.float32)) == 0.0
    mgr.session.run.assert_called_once()


def test_endpointing_speech_start_timing_uses_16ms_frames():
    """SPEECH_ACTIVE must trigger after exactly speech_start_ms of speech, proving
    the state machine counts 16ms (256-sample) frames rather than 32ms ones. With
    speech_start_ms=160 that is 10 frames; the 9th must still be waiting."""
    from verse.audio.vad import VADEndpointingStateMachine
    from verse.config import VADConfig

    config = VADConfig(start_threshold=0.55, speech_start_ms=160)
    sm = VADEndpointingStateMachine(config)
    frame = np.zeros(VAD_WINDOW_SAMPLES, dtype=np.float32)

    frames_needed = config.speech_start_ms // VAD_FRAME_MS  # 160 // 16 == 10

    for _ in range(frames_needed - 1):
        state, _ = sm.process_frame(frame, 0.9)
        assert state is VADState.WAITING_FOR_SPEECH

    state, _ = sm.process_frame(frame, 0.9)
    assert state is VADState.SPEECH_ACTIVE
