import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from verse.config import AppConfig
from verse.intent.turn import TurnContext
from verse.orchestrator import Orchestrator, CANNED_ACKNOWLEDGEMENTS
from verse.state import State, StateMachine
from verse.tools.registry import Tool, ToolRegistry
from verse.tts.base import RealtimeTTSAdapter, TTSAdapter
from verse.llm.base import LLMResponse


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


class FakeLLM:
    def __init__(self, responses):
        self.responses = responses
        self.requests = []

    async def chat(self, messages, tools=None):
        self.requests.append((messages, tools))
        return self.responses.pop(0)


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
