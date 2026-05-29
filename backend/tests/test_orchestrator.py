import asyncio

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
        return b"audio"


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
    )
    
    asyncio.run(orch._speak("hello"))
    
    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True


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

