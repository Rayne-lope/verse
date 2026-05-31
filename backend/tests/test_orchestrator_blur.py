import pytest
from unittest.mock import MagicMock
from verse.config import AppConfig
from verse.orchestrator import Orchestrator
from verse.state import State, StateMachine
from verse.llm.base import LLMResponse


class FakeRecorder:
    def __init__(self):
        self.is_recording = False

    def stop_recording(self):
        self.is_recording = False
        return b"wav"


class FakeSTT:
    async def transcribe(self, audio, language=None):
        return "hi"


class FakeLLM:
    async def chat(self, messages, tools=None):
        return LLMResponse(text="reply", tool_calls=[])


class FakeTTS:
    async def synthesize(self, text):
        return b"audio"


def test_deactivate_conversation_while_listening_forces_idle():
    machine = StateMachine(initial_state=State.LISTENING)
    recorder = FakeRecorder()
    recorder.is_recording = True

    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        recorder=recorder,
    )
    orch._auto_listening = True
    orch._conversation_mode_active = True

    orch.deactivate_conversation()

    assert orch._conversation_mode_active is False
    assert orch._auto_listening is False
    assert recorder.is_recording is False
    assert machine.state is State.IDLE


def test_deactivate_conversation_while_thinking_does_not_force_idle():
    machine = StateMachine(initial_state=State.THINKING)
    recorder = FakeRecorder()

    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        recorder=recorder,
    )
    orch._auto_listening = True
    orch._conversation_mode_active = True

    orch.deactivate_conversation()

    # Conversation tracking flags should be disabled to prevent re-arming
    assert orch._conversation_mode_active is False
    assert orch._auto_listening is False
    # But State remains THINKING so that active turn completes naturally
    assert machine.state is State.THINKING


def test_deactivate_conversation_while_speaking_does_not_force_idle():
    machine = StateMachine(initial_state=State.SPEAKING)
    recorder = FakeRecorder()

    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM(),
        tts=FakeTTS(),
        registry=MagicMock(),
        state_machine=machine,
        recorder=recorder,
    )
    orch._auto_listening = True
    orch._conversation_mode_active = True

    orch.deactivate_conversation()

    # Conversation tracking flags should be disabled to prevent re-arming
    assert orch._conversation_mode_active is False
    assert orch._auto_listening is False
    # But State remains SPEAKING so that active turn completes naturally
    assert machine.state is State.SPEAKING
