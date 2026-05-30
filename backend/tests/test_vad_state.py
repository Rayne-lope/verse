import numpy as np
import pytest

from verse.config import VADConfig
from verse.audio.vad import VADEndpointingStateMachine, VADState, VAD_WINDOW_SAMPLES, VAD_FRAME_MS


def test_vad_state_machine_initial_state():
    sm = VADEndpointingStateMachine()
    assert sm.state is VADState.WAITING_FOR_SPEECH
    assert sm.elapsed_ms == 0.0


def test_vad_state_machine_timeout():
    config = VADConfig(followup_timeout_s=0.1)  # 100ms timeout
    sm = VADEndpointingStateMachine(config)

    # Frames that stay just under the timeout remain WAITING (6 * 16ms = 96ms).
    waiting_frames = (100 - 1) // VAD_FRAME_MS
    for _ in range(waiting_frames):
        state, _ = sm.process_frame(np.zeros(VAD_WINDOW_SAMPLES), 0.1)
        assert state is VADState.WAITING_FOR_SPEECH

    # Next frame crosses 100ms -> TIMEOUT.
    state, _ = sm.process_frame(np.zeros(VAD_WINDOW_SAMPLES), 0.1)
    assert state is VADState.TIMEOUT


def test_vad_state_machine_debounce_and_speech_activation():
    config = VADConfig(speech_start_ms=3 * VAD_FRAME_MS, pre_roll_ms=3 * VAD_FRAME_MS)  # 3 frames speech_start
    sm = VADEndpointingStateMachine(config)

    # 1. Single high-prob frame (16ms) followed by low-prob -> should not activate speech (debounce)
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.1, 0.8)
    assert state is VADState.WAITING_FOR_SPEECH

    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.2, 0.1)
    assert state is VADState.WAITING_FOR_SPEECH
    assert sm._consecutive_speech_frames == 0

    # 2. Three consecutive high-prob frames -> triggers SPEECH_ACTIVE (48ms)
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.3, 0.8)
    assert state is VADState.WAITING_FOR_SPEECH
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.4, 0.8)
    assert state is VADState.WAITING_FOR_SPEECH

    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.5, 0.8)
    assert state is VADState.SPEECH_ACTIVE
    
    # Verify pre-roll buffer was preloaded into speech_frames
    # It should contain: [0.3 chunk, 0.4 chunk, 0.5 chunk] (deque size is 3)
    assert len(sm._speech_frames) == 3
    assert np.all(sm._speech_frames[0] == 0.3)
    assert np.all(sm._speech_frames[1] == 0.4)
    assert np.all(sm._speech_frames[2] == 0.5)


def test_vad_state_machine_silence_detection():
    config = VADConfig(
        speech_start_ms=1 * VAD_FRAME_MS,    # 1 frame
        pre_roll_ms=1 * VAD_FRAME_MS,        # 1 frame
        end_silence_ms=2 * VAD_FRAME_MS,     # 2 frames
        min_utterance_ms=3 * VAD_FRAME_MS,   # 3 frames
    )
    sm = VADEndpointingStateMachine(config)

    # Start speech
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.5, 0.8)
    assert state is VADState.SPEECH_ACTIVE

    # Speech continues
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.6, 0.8)
    assert state is VADState.SPEECH_ACTIVE

    # Silence starts: Frame 1 (16ms silence)
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.7, 0.1)
    assert state is VADState.SPEECH_ACTIVE

    # Silence ends: Frame 2 (32ms silence) -> ENDED, speech duration is 4 frames * 16 = 64ms (>= 48ms min)
    state, utterance = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.8, 0.1)
    assert state is VADState.ENDED
    assert utterance is not None
    assert len(utterance) == 4
    assert np.all(utterance[3] == 0.8)


def test_vad_state_machine_discard_short_noise():
    config = VADConfig(
        speech_start_ms=1 * VAD_FRAME_MS,     # 1 frame
        pre_roll_ms=1 * VAD_FRAME_MS,         # 1 frame
        end_silence_ms=2 * VAD_FRAME_MS,      # 2 frames
        min_utterance_ms=200,                 # far longer than the noise burst
    )
    sm = VADEndpointingStateMachine(config)

    # Start speech
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.5, 0.8)
    assert state is VADState.SPEECH_ACTIVE

    # Silence starts
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.6, 0.1)
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.7, 0.1)

    # Total speech was only 3 frames (48ms), which is < 200ms min, so VAD resets to WAITING_FOR_SPEECH
    assert state is VADState.WAITING_FOR_SPEECH
    assert len(sm._speech_frames) == 0


def test_vad_state_machine_max_utterance():
    config = VADConfig(
        speech_start_ms=1 * VAD_FRAME_MS,
        pre_roll_ms=1 * VAD_FRAME_MS,
        max_utterance_ms=3 * VAD_FRAME_MS,  # 3 frames max duration
    )
    sm = VADEndpointingStateMachine(config)

    # Start speech
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.5, 0.8)
    assert state is VADState.SPEECH_ACTIVE

    # Frame 2
    state, _ = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.6, 0.8)
    assert state is VADState.SPEECH_ACTIVE

    # Frame 3 -> triggers max utterance limit ENDED
    state, utterance = sm.process_frame(np.ones(VAD_WINDOW_SAMPLES) * 0.7, 0.8)
    assert state is VADState.ENDED
    assert len(utterance) == 3


def test_vad_state_machine_reset():
    sm = VADEndpointingStateMachine()
    sm.process_frame(np.ones(VAD_WINDOW_SAMPLES), 0.8)
    
    sm.reset()
    assert sm.state is VADState.WAITING_FOR_SPEECH
    assert sm.elapsed_ms == 0.0
    assert len(sm._speech_frames) == 0
    assert len(sm._pre_roll) == 0
