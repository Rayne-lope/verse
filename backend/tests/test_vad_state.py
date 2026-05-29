import numpy as np
import pytest

from verse.config import VADConfig
from verse.audio.vad import VADEndpointingStateMachine, VADState


def test_vad_state_machine_initial_state():
    sm = VADEndpointingStateMachine()
    assert sm.state is VADState.WAITING_FOR_SPEECH
    assert sm.elapsed_ms == 0.0


def test_vad_state_machine_timeout():
    config = VADConfig(followup_timeout_s=0.1)  # 100ms timeout
    sm = VADEndpointingStateMachine(config)
    
    # 3 frames (96ms)
    for _ in range(3):
        state, _ = sm.process_frame(np.zeros(512), 0.1)
        assert state is VADState.WAITING_FOR_SPEECH
        
    # 4th frame (128ms) -> exceeds 100ms timeout
    state, _ = sm.process_frame(np.zeros(512), 0.1)
    assert state is VADState.TIMEOUT


def test_vad_state_machine_debounce_and_speech_activation():
    config = VADConfig(speech_start_ms=96, pre_roll_ms=96)  # ~3 frames speech_start
    sm = VADEndpointingStateMachine(config)
    
    # 1. Single high-prob frame (32ms) followed by low-prob -> should not activate speech (debounce)
    state, _ = sm.process_frame(np.ones(512) * 0.1, 0.8)
    assert state is VADState.WAITING_FOR_SPEECH
    
    state, _ = sm.process_frame(np.ones(512) * 0.2, 0.1)
    assert state is VADState.WAITING_FOR_SPEECH
    assert sm._consecutive_speech_frames == 0
    
    # 2. Three consecutive high-prob frames -> triggers SPEECH_ACTIVE (96ms)
    state, _ = sm.process_frame(np.ones(512) * 0.3, 0.8)
    assert state is VADState.WAITING_FOR_SPEECH
    state, _ = sm.process_frame(np.ones(512) * 0.4, 0.8)
    assert state is VADState.WAITING_FOR_SPEECH
    
    state, _ = sm.process_frame(np.ones(512) * 0.5, 0.8)
    assert state is VADState.SPEECH_ACTIVE
    
    # Verify pre-roll buffer was preloaded into speech_frames
    # It should contain: [0.3 chunk, 0.4 chunk, 0.5 chunk] (deque size is 3)
    assert len(sm._speech_frames) == 3
    assert np.all(sm._speech_frames[0] == 0.3)
    assert np.all(sm._speech_frames[1] == 0.4)
    assert np.all(sm._speech_frames[2] == 0.5)


def test_vad_state_machine_silence_detection():
    config = VADConfig(
        speech_start_ms=32,    # 1 frame
        pre_roll_ms=32,        # 1 frame
        end_silence_ms=64,     # 2 frames
        min_utterance_ms=96,   # 3 frames
    )
    sm = VADEndpointingStateMachine(config)
    
    # Start speech
    state, _ = sm.process_frame(np.ones(512) * 0.5, 0.8)
    assert state is VADState.SPEECH_ACTIVE
    
    # Speech continues
    state, _ = sm.process_frame(np.ones(512) * 0.6, 0.8)
    assert state is VADState.SPEECH_ACTIVE
    
    # Silence starts: Frame 1 (32ms silence)
    state, _ = sm.process_frame(np.ones(512) * 0.7, 0.1)
    assert state is VADState.SPEECH_ACTIVE
    
    # Silence ends: Frame 2 (64ms silence) -> triggers ENDED because speech duration is 4 frames * 32 = 128ms (>= 96ms min)
    state, utterance = sm.process_frame(np.ones(512) * 0.8, 0.1)
    assert state is VADState.ENDED
    assert utterance is not None
    assert len(utterance) == 4
    assert np.all(utterance[3] == 0.8)


def test_vad_state_machine_discard_short_noise():
    config = VADConfig(
        speech_start_ms=32,     # 1 frame
        pre_roll_ms=32,         # 1 frame
        end_silence_ms=64,      # 2 frames
        min_utterance_ms=200,   # > 6 frames required
    )
    sm = VADEndpointingStateMachine(config)
    
    # Start speech
    state, _ = sm.process_frame(np.ones(512) * 0.5, 0.8)
    assert state is VADState.SPEECH_ACTIVE
    
    # Silence starts
    state, _ = sm.process_frame(np.ones(512) * 0.6, 0.1)
    state, _ = sm.process_frame(np.ones(512) * 0.7, 0.1)
    
    # Since total speech was only 3 frames (96ms), which is < 200ms min, VAD should reset to WAITING_FOR_SPEECH
    assert state is VADState.WAITING_FOR_SPEECH
    assert len(sm._speech_frames) == 0


def test_vad_state_machine_max_utterance():
    config = VADConfig(
        speech_start_ms=32,
        pre_roll_ms=32,
        max_utterance_ms=96,  # 3 frames max duration
    )
    sm = VADEndpointingStateMachine(config)
    
    # Start speech
    state, _ = sm.process_frame(np.ones(512) * 0.5, 0.8)
    assert state is VADState.SPEECH_ACTIVE
    
    # Frame 2
    state, _ = sm.process_frame(np.ones(512) * 0.6, 0.8)
    assert state is VADState.SPEECH_ACTIVE
    
    # Frame 3 -> triggers max utterance limit ENDED
    state, utterance = sm.process_frame(np.ones(512) * 0.7, 0.8)
    assert state is VADState.ENDED
    assert len(utterance) == 3


def test_vad_state_machine_reset():
    sm = VADEndpointingStateMachine()
    sm.process_frame(np.ones(512), 0.8)
    
    sm.reset()
    assert sm.state is VADState.WAITING_FOR_SPEECH
    assert sm.elapsed_ms == 0.0
    assert len(sm._speech_frames) == 0
    assert len(sm._pre_roll) == 0
