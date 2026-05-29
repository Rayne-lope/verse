from verse.tools.builtin import spotify, system, web
from verse.tools.registry import Tool, ToolRegistry, build_default_registry


def _echo_tool(name="echo"):
    return Tool(
        name=name,
        description="Echo the message back.",
        parameters={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
        handler=lambda message: f"echo: {message}",
    )


def test_register_and_execute():
    registry = ToolRegistry()
    registry.register(_echo_tool())

    assert "echo" in registry
    assert registry.execute("echo", {"message": "hi"}) == "echo: hi"


def test_execute_unknown_tool_raises():
    registry = ToolRegistry()
    try:
        registry.execute("missing")
    except KeyError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("expected KeyError")


def test_execute_call_parses_json_arguments():
    registry = ToolRegistry()
    registry.register(_echo_tool())

    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "echo", "arguments": '{"message": "halo"}'},
    }

    assert registry.execute_call(tool_call) == "echo: halo"


def test_execute_call_handles_empty_arguments():
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="ping",
            description="ping",
            parameters={"type": "object", "properties": {}},
            handler=lambda: "pong",
        )
    )

    tool_call = {"function": {"name": "ping", "arguments": ""}}
    assert registry.execute_call(tool_call) == "pong"


def test_tool_definition_matches_openai_schema():
    tool = _echo_tool()
    assert tool.definition() == {
        "type": "function",
        "function": {
            "name": "echo",
            "description": "Echo the message back.",
            "parameters": {
                "type": "object",
                "properties": {"message": {"type": "string"}},
                "required": ["message"],
            },
        },
    }


def test_list_definitions_respects_enabled_order():
    registry = ToolRegistry()
    registry.register(_echo_tool("a"))
    registry.register(_echo_tool("b"))
    registry.register(_echo_tool("c"))

    definitions = registry.list_definitions(enabled=["c", "a", "missing"])
    names = [d["function"]["name"] for d in definitions]
    assert names == ["c", "a"]


def test_build_default_registry_registers_core_tools():
    registry = build_default_registry()
    for name in ["play_music", "pause_music", "open_app", "web_search", "get_time"]:
        assert name in registry


def test_build_default_registry_filters_by_enabled():
    registry = build_default_registry(enabled=["open_app", "get_time"])
    assert registry.names() == ["open_app", "get_time"]


def test_get_time_handler_returns_string():
    result = system.get_time()
    assert result.startswith("It is")


def test_web_search_format_results():
    results = [
        {"title": "Jazz", "description": "About jazz", "url": "https://x.test"},
    ]
    formatted = web._format_results("jazz", results)
    assert "1. Jazz — About jazz (https://x.test)" in formatted


def test_web_search_format_results_empty():
    assert web._format_results("jazz", []) == "No web results found for 'jazz'."


def test_spotify_parse_first_track():
    payload = {
        "tracks": {
            "items": [
                {
                    "uri": "spotify:track:abc123",
                    "name": "So What",
                    "artists": [{"name": "Miles Davis"}],
                }
            ]
        }
    }
    assert spotify._parse_first_track(payload) == (
        "spotify:track:abc123",
        "So What",
        "Miles Davis",
    )


def test_spotify_parse_first_track_empty():
    assert spotify._parse_first_track({"tracks": {"items": []}}) is None
