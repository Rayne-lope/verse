from unittest.mock import MagicMock

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


def test_spotify_parse_first_playlist():
    payload = {
        "playlists": {
            "items": [
                {
                    "uri": "spotify:playlist:play123",
                    "name": "Lofi Chill",
                    "owner": {"display_name": "Lofi Girl"},
                }
            ]
        }
    }
    assert spotify._parse_first_item(payload, "playlist") == (
        "spotify:playlist:play123",
        "Lofi Chill",
        "Lofi Girl",
    )


def test_spotify_parse_first_album():
    payload = {
        "albums": {
            "items": [
                {
                    "uri": "spotify:album:alb123",
                    "name": "Random Access Memories",
                    "artists": [{"name": "Daft Punk"}],
                }
            ]
        }
    }
    assert spotify._parse_first_item(payload, "album") == (
        "spotify:album:alb123",
        "Random Access Memories",
        "Daft Punk",
    )


def test_spotify_parse_first_artist():
    payload = {
        "artists": {
            "items": [
                {
                    "uri": "spotify:artist:art123",
                    "name": "Queen",
                }
            ]
        }
    }
    assert spotify._parse_first_item(payload, "artist") == (
        "spotify:artist:art123",
        "Queen",
        "Artist",
    )



def test_get_weather_returns_weather_info(monkeypatch):
    mock_geo_response = MagicMock()
    mock_geo_response.json = lambda: {
        "results": [
            {
                "latitude": -6.2,
                "longitude": 106.8,
                "name": "Jakarta",
                "country": "Indonesia",
            }
        ]
    }
    mock_geo_response.raise_for_status = MagicMock()

    mock_weather_response = MagicMock()
    mock_weather_response.json = lambda: {
        "current_weather": {"temperature": 29.5, "windspeed": 12.0, "weathercode": 0}
    }
    mock_weather_response.raise_for_status = MagicMock()

    def mock_get(url, *args, **kwargs):
        if "geocoding-api" in url:
            return mock_geo_response
        return mock_weather_response

    monkeypatch.setattr("requests.get", mock_get)

    from verse.tools.builtin import weather

    res = weather.get_weather("Jakarta")
    assert "Jakarta, Indonesia: 29.5°C, Clear sky. Wind speed: 12.0 km/h." in res


def test_notes_tool_lifecycle(tmp_path, monkeypatch):
    from verse.tools.builtin import notes

    monkeypatch.setattr("verse.tools.builtin.notes.NOTES_DIR", tmp_path)

    # 1. list empty
    assert "No notes found" in notes.list_notes()

    # 2. take note
    res = notes.take_note("my_note", "Hello notes!")
    assert "Successfully saved note" in res
    assert (tmp_path / "my_note.md").exists()

    # 3. read note
    read_res = notes.read_note("my_note")
    assert "Hello notes!" in read_res

    # 4. list notes
    list_res = notes.list_notes()
    assert "- my_note" in list_res


def test_read_calendar_calls_osascript(monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value.stdout = "Meeting with Rayne (10:00:00 AM)"
    monkeypatch.setattr("subprocess.run", mock_run)

    from verse.tools.builtin import calendar

    res = calendar.read_calendar("today")
    assert "Meeting with Rayne" in res
    assert mock_run.called


def test_reminders_calls_osascript(monkeypatch):
    mock_run = MagicMock()
    mock_run.return_value.stdout = "Buy milk (list: Reminders)"
    monkeypatch.setattr("subprocess.run", mock_run)

    from verse.tools.builtin import reminders

    read_res = reminders.read_reminders()
    assert "Buy milk" in read_res

    add_res = reminders.add_reminder("Buy bread", "Whole wheat")
    assert "Successfully added reminder" in add_res
