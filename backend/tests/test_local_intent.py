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


def test_local_intent_routes_settings_controls():
    router = LocalIntentRouter()

    # 1. Volume
    vol_set = router.route("setel volume ke 60")
    assert vol_set is not None
    assert vol_set.tool_name == "set_volume"
    assert vol_set.arguments == {"level": 60}

    vol_up = router.route("gedein volume")
    assert vol_up is not None
    assert vol_up.tool_name == "set_volume"
    assert vol_up.arguments == {"level": 75}

    vol_down = router.route("kecilin volume")
    assert vol_down is not None
    assert vol_down.tool_name == "set_volume"
    assert vol_down.arguments == {"level": 25}

    vol_get = router.route("cek volume")
    assert vol_get is not None
    assert vol_get.tool_name == "get_volume"

    # 2. Mute
    mute = router.route("matikan suara")
    assert mute is not None
    assert mute.tool_name == "set_muted"
    assert mute.arguments == {"muted": True}

    unmute = router.route("unmute")
    assert unmute is not None
    assert unmute.tool_name == "set_muted"
    assert unmute.arguments == {"muted": False}

    # 3. Dark mode
    dark = router.route("nyalakan mode gelap")
    assert dark is not None
    assert dark.tool_name == "set_dark_mode"
    assert dark.arguments == {"enabled": True}

    light = router.route("aktifkan mode terang")
    assert light is not None
    assert light.tool_name == "set_dark_mode"
    assert light.arguments == {"enabled": False}

    # 4. DND
    dnd_on = router.route("nyalakan do not disturb")
    assert dnd_on is not None
    assert dnd_on.tool_name == "set_dnd"
    assert dnd_on.arguments == {"enabled": True}

    dnd_off = router.route("matikan dnd")
    assert dnd_off is not None
    assert dnd_off.tool_name == "set_dnd"
    assert dnd_off.arguments == {"enabled": False}
