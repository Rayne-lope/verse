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
    for name in ["play_music", "pause_music", "open_app", "close_app", "web_search", "get_time"]:
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


def test_spotify_get_clean_username():
    assert spotify._get_clean_spotify_username("31ky3wdovalw2ddnc3zxh7dlhyj4") == "31ky3wdovalw2ddnc3zxh7dlhyj4"
    assert spotify._get_clean_spotify_username("https://open.spotify.com/user/31ky3wdovalw2ddnc3zxh7dlhyj4?si=9d1f") == "31ky3wdovalw2ddnc3zxh7dlhyj4"
    assert spotify._get_clean_spotify_username("   ") == ""


def test_spotify_find_user_playlist_scrapes(monkeypatch):
    mock_html = """
    <div>
      <a class="class1" href="/playlist/6r3aZ4RiTxmf6z9D9UQNHM">
        <span>My Playlist #11</span>
      </a>
      <a class="class1" href="/playlist/0jGMJWyLZc3zvlBpndr8j4">
        <span>My obsession to lanaa 🫀</span>
      </a>
    </div>
    """

    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = mock_html.encode("utf-8")

    mock_urlopen = MagicMock(return_value=mock_response)
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    # 1. Exact match
    res = spotify._find_user_playlist("My Playlist #11", "dummy_user")
    assert res == ("spotify:playlist:6r3aZ4RiTxmf6z9D9UQNHM", "My Playlist #11", "You")

    # 2. Substring match case-insensitive
    res = spotify._find_user_playlist("lanaa", "dummy_user")
    assert res == ("spotify:playlist:0jGMJWyLZc3zvlBpndr8j4", "My obsession to lanaa 🫀", "You")

    # 3. No match
    assert spotify._find_user_playlist("missing playlist", "dummy_user") is None


def test_spotify_find_user_playlist_token_matching(monkeypatch):
    mock_html = """
    <div>
      <a class="class1" href="/playlist/6r3aZ4RiTxmf6z9D9UQNHM">
        <span>My Playlist #11</span>
      </a>
      <a class="class1" href="/playlist/0jGMJWyLZc3zvlBpndr8j4">
        <span>My obsession to lanaa 🫀</span>
      </a>
    </div>
    """

    mock_response = MagicMock()
    mock_response.__enter__.return_value = mock_response
    mock_response.read.return_value = mock_html.encode("utf-8")

    mock_urlopen = MagicMock(return_value=mock_response)
    monkeypatch.setattr("urllib.request.urlopen", mock_urlopen)

    # Fuzzy match with moriant username inside query and different naming
    res = spotify._find_user_playlist("My Obsession to Lana Del Rey Morian", "31ky3wdovalw2ddnc3zxh7dlhyj4")
    assert res == ("spotify:playlist:0jGMJWyLZc3zvlBpndr8j4", "My obsession to lanaa 🫀", "You")



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
    assert "Buy bread" in add_res
    assert "default list" in add_res


def test_open_app_resolves_aliases(monkeypatch):
    from verse.tools.builtin import system
    
    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)
    
    system.open_app("brave")
    mock_run.assert_called_with(["open", "-a", "Brave Browser"], check=True)
    
    system.open_app("  vs code  ")
    mock_run.assert_called_with(["open", "-a", "Visual Studio Code"], check=True)
    
    system.open_app("Safari")
    mock_run.assert_called_with(["open", "-a", "Safari"], check=True)


