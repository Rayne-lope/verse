import asyncio
import contextlib
import threading
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from verse.config import AppConfig
from verse.intent.turn import TurnContext
from verse.orchestrator import Orchestrator, CANNED_ACKNOWLEDGEMENTS
from verse.state import State, StateMachine
from verse.tools.registry import Tool, ToolRegistry
from verse.tts.base import RealtimeTTSAdapter, TTSAdapter
from verse.llm.base import LLMResponse, LLMStreamEvent


class FakeRealtimeTTS(TTSAdapter, RealtimeTTSAdapter):
    def __init__(self):
        self.spoken = []

    async def stream(self, text):
        yield text.encode()

    async def stream_pcm(self, text):
        self.spoken.append(text)
        yield b"\x00\x00" * 100


class FakeSTT:
    async def transcribe(self, audio, language=None):
        return "hello"


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


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def chat(self, messages, tools=None):
        self.requests.append((messages, tools))
        return self.responses.pop(0)


class FakeStreamingLLM:
    def __init__(self, streams):
        self.streams = list(streams)
        self.requests = []

    async def chat(self, messages, tools=None):
        raise AssertionError("streaming test should use stream_chat")

    async def stream_chat(self, messages, tools=None):
        self.requests.append((messages, tools))
        for item in self.streams.pop(0):
            if isinstance(item, float):
                await asyncio.sleep(item)
                continue
            yield item


@pytest.fixture
def mock_sd_output_stream(monkeypatch):
    class FakeOutputStream:
        def __init__(self, **kwargs):
            self.active = True
        def start(self):
            pass
        def stop(self):
            self.active = False
        def close(self):
            self.active = False

    monkeypatch.setattr("verse.audio.streaming_player.sd.OutputStream", FakeOutputStream)


@pytest.mark.anyio
async def test_turn_context_cancellation_player(mock_sd_output_stream):
    turn = TurnContext(id="turn_test")
    assert not turn.is_cancelled()
    
    player_mock = MagicMock()
    player_mock.clear = AsyncMock()
    turn.playback = player_mock
    
    turn.cancel()
    assert turn.is_cancelled()
    
    await asyncio.sleep(0.01)
    player_mock.clear.assert_called_once()


@pytest.mark.anyio
async def test_turn_context_cancels_registered_tasks_and_stop_event(mock_sd_output_stream):
    async def wait_forever():
        await asyncio.Event().wait()

    turn = TurnContext(id="turn_tasks")
    stop_event = threading.Event()
    llm_task = asyncio.create_task(wait_forever())
    tts_task = asyncio.create_task(wait_forever())
    tool_task = asyncio.create_task(wait_forever())
    turn.playback_stop_event = stop_event
    turn.llm_task = llm_task
    turn.tts_task = tts_task
    turn.tool_tasks.add(tool_task)

    turn.cancel("barge_in")

    assert turn.is_cancelled()
    assert turn.metadata["cancel_reason"] == "barge_in"
    assert stop_event.is_set()
    assert llm_task.cancelled() or llm_task.cancelling()
    assert tts_task.cancelled() or tts_task.cancelling()
    assert tool_task.cancelled() or tool_task.cancelling()

    for task in (llm_task, tts_task, tool_task):
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.anyio
async def test_speak_text_immediately_realtime(mock_sd_output_stream):
    machine = StateMachine(initial_state=State.THINKING)
    tts = FakeRealtimeTTS()
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM([]),
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
    )
    
    turn = TurnContext(id="test_turn")
    orch._current_turn = turn
    await orch.speak_text_immediately(turn, "Halo apa kabar")
    
    assert tts.spoken == ["Halo apa kabar."]
    assert machine.state is State.IDLE


@pytest.mark.anyio
async def test_speak_streaming_realtime(mock_sd_output_stream):
    machine = StateMachine(initial_state=State.THINKING)
    tts = FakeRealtimeTTS()
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM([]),
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
    )
    
    async def text_stream():
        yield "Halo"
        yield " ini adalah segmen yang cukup panjang,"
        yield " sisa kata."
        
    turn = TurnContext(id="test_turn")
    orch._current_turn = turn
    await orch.speak_streaming(turn, text_stream())
    
    assert len(tts.spoken) >= 1
    assert any("Halo" in s for s in tts.spoken)
    assert machine.state is State.IDLE


