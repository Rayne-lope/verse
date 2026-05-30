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
    play_playlist = router.route("putar playlist lofi")
    play_album = router.route("play album thriller")
    play_artist = router.route("mainkan artist queen")

    assert play is not None
    assert play.tool_name == "play_music"
    assert play.arguments == {"query": "jazz"}

    assert pause is not None
    assert pause.tool_name == "pause_music"

    assert play_playlist is not None
    assert play_playlist.tool_name == "play_music"
    assert play_playlist.arguments == {"query": "lofi", "type": "playlist"}

    assert play_album is not None
    assert play_album.tool_name == "play_music"
    assert play_album.arguments == {"query": "thriller", "type": "album"}

    assert play_artist is not None
    assert play_artist.tool_name == "play_music"
    assert play_artist.arguments == {"query": "queen", "type": "artist"}



def test_local_intent_ignores_unknown_text():
    assert LocalIntentRouter().route("ceritakan tentang arsitektur verse") is None
