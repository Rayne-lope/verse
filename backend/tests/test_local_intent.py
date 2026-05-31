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
    notes = router.route("buka notes")

    assert vscode is not None
    assert vscode.tool_name == "open_app"
    assert vscode.arguments == {"app_name": "Visual Studio Code"}
    assert spotify is not None
    assert spotify.arguments == {"app_name": "Spotify"}
    assert notes is not None
    assert notes.arguments == {"app_name": "Notes"}


def test_local_intent_routes_close_known_apps():
    match = LocalIntentRouter().route("tutup chrome")

    assert match is not None
    assert match.intent == "system.close_app"
    assert match.tool_name == "close_app"
    assert match.arguments == {"app_name": "Google Chrome"}


def test_local_intent_routes_music_controls():
    router = LocalIntentRouter()

    play = router.route("putar musik jazz")
    pause = router.route("stop musik")
    resume = router.route("lanjutkan spotify")
    play_playlist = router.route("putar playlist lofi")
    play_album = router.route("play album thriller")
    play_artist = router.route("mainkan artist queen")

    assert play is not None
    assert play.tool_name == "play_music"
    assert play.arguments == {"query": "jazz"}

    assert pause is not None
    assert pause.tool_name == "pause_music"

    assert resume is not None
    assert resume.intent == "music.resume"
    assert resume.tool_name == "play_music"
    assert resume.arguments == {}

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

    vol_clamped = router.route("volume 150")
    assert vol_clamped is not None
    assert vol_clamped.tool_name == "set_volume"
    assert vol_clamped.arguments == {"level": 100}

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

    # 5. Brightness
    bright_set = router.route("setel brightness ke 70")
    assert bright_set is not None
    assert bright_set.tool_name == "set_brightness"
    assert bright_set.arguments == {"level": 70}

    bright_up = router.route("terangkan layar")
    assert bright_up is not None
    assert bright_up.tool_name == "set_brightness"
    assert bright_up.arguments == {"level": 80}

    bright_down = router.route("redupkan layar")
    assert bright_down is not None
    assert bright_down.tool_name == "set_brightness"
    assert bright_down.arguments == {"level": 20}

    bright_get = router.route("cek kecerahan")
    assert bright_get is not None
    assert bright_get.tool_name == "get_brightness"


def test_local_intent_routes_browser():
    router = LocalIntentRouter()

    # 1. Close browser
    close_b = router.route("tutup browser")
    assert close_b is not None
    assert close_b.tool_name == "browser_close"

    # 2. Google Search
    search_g = router.route("cari harga emas di google")
    assert search_g is not None
    assert search_g.tool_name == "browser_navigate"
    assert "https://www.google.com/search?q=harga%20emas" in search_g.arguments["url"]

    search_g2 = router.route("google apple stock price")
    assert search_g2 is not None
    assert search_g2.tool_name == "browser_navigate"
    assert "https://www.google.com/search?q=apple%20stock%20price" in search_g2.arguments["url"]

    # 3. Direct Navigation
    nav_site = router.route("buka website tokopedia")
    assert nav_site is not None
    assert nav_site.tool_name == "browser_navigate"
    assert nav_site.arguments == {"url": "tokopedia.com"}

    nav_site_dot = router.route("kunjungi wikipedia.org")
    assert nav_site_dot is not None
    assert nav_site_dot.tool_name == "browser_navigate"
    assert nav_site_dot.arguments == {"url": "wikipedia.org"}


def test_local_intent_routes_web_notes_and_memory():
    router = LocalIntentRouter()

    search = router.route("search web for harga emas")
    note = router.route("catat beli susu besok pagi")
    remember = router.route("remember that I prefer short answers")

    assert search is not None
    assert search.intent == "web.search"
    assert search.tool_name == "web_search"
    assert search.arguments == {"query": "harga emas"}

    assert note is not None
    assert note.intent == "notes.take"
    assert note.tool_name == "take_note"
    assert note.arguments == {
        "title": "beli susu besok pagi",
        "content": "beli susu besok pagi",
    }

    assert remember is not None
    assert remember.intent == "memory.remember"
    assert remember.tool_name == "remember"
    assert remember.arguments == {"content": "i prefer short answers"}