@pytest.mark.anyio
async def test_canned_acknowledgement_triggers_on_slow_tool(mock_sd_output_stream):
    called = []
    
    def slow_search(query=None):
        called.append(query)
        return "Hasil pencarian: Verse mac app."
        
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="web_search",
            description="slow web search tool",
            parameters={"type": "object", "properties": {"query": {"type": "string"}}},
            handler=slow_search,
        )
    )
    
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT()
    tool_call = {
        "id": "call_search",
        "type": "function",
        "function": {"name": "web_search", "arguments": '{"query": "Verse mac"}'},
    }
    llm = FakeLLM([
        LLMResponse(text="", tool_calls=[tool_call]),
        LLMResponse(text="Ini infonya: Verse mac app.", tool_calls=[]),
    ])
    tts = FakeRealtimeTTS()
    
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=registry,
        state_machine=machine,
    )
    
    turn = TurnContext(id="test_slow_turn")
    orch._current_turn = turn
    
    reply = await orch.handle_audio(b"audio")
    
    assert "Bentar, aku cari dulu." in tts.spoken
    assert "Ini infonya: Verse mac app." in tts.spoken
    assert reply == "Ini infonya: Verse mac app."
    assert called == ["Verse mac"]
    assert machine.state is State.IDLE


@pytest.mark.anyio
async def test_handle_audio_streams_llm_text_to_ui_and_tts_before_done(mock_sd_output_stream):
    machine = StateMachine(initial_state=State.THINKING)
    marks = []
    assistant_updates = []
    llm = FakeStreamingLLM(
        [
            [
                LLMStreamEvent(type="text_delta", text="Halo."),
                0.05,
                LLMStreamEvent(type="text_delta", text=" Lanjut."),
                LLMStreamEvent(type="done"),
            ]
        ]
    )
    tts = FakeRealtimeTTS()
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
        on_assistant_text=assistant_updates.append,
    )
    original_mark = orch._latency_mark

    def record_mark(name, **data):
        marks.append(name)
        original_mark(name, **data)

    orch._latency_mark = record_mark

    reply = await orch.handle_audio(b"audio")

    assert reply == "Halo. Lanjut."
    assert assistant_updates == ["Halo.", "Halo. Lanjut."]
    assert any("Halo" in text for text in tts.spoken)
    assert marks.index("tts_first_audio") < marks.index("llm_done")
    assert machine.state is State.IDLE


@pytest.mark.anyio
async def test_streaming_tool_call_before_text_runs_tool_then_streams_final(mock_sd_output_stream):
    called = []

    def lookup():
        called.append("lookup")
        return "tool result"

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="lookup",
            description="lookup",
            parameters={"type": "object", "properties": {}},
            handler=lookup,
        )
    )
    tool_call = {
        "id": "call_lookup",
        "type": "function",
        "function": {"name": "lookup", "arguments": "{}"},
    }
    llm = FakeStreamingLLM(
        [
            [
                LLMStreamEvent(type="tool_call_done", tool_call=tool_call),
                LLMStreamEvent(type="done"),
            ],
            [
                LLMStreamEvent(type="text_delta", text="Ini hasilnya."),
                LLMStreamEvent(type="done"),
            ],
        ]
    )
    tts = FakeRealtimeTTS()
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=llm,
        tts=tts,
        registry=registry,
        state_machine=StateMachine(initial_state=State.THINKING),
    )

    reply = await orch.handle_audio(b"audio")

    assert called == ["lookup"]
    assert reply == "Ini hasilnya."
    assert tts.spoken == ["Ini hasilnya."]
    assert any(m.get("role") == "tool" and m.get("content") == "tool result" for m in llm.requests[1][0])


@pytest.mark.anyio
async def test_streaming_tool_call_after_text_interrupts_then_streams_followup(mock_sd_output_stream):
    called = []

    def lookup():
        called.append("lookup")
        return "tool result"

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="lookup",
            description="lookup",
            parameters={"type": "object", "properties": {}},
            handler=lookup,
        )
    )
    tool_call = {
        "id": "call_lookup",
        "type": "function",
        "function": {"name": "lookup", "arguments": "{}"},
    }
    llm = FakeStreamingLLM(
        [
            [
                LLMStreamEvent(type="text_delta", text="Aku cek dulu."),
                LLMStreamEvent(type="tool_call_done", tool_call=tool_call),
                LLMStreamEvent(type="text_delta", text=" Jangan lanjutkan ini."),
                LLMStreamEvent(type="done"),
            ],
            [
                LLMStreamEvent(type="text_delta", text="Hasil akhirnya."),
                LLMStreamEvent(type="done"),
            ],
        ]
    )
    tts = FakeRealtimeTTS()
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=llm,
        tts=tts,
        registry=registry,
        state_machine=StateMachine(initial_state=State.THINKING),
    )

    reply = await orch.handle_audio(b"audio")

    assert called == ["lookup"]
    assert reply == "Hasil akhirnya."
    assert "Aku cek dulu." in tts.spoken
    assert "Hasil akhirnya." in tts.spoken
    assert all("Jangan lanjutkan ini" not in text for text in tts.spoken)


