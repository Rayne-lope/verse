import asyncio
from types import SimpleNamespace

from verse.config import LLMConfig
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
