import subprocess
from unittest.mock import MagicMock, patch

from verse.ws.media import check_media_state


def test_check_media_state_spotify_playing():
    """Verify check_media_state returns Spotify info if active."""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "playing|||Midnight City|||M83\n"
    
    with patch("subprocess.run", return_value=mock_res) as mock_run:
        state = check_media_state()
        assert state["playing"] is True
        assert state["player"] == "spotify"
        assert state["track"] == "Midnight City"
        assert state["artist"] == "M83"
        
        # Verify first call checked Spotify
        mock_run.assert_any_call(
            ["osascript", "-e", 'if application "Spotify" is running then tell application "Spotify" to get (player state as text) & "|||" & (name of current track as text) & "|||" & (artist of current track as text)'],
            capture_output=True,
            text=True,
            timeout=2.0
        )


def test_check_media_state_spotify_paused_music_playing():
    """Verify check_media_state falls back to Music.app if Spotify is paused."""
    mock_spotify_res = MagicMock()
    mock_spotify_res.returncode = 0
    mock_spotify_res.stdout = "paused|||Let Me Love You|||DJ Snake\n"
    
    mock_music_res = MagicMock()
    mock_music_res.returncode = 0
    mock_music_res.stdout = "playing|||Blank Space|||Taylor Swift\n"
    
    def side_effect(cmd, **kwargs):
        if "Spotify" in cmd[2]:
            return mock_spotify_res
        if "Music" in cmd[2]:
            return mock_music_res
        raise ValueError("Unexpected command")

    with patch("subprocess.run", side_effect=side_effect) as mock_run:
        state = check_media_state()
        assert state["playing"] is True
        assert state["player"] == "music"
        assert state["track"] == "Blank Space"
        assert state["artist"] == "Taylor Swift"


def test_check_media_state_none_playing():
    """Verify check_media_state returns not playing if both are idle/paused."""
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "\n"  # not running or empty

    with patch("subprocess.run", return_value=mock_res):
        state = check_media_state()
        assert state["playing"] is False
        assert state["player"] == ""
        assert state["track"] == ""
        assert state["artist"] == ""
