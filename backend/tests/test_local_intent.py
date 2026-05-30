from verse.intent import LocalIntentRouter


def test_local_intent_routes_time_query():
    match = LocalIntentRouter().route("jam berapa sekarang?")

    assert match is not None
    assert match.intent == "system.get_time"
    assert match.tool_name == "get_time"
    assert match.confidence >= 0.9


def test_local_intent_routes_open_known_apps():
    router = LocalIntentRouter()

    vscode = router.route("buka VS Code")
    spotify = router.route("open spotify")

    assert vscode is not None
    assert vscode.tool_name == "open_app"
    assert vscode.arguments == {"app_name": "Visual Studio Code"}
    assert spotify is not None
    assert spotify.arguments == {"app_name": "Spotify"}


def test_local_intent_routes_music_controls():
    router = LocalIntentRouter()

    play = router.route("putar musik jazz")
    pause = router.route("stop musik")

    assert play is not None
    assert play.tool_name == "play_music"
    assert play.arguments == {"query": "jazz"}
    assert pause is not None
    assert pause.tool_name == "pause_music"


def test_local_intent_ignores_unknown_text():
    assert LocalIntentRouter().route("ceritakan tentang arsitektur verse") is None
