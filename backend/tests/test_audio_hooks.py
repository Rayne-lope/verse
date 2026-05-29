import asyncio
import numpy as np
import pytest
from unittest.mock import MagicMock

from verse.config import AppConfig
from verse.orchestrator import Orchestrator
from verse.state import StateMachine
from verse.audio.capture import AudioRecorder


class FakeSTT:
    async def transcribe(self, audio, language=None):
        return "fake transcript"


class FakeLLM:
    async def chat(self, messages, tools=None):
        from verse.llm.base import LLMResponse
        return LLMResponse(text="fake reply", tool_calls=[])


class FakeTTS:
    async def synthesize(self, text):
        return text.encode()


def test_audio_recorder_pre_vad_audio_hook():
    """Verify pre_vad_audio_hook modifies incoming sounddevice chunks before queueing and appending."""
    # A hook that doubles the amplitude of all samples
    def double_amplitude(chunk):
        return chunk * 2.0

    recorder = AudioRecorder(pre_vad_audio_hook=double_amplitude)
    
    # Manually trigger the sounddevice callback
    indata = np.ones((512, 1), dtype=np.float32)
    recorder._recording = True
    recorder._chunks = []
    
    # We don't have an active event loop here, but _on_audio should still call the hook and append
    recorder._on_audio(indata, 512, None, status=None)
    
    assert len(recorder._chunks) == 1
    # Check that hook modified the appended chunk
    np.testing.assert_array_equal(recorder._chunks[0], np.ones((512, 1), dtype=np.float32) * 2.0)


def test_audio_recorder_post_recording_audio_hook():
    """Verify post_recording_audio_hook modifies consolidated samples inside stop_recording."""
    # A hook that sets all consolidated samples to 0.5
    def fill_half(samples):
        return np.ones_like(samples) * 0.5

    recorder = AudioRecorder(post_recording_audio_hook=fill_half)
    recorder._recording = True
    # Populate chunks with dummy data
    recorder._chunks = [np.ones((10, 1), dtype=np.float32)]
    
    # We mock out _stream to avoid sounddevice runtime issues in test
    recorder._stream = MagicMock()
    
    wav_bytes = recorder.stop_recording()
    
    # Decode wav to verify samples were modified by hook
    import io
    import soundfile as sf
    with sf.SoundFile(io.BytesIO(wav_bytes)) as f:
        samples = f.read()
        np.testing.assert_array_equal(samples, np.ones(10, dtype=np.float32) * 0.5)


def test_audio_recorder_clean_for_stt():
    """Verify clean_for_stt modifies the final WAV bytes output from stop_recording."""
    # A hook that appends custom suffix bytes to the wav data
    def append_suffix(wav_data):
        return wav_data + b"HOOK_SUFFIX"

    recorder = AudioRecorder(clean_for_stt=append_suffix)
    recorder._recording = True
    recorder._chunks = [np.zeros((10, 1), dtype=np.float32)]
    recorder._stream = MagicMock()
    
    wav_bytes = recorder.stop_recording()
    assert wav_bytes.endswith(b"HOOK_SUFFIX")


def test_orchestrator_passes_hooks_to_recorder():
    """Verify Orchestrator successfully configures hooks on the injected recorder."""
    pre_hook = lambda chunk: chunk
    post_hook = lambda samples: samples
    stt_hook = lambda wav: wav

    recorder = AudioRecorder()
    
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=StateMachine(),
        recorder=recorder,
        pre_vad_audio_hook=pre_hook,
        post_recording_audio_hook=post_hook,
        clean_for_stt=stt_hook,
    )
    
    assert orch.pre_vad_audio_hook is pre_hook
    assert orch.post_recording_audio_hook is post_hook
    assert orch.clean_for_stt is stt_hook
    
    # Verify the hooks were propagated down to the recorder
    assert recorder.pre_vad_audio_hook is pre_hook
    assert recorder.post_recording_audio_hook is post_hook
    assert recorder.clean_for_stt is stt_hook
