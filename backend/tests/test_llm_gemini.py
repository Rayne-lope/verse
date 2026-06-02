import asyncio
from types import SimpleNamespace

from verse.config import LLMConfig
from verse.llm.gemini import GEMINI_API_BASE_URL, GEMINI_DEFAULT_MODEL, GeminiAdapter


class FakeModels:
    def __init__(self, response):
        self.response = response
        self.request = None

    def generate_content(self, **kwargs):
        self.request = kwargs
        return self.response


class FakeClient:
    def __init__(self, response):
        self.models = FakeModels(response)


def _response_with_parts(parts):
    return SimpleNamespace(
        text=None,
        candidates=[
            SimpleNamespace(
                content=SimpleNamespace(parts=parts)
            )
        ],
    )


def test_gemini_adapter_defaults_model_and_base_url_for_gemini_provider():
    adapter = GeminiAdapter(LLMConfig(provider="gemini"))

    assert adapter.model == GEMINI_DEFAULT_MODEL
    assert adapter.base_url == GEMINI_API_BASE_URL


def test_gemini_adapter_builds_client_with_config_base_url(monkeypatch):
    created = {}

    def fake_client(**kwargs):
        created.update(kwargs)
        return "client"

    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("google.genai.Client", fake_client)
    adapter = GeminiAdapter(
        LLMConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        )
    )

    assert adapter.client == "client"
    assert created["api_key"] == "dummy-key"
    assert created["http_options"].base_url == "https://generativelanguage.googleapis.com/v1beta"


def test_gemini_adapter_returns_text_and_passes_tools():
    response = SimpleNamespace(text="Halo", candidates=[])
    client = FakeClient(response)
    adapter = GeminiAdapter(
        LLMConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            temperature=0.2,
        ),
        client=client,
    )

    result = asyncio.run(
        adapter.chat(
            [
                {"role": "system", "content": "You are Verse."},
                {"role": "user", "content": "halo"},
            ],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get weather",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "city": {"type": "string", "description": "City name"},
                            },
                            "required": ["city"],
                        },
                    },
                }
            ],
        )
    )

    assert result.text == "Halo"
    assert client.models.request["model"] == "gemini-3.5-flash"
    assert client.models.request["contents"][0].role == "user"
    config = client.models.request["config"]
    assert config.temperature == 0.2
    assert config.system_instruction == "You are Verse."
    assert config.tools[0].function_declarations[0].name == "get_weather"


def test_gemini_adapter_serializes_function_calls():
    function_call = SimpleNamespace(
        id="call_1",
        name="browser_navigate",
        args={"url": "https://example.com"},
    )
    response = _response_with_parts([
        SimpleNamespace(text=None, function_call=function_call)
    ])
    adapter = GeminiAdapter(client=FakeClient(response))

    result = asyncio.run(adapter.chat([{"role": "user", "content": "buka web"}]))

    assert result.text == ""
    assert result.tool_calls == [
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "browser_navigate",
                "arguments": '{"url": "https://example.com"}',
            },
        }
    ]


def test_gemini_adapter_converts_tool_results_back_to_function_response():
    response = SimpleNamespace(text="Sudah.", candidates=[])
    client = FakeClient(response)
    adapter = GeminiAdapter(client=client)

    asyncio.run(
        adapter.chat(
            [
                {"role": "user", "content": "buka web"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "browser_navigate",
                                "arguments": '{"url": "https://example.com"}',
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call_1",
                    "content": "Successfully navigated.",
                },
            ]
        )
    )

    contents = client.models.request["contents"]
    function_response = contents[-1].parts[0].function_response
    assert function_response.id == "call_1"
    assert function_response.name == "browser_navigate"
    assert function_response.response == {"result": "Successfully navigated."}
