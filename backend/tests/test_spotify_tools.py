from __future__ import annotations

from unittest.mock import patch

from verse.tools.builtin.spotify import (
    get_now_playing,
    get_spotify_volume,
    set_spotify_volume,
    skip_music,
)


def test_set_spotify_volume() -> None:
    with patch("verse.tools.builtin.spotify.run_applescript") as mock_applescript:
        # Standard valid set
        res = set_spotify_volume(45)
        mock_applescript.assert_called_once_with('tell application "Spotify" to set sound volume to 45')
        assert "Spotify volume set to 45%" in res

        # Boundary clamping (above 100)
        mock_applescript.reset_mock()
        res = set_spotify_volume(150)
        mock_applescript.assert_called_once_with('tell application "Spotify" to set sound volume to 100')
        assert "Spotify volume set to 100%" in res

        # Boundary clamping (below 0)
        mock_applescript.reset_mock()
        res = set_spotify_volume(-10)
        mock_applescript.assert_called_once_with('tell application "Spotify" to set sound volume to 0')
        assert "Spotify volume set to 0%" in res


def test_get_spotify_volume() -> None:
    with patch("verse.tools.builtin.spotify.run_applescript", return_value="75") as mock_applescript:
        res = get_spotify_volume()
        mock_applescript.assert_called_once_with('tell application "Spotify" to get sound volume')
        assert "Spotify volume is at 75%." in res


def test_skip_music() -> None:
    with patch("verse.tools.builtin.spotify.run_applescript") as mock_applescript:
        # Skip next
        res = skip_music("next")
        mock_applescript.assert_called_once_with('tell application "Spotify" to next track')
        assert "Skipped to the next track" in res

        # Skip previous
        mock_applescript.reset_mock()
        res = skip_music("previous")
        mock_applescript.assert_called_once_with('tell application "Spotify" to previous track')
        assert "Skipped to the previous track" in res


def test_get_now_playing() -> None:
    # 1. Test when Spotify is paused
    with patch("verse.tools.builtin.spotify.run_applescript", return_value="paused") as mock_applescript:
        res = get_now_playing()
        mock_applescript.assert_called_once_with('tell application "Spotify" to player state')
        assert "Spotify is not currently playing" in res

    # 2. Test when Spotify is actively playing a song
    def mock_run_applescript(script: str) -> str:
        if "player state" in script:
            return "playing"
        if "name of current track" in script:
            return "Robbers"
        if "artist of current track" in script:
            return "The 1975"
        if "album of current track" in script:
            return "The 1975 (Deluxe)"
        return ""

    with patch("verse.tools.builtin.spotify.run_applescript", side_effect=mock_run_applescript) as mock_applescript:
        res = get_now_playing()
        assert "Currently playing 'Robbers' by The 1975 from the album 'The 1975 (Deluxe)'." in res
