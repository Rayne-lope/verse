import asyncio
from types import SimpleNamespace

from verse.config import LLMConfig
from verse.llm.base import LLMAdapter, LLMResponse
from verse.llm.deepseek import DeepSeekAdapter


class FakeCompletions:
    def __init__(self, message):
        self.message = message
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=self.message)])


class FakeChat:
    def __init__(self, message):
        self.completions = FakeCompletions(message)


class FakeClient:
    def __init__(self, message):
        self.chat = FakeChat(message)


def test_deepseek_adapter_returns_text_without_tools():
    message = SimpleNamespace(content="hai", tool_calls=None)
    client = FakeClient(message)
    adapter = DeepSeekAdapter(
        LLMConfig(model="deepseek-chat", temperature=0.2),
        client=client,
    )

    response = asyncio.run(adapter.chat([{"role": "user", "content": "halo"}]))

    assert response.text == "hai"
    assert response.tool_calls == []
    assert client.chat.completions.request == {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "halo"}],
        "temperature": 0.2,
    }


def test_deepseek_adapter_builds_client_with_config_base_url(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dummy-key")
    adapter = DeepSeekAdapter(
        LLMConfig(model="deepseek-v4-flash-free", base_url="https://opencode.ai/zen/v1")
    )

    assert str(adapter.client.base_url).rstrip("/") == "https://opencode.ai/zen/v1"


def test_deepseek_adapter_serializes_tool_calls():
    function = SimpleNamespace(name="open_app", arguments='{"app_name":"Music"}')
    tool_call = SimpleNamespace(id="call_1", type="function", function=function)
    message = SimpleNamespace(content=None, tool_calls=[tool_call])
    adapter = DeepSeekAdapter(client=FakeClient(message))

    response = asyncio.run(
        adapter.chat(
            [{"role": "user", "content": "open music"}],
            tools=[{"type": "function", "function": {"name": "open_app"}}],
        )
    )

    assert response.text == ""
    assert response.tool_calls == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "open_app",
                "arguments": '{"app_name":"Music"}',
            },
        }
    ]


class FakeStreamingCompletions:
    def __init__(self, chunks):
        self.chunks = chunks
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return iter(self.chunks)


class FakeStreamingChat:
    def __init__(self, chunks):
        self.completions = FakeStreamingCompletions(chunks)


class FakeStreamingClient:
    def __init__(self, chunks):
        self.chat = FakeStreamingChat(chunks)


def _chunk(delta, finish_reason=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=delta,
                finish_reason=finish_reason,
            )
        ]
    )


def test_deepseek_adapter_streams_text_deltas():
    chunks = [
        _chunk(SimpleNamespace(content="Ha", tool_calls=None)),
        _chunk(SimpleNamespace(content="lo", tool_calls=None), finish_reason="stop"),
    ]
    client = FakeStreamingClient(chunks)
    adapter = DeepSeekAdapter(
        LLMConfig(model="deepseek-chat", temperature=0.2),
        client=client,
    )

    events = asyncio.run(_collect_stream(adapter.stream_chat([{"role": "user", "content": "halo"}])))

    assert [event.type for event in events] == ["text_delta", "text_delta", "done"]
    assert "".join(event.text for event in events if event.type == "text_delta") == "Halo"
    assert client.chat.completions.request == {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": "halo"}],
        "temperature": 0.2,
        "stream": True,
    }


def test_deepseek_adapter_streams_tool_call_done():
    chunks = [
        _chunk(
            SimpleNamespace(
                content=None,
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id="call_1",
                        type="function",
                        function=SimpleNamespace(name="get_weather", arguments=""),
                    )
                ],
            )
        ),
        _chunk(
            SimpleNamespace(
                content=None,
                tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id=None,
                        type=None,
                        function=SimpleNamespace(name=None, arguments='{"city":"Jakarta"}'),
                    )
                ],
            ),
            finish_reason="tool_calls",
        ),
    ]
    adapter = DeepSeekAdapter(client=FakeStreamingClient(chunks))

    events = asyncio.run(_collect_stream(adapter.stream_chat([{"role": "user", "content": "cuaca"}])))

    done_events = [event for event in events if event.type == "tool_call_done"]
    assert len(done_events) == 1
    assert done_events[0].tool_call == {
        "id": "call_1",
        "type": "function",
        "function": {
            "name": "get_weather",
            "arguments": '{"city":"Jakarta"}',
        },
    }
    assert events[-1].type == "done"


def test_llm_adapter_stream_chat_falls_back_to_chat_without_speaking_tools():
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "open_app", "arguments": '{"app_name":"Music"}'},
    }

    class FakeAdapter(LLMAdapter):
        async def chat(self, messages, tools=None):
            return LLMResponse(text="speculative text", tool_calls=[tool_call])

    events = asyncio.run(_collect_stream(FakeAdapter().stream_chat([])))

    assert [event.type for event in events] == ["tool_call_done", "done"]
    assert events[0].tool_call == tool_call


async def _collect_stream(stream):
    return [event async for event in stream]