def test_system_controls_tools(monkeypatch):
    from verse.tools.builtin import system
    
    mock_run = MagicMock()
    mock_run.return_value.stdout = "50\n"
    monkeypatch.setattr("subprocess.run", mock_run)
    
    # 1. get_volume
    assert "50%" in system.get_volume()
    mock_run.assert_called_with(["osascript", "-e", "output volume of (get volume settings)"], capture_output=True, text=True, check=True, timeout=20.0)
    
    # 2. set_volume
    assert "75%" in system.set_volume(75)
    mock_run.assert_called_with(["osascript", "-e", "set volume output volume 75"], capture_output=True, text=True, check=True, timeout=20.0)
    
    # 3. is_muted (true)
    mock_run.return_value.stdout = "true\n"
    assert "muted" in system.is_muted()
    
    # 4. is_muted (false)
    mock_run.return_value.stdout = "false\n"
    assert "not muted" in system.is_muted()
    
    # 5. set_muted
    assert "muted" in system.set_muted(True)
    mock_run.assert_called_with(["osascript", "-e", "set volume with output muted"], capture_output=True, text=True, check=True, timeout=20.0)
    
    # 6. set_muted (unmute)
    assert "unmuted" in system.set_muted(False)
    mock_run.assert_called_with(["osascript", "-e", "set volume without output muted"], capture_output=True, text=True, check=True, timeout=20.0)
    
    # 7. is_dark_mode
    mock_run.return_value.stdout = "true\n"
    assert "enabled" in system.is_dark_mode()
    
    # 8. set_dark_mode
    assert "Dark Mode" in system.set_dark_mode(True)
    mock_run.assert_called_with(["osascript", "-e", 'tell application "System Events" to tell appearance preferences to set dark mode to true'], capture_output=True, text=True, check=True, timeout=20.0)
    
    # 9. set_dnd (fallback path since list_shortcuts returns no matching names in test)
    mock_run.return_value.stdout = ""
    res = system.set_dnd(True)
    assert "Shortcuts app" in res
    assert "Toggle DND" in res

    # 10. set_dnd (successful match path with lowercase name)
    def mock_list_shortcuts():
        return "Your shortcuts:\n- toggle dnd\n- Set Volume"
    monkeypatch.setattr("verse.tools.builtin.shortcuts.list_shortcuts", mock_list_shortcuts)
    
    mock_run_shortcut = MagicMock(return_value="Ran shortcut")
    monkeypatch.setattr("verse.tools.builtin.shortcuts.run_shortcut", mock_run_shortcut)
    
    res = system.set_dnd(True)
    assert "Do Not Disturb is now enabled" in res
    mock_run_shortcut.assert_called_with("toggle dnd", text_input="On")


def test_system_brightness_controls(monkeypatch):
    from verse.tools.builtin import system
    
    mock_get = MagicMock(return_value=0)
    mock_set = MagicMock(return_value=0)
    
    import ctypes
    class MockDoubleRef:
        def __init__(self):
            self.value = 0.65
            
    mock_brightness = MockDoubleRef()
    
    def dummy_get(display, ref):
        ref.contents.value = 0.65
        return 0
        
    monkeypatch.setattr("ctypes.CDLL", lambda *args, **kwargs: MagicMock())
    monkeypatch.setattr("ctypes.c_float", lambda: mock_brightness)
    monkeypatch.setattr("ctypes.byref", lambda x: x)
    
    # Mock the DisplayServices calls inside system.py
    # We will mock CDLL to return dummy objects that have the target functions
    class DummyDS:
        def __init__(self):
            # Define functions as local objects so we can set attributes like argtypes on them
            def get_linear(display_id, ref):
                ref.value = 0.65
                return 0
            
            def set_linear(display_id, val):
                return 0
                
            set_linear.argtypes = []
            
            self.DisplayServicesGetLinearBrightness = get_linear
            self.DisplayServicesSetLinearBrightness = set_linear
            
    class DummyCG:
        def CGMainDisplayID(self):
            return 1
            
    def mock_cdll(path):
        if "CoreGraphics" in path:
            return DummyCG()
        return DummyDS()
        
    monkeypatch.setattr("ctypes.CDLL", mock_cdll)
    
    # Test get_brightness
    assert "65%" in system.get_brightness()
    
    # Test set_brightness
    assert "brightness set to 75%" in system.set_brightness(75)
