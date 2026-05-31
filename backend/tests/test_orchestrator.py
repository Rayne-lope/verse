import asyncio
import threading

from verse.config import AppConfig, IntentConfig, ToolsConfig
from verse.llm.base import LLMResponse
from verse.orchestrator import Orchestrator
from verse.state import State, StateMachine
from verse.tools.registry import Tool, ToolRegistry


class FakeSTT:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def transcribe(self, audio, language=None):
        self.calls.append((audio, language))
        return self.text


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    async def chat(self, messages, tools=None):
        self.requests.append((messages, tools))
        return self._responses.pop(0)


class FakeTTS:
    def __init__(self):
        self.spoken = []

    async def stream(self, text):
        yield text.encode()

    async def synthesize(self, text):
        self.spoken.append(text)
        return text.encode()


def _registry_with(name, handler):
    registry = ToolRegistry()
    registry.register(
        Tool(
            name=name,
            description="test tool",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    return registry


def _orchestrator(stt, llm, tts, registry, machine, **kwargs):
    played = []
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=registry,
        state_machine=machine,
        play=played.append,
        **kwargs,
    )
    return orch, played


def test_handle_audio_plain_text_response():
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("hello there")
    llm = FakeLLM([LLMResponse(text="Hi!", tool_calls=[])])
    tts = FakeTTS()
    orch, played = _orchestrator(stt, llm, tts, ToolRegistry(), machine)

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "Hi!"
    assert tts.spoken == ["Hi!"]
    assert played == [b"Hi!"]
    assert machine.state is State.IDLE


def test_handle_audio_executes_tool_then_replies():
    calls = []

    def play_music(query=None):
        calls.append(query)
        return "Playing jazz."

    registry = _registry_with("play_music", play_music)
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("play some jazz")
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "play_music", "arguments": '{"query": "jazz"}'},
    }
    llm = FakeLLM(
        [
            LLMResponse(text="", tool_calls=[tool_call]),
            LLMResponse(text="Done, playing jazz.", tool_calls=[]),
        ]
    )
    tts = FakeTTS()
    executed = []
    orch, _ = _orchestrator(
        stt, llm, tts, registry, machine, on_tool_executed=lambda n, r: executed.append((n, r))
    )

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert calls == ["jazz"]
    assert reply == "Done, playing jazz."
    assert executed == [("play_music", "Playing jazz.")]
    # second LLM request includes the tool result message
    second_messages = llm.requests[1][0]
    assert any(m.get("role") == "tool" for m in second_messages)


def test_handle_audio_uses_local_intent_before_llm():
    registry = _registry_with("get_time", lambda: "It is noon.")
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("jam berapa sekarang")
    llm = FakeLLM([])
    tts = FakeTTS()
    executed = []
    orch, played = _orchestrator(
        stt,
        llm,
        tts,
        registry,
        machine,
        config=AppConfig(tools=ToolsConfig(enabled=["get_time"])),
        on_tool_executed=lambda n, r: executed.append((n, r)),
    )

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "It is noon."
    assert llm.requests == []
    assert executed == [("get_time", "It is noon.")]
    assert tts.spoken == ["It is noon."]
    assert played == [b"It is noon."]


def test_local_intent_can_be_disabled_for_llm_fallback():
    registry = _registry_with("get_time", lambda: "It is noon.")
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("jam berapa sekarang")
    llm = FakeLLM([LLMResponse(text="LLM answer.", tool_calls=[])])
    tts = FakeTTS()
    orch, _ = _orchestrator(
        stt,
        llm,
        tts,
        registry,
        machine,
        config=AppConfig(intent=IntentConfig(local_router_enabled=False)),
    )

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "LLM answer."
    assert len(llm.requests) == 1