@pytest.mark.anyio
async def test_barge_in_during_thinking_cancels_llm_and_starts_listening(mock_sd_output_stream):
    class SlowStreamingLLM:
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def chat(self, messages, tools=None):
            raise AssertionError("streaming path expected")

        async def stream_chat(self, messages, tools=None):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            if False:
                yield LLMStreamEvent(type="done")

    recorder = FakeRecorder()
    llm = SlowStreamingLLM()
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=llm,
        tts=FakeRealtimeTTS(),
        registry=ToolRegistry(),
        state_machine=StateMachine(initial_state=State.THINKING),
        recorder=recorder,
    )

    task = asyncio.create_task(orch.handle_audio(b"audio"))
    await asyncio.wait_for(llm.started.wait(), 1)

    assert orch.request_barge_in() is True
    await asyncio.wait_for(llm.cancelled.wait(), 1)
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)

    assert recorder.is_recording is True
    assert recorder.started == 1
    assert orch.state_machine.state is State.LISTENING


@pytest.mark.anyio
async def test_barge_in_during_preparing_audio_cancels_tts(mock_sd_output_stream):
    class SlowRealtimeTTS(TTSAdapter, RealtimeTTSAdapter):
        def __init__(self):
            self.started = asyncio.Event()
            self.cancelled = asyncio.Event()

        async def stream(self, text):
            yield text.encode()

        async def stream_pcm(self, text):
            self.started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
            if False:
                yield b""

    recorder = FakeRecorder()
    tts = SlowRealtimeTTS()
    llm = FakeStreamingLLM(
        [[LLMStreamEvent(type="text_delta", text="Halo."), LLMStreamEvent(type="done")]]
    )
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=StateMachine(initial_state=State.THINKING),
        recorder=recorder,
    )

    task = asyncio.create_task(orch.handle_audio(b"audio"))
    await asyncio.wait_for(tts.started.wait(), 1)

    assert orch.state_machine.state is State.PREPARING_AUDIO
    assert orch.request_barge_in() is True
    await asyncio.wait_for(tts.cancelled.wait(), 1)
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)

    assert recorder.is_recording is True
    assert orch.state_machine.state is State.LISTENING


@pytest.mark.anyio
async def test_stale_turn_drops_assistant_text_and_audio(mock_sd_output_stream):
    assistant_updates = []
    tts = FakeRealtimeTTS()
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM([]),
        tts=tts,
        registry=ToolRegistry(),
        state_machine=StateMachine(initial_state=State.THINKING),
        on_assistant_text=assistant_updates.append,
    )
    old_turn = TurnContext(id="old")
    orch._current_turn = TurnContext(id="new")

    orch._emit_assistant_text_for_turn(old_turn, "stale")

    async def text_stream():
        yield "This should not play."

    await orch.speak_streaming(old_turn, text_stream())

    assert assistant_updates == []
    assert tts.spoken == []


@pytest.mark.anyio
async def test_stale_tool_result_does_not_emit_tool_callback(mock_sd_output_stream):
    started = threading.Event()
    release = threading.Event()
    emitted = []

    def slow_tool():
        started.set()
        release.wait(timeout=1)
        return "done"

    registry = ToolRegistry()
    registry.register(
        Tool(
            name="slow_tool",
            description="slow tool",
            parameters={"type": "object", "properties": {}},
            handler=slow_tool,
        )
    )
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM([]),
        tts=FakeRealtimeTTS(),
        registry=registry,
        state_machine=StateMachine(initial_state=State.THINKING),
        on_tool_executed=lambda name, result: emitted.append((name, result)),
    )
    turn = TurnContext(id="tool_turn")
    orch._current_turn = turn
    tool_call = {
        "id": "call_slow",
        "type": "function",
        "function": {"name": "slow_tool", "arguments": "{}"},
    }

    task = asyncio.create_task(orch._run_tool_for_turn(turn, tool_call))
    await asyncio.to_thread(started.wait, 1)
    orch._current_turn = TurnContext(id="new")
    release.set()
    await asyncio.wait_for(task, 1)

    assert emitted == []


def test_start_listening_barges_in_active_turn():
    recorder = FakeRecorder()
    machine = StateMachine(initial_state=State.THINKING)
    orch = Orchestrator(
        stt=FakeSTT(),
        llm=FakeLLM([]),
        tts=FakeRealtimeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )
    old_turn = TurnContext(id="active")
    orch._current_turn = old_turn

    assert orch.start_listening() is True

    assert old_turn.is_cancelled()
    assert recorder.is_recording is True
    assert recorder.started == 1
    assert machine.state is State.LISTENING