def test_tool_failure_is_reported_to_llm_not_raised():
    def boom():
        raise RuntimeError("spotify offline")

    registry = _registry_with("play_music", boom)
    machine = StateMachine(initial_state=State.THINKING)
    tool_call = {"id": "c1", "type": "function", "function": {"name": "play_music", "arguments": "{}"}}
    llm = FakeLLM(
        [
            LLMResponse(text="", tool_calls=[tool_call]),
            LLMResponse(text="Sorry, could not play.", tool_calls=[]),
        ]
    )
    orch, _ = _orchestrator(FakeSTT("play"), llm, FakeTTS(), registry, machine)

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "Sorry, could not play."
    tool_messages = [m for m in llm.requests[1][0] if m.get("role") == "tool"]
    assert "spotify offline" in tool_messages[0]["content"]


def test_handle_audio_failure_sets_error_state():
    class BrokenSTT:
        async def transcribe(self, audio, language=None):
            raise RuntimeError("mic dead")

    machine = StateMachine(initial_state=State.THINKING, error_reset_seconds=-1)
    orch, _ = _orchestrator(BrokenSTT(), FakeLLM([]), FakeTTS(), ToolRegistry(), machine)

    try:
        asyncio.run(orch.handle_audio(b"audio"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    assert machine.state is State.ERROR


class FakeRecorder:
    def __init__(self):
        self.is_recording = False
        self.started = 0

    def start_recording(self, on_audio_level=None):
        self.is_recording = True
        self.started += 1
        self.on_audio_level = on_audio_level

    def stop_recording(self):
        self.is_recording = False
        import numpy as np
        from verse.audio.capture import samples_to_wav_bytes
        return samples_to_wav_bytes(np.zeros(3200), 16000)


def test_start_listening_ignored_when_not_idle():
    machine = StateMachine(initial_state=State.ERROR, error_reset_seconds=-1)
    recorder = FakeRecorder()
    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )

    assert orch.start_listening() is False
    assert recorder.started == 0
    assert machine.state is State.ERROR


def test_stop_and_respond_noop_when_not_recording():
    machine = StateMachine()
    recorder = FakeRecorder()
    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )

    assert asyncio.run(orch.stop_and_respond()) == ""
    assert machine.state is State.IDLE


def test_transcript_callback_fires():
    machine = StateMachine(initial_state=State.THINKING)
    seen = []
    orch, _ = _orchestrator(
        FakeSTT("  hello  "),
        FakeLLM([LLMResponse(text="hi", tool_calls=[])]),
        FakeTTS(),
        ToolRegistry(),
        machine,
        on_transcript=seen.append,
    )

    asyncio.run(orch.handle_audio(b"audio"))
    assert seen == ["hello"]


def test_conversation_mode_auto_listens_after_speak():
    from verse.config import AppConfig, VADConfig

    machine = StateMachine(initial_state=State.THINKING)
    recorder = FakeRecorder()
    stt = FakeSTT("x")
    llm = FakeLLM([])
    tts = FakeTTS()
    
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
        config=AppConfig(vad=VADConfig(enabled=False)),
    )
    
    # Conversation mode is active (as if toggled on via start_auto_listening).
    orch._conversation_mode_active = True
    asyncio.run(orch._speak("hello"))

    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True


def test_request_barge_in_interrupts_speaking_and_starts_listening():
    machine = StateMachine(initial_state=State.SPEAKING)
    recorder = FakeRecorder()
    events = []
    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
        play=lambda audio: None,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    orch._playback_stop_event = threading.Event()

    assert orch.request_barge_in() is True

    assert orch._playback_stop_event.is_set()
    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert ("tts", "interrupted", {}) in events


def test_barge_in_preserves_conversation_auto_listening():
    from verse.config import VADConfig

    machine = StateMachine(initial_state=State.SPEAKING)
    recorder = FakeRecorder()
    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
        config=AppConfig(vad=VADConfig(enabled=False)),
        play=lambda audio: None,
    )
    orch._conversation_mode_active = True
    orch._playback_stop_event = threading.Event()

    assert orch.request_barge_in() is True

    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True
    assert orch.conversation_mode_active is True


def test_speak_interruption_does_not_emit_completed_event():
    machine = StateMachine(initial_state=State.THINKING)
    recorder = FakeRecorder()
    events = []

    def interrupting_play(audio, *, on_audio_level=None, stop_event=None):
        assert stop_event is not None
        stop_event.set()

    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
        play=interrupting_play,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))

    asyncio.run(orch._speak("hello"))

    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert ("tts", "interrupted", {}) in events
    assert ("tts", "completed", {}) not in events


def test_conversation_mode_silence_detection_triggers_response():
    import time
    machine = StateMachine(initial_state=State.LISTENING)
    recorder = FakeRecorder()
    stt = FakeSTT("test")
    llm = FakeLLM([LLMResponse(text="response", tool_calls=[])])
    tts = FakeTTS()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )
    
    from verse.config import AppConfig, HotkeyConfig, VADConfig
    orch.config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=False),
        vad=VADConfig(enabled=False)
    )
    recorder.is_recording = True
    orch._loop = loop
    orch._auto_listening = True
    orch._speech_detected = False
    orch._last_speech_time = 0.0
    
    orch._handle_audio_level(0.1)
    assert orch._speech_detected is True
    
    orch._last_speech_time = time.time() - 2.0
    orch._handle_audio_level(0.01)
    
    async def run_brief():
        await asyncio.sleep(0.1)
        
    loop.run_until_complete(run_brief())
    
    assert orch._auto_listening is False
    assert tts.spoken == ["response."]
    assert machine.state is State.IDLE
    loop.close()


def test_conversation_mode_timeout_returns_to_idle():
    import time
    machine = StateMachine(initial_state=State.LISTENING)
    recorder = FakeRecorder()
    stt = FakeSTT("x")
    llm = FakeLLM([])
    tts = FakeTTS()
    
    loop = asyncio.new_event_loop()
    
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )
    
    from verse.config import AppConfig, HotkeyConfig, VADConfig
    orch.config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=False),
        vad=VADConfig(enabled=False)
    )
    recorder.is_recording = True
    orch._loop = loop
    orch._auto_listening = True
    orch._speech_detected = False
    orch._auto_listen_start_real_time = time.time() - 6.0
    
    orch._handle_audio_level(0.01)
    
    async def run_brief():
        await asyncio.sleep(0.1)
        
    loop.run_until_complete(run_brief())
    
    assert orch._auto_listening is False
    assert recorder.is_recording is False
    assert machine.state is State.IDLE
    loop.close()


def test_clean_markdown_for_tts():
    orch = Orchestrator(
        stt=FakeSTT(""),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=StateMachine(),
    )
    
    input_text = "Berikut beberapa catatan Anda:\n* **Belanja**: Beli susu\n* **Kerja**: Kirim email ke Rayne"
    cleaned = orch._clean_markdown_for_tts(input_text)
    
    # Expected output should have clean text and correct pauses
    assert "Berikut beberapa catatan Anda:" in cleaned
    assert "Belanja: Beli susu." in cleaned
    assert "Kerja: Kirim email ke Rayne." in cleaned
    assert "*" not in cleaned
    assert "**" not in cleaned


def test_conversational_local_intent_replies(monkeypatch):
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="set_volume",
            description="set volume",
            parameters={"type": "object", "properties": {"level": {"type": "integer"}}},
            handler=lambda level: f"System volume set to {level}%.",
        )
    )
    
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("kecilin volume")
    llm = FakeLLM([])
    tts = FakeTTS()
    
    orch, played = _orchestrator(
        stt,
        llm,
        tts,
        registry,
        machine,
        config=AppConfig(tools=ToolsConfig(enabled=["set_volume"])),
    )
    
    reply = asyncio.run(orch.handle_audio(b"audio"))
    
    # Verify that the reply is in friendly Indonesian instead of raw "System volume set to 25%."
    assert "diatur ke 25%" in reply
    assert "Rafi" in reply
    assert tts.spoken == [reply + "."]
    assert played == [(reply + ".").encode()]
