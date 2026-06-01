from __future__ import annotations

import base64
import html
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from typing import Any

from verse.config import load_config
from verse.persistence.keychain import get_api_key

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"


def run_applescript(script: str) -> str:
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def open_uri(uri: str) -> None:
    subprocess.run(["open", uri], check=True)


def play_music(query: str | None = None, type: str = "track") -> str:
    if not (query and query.strip()):
        run_applescript('tell application "Spotify" to play')
        return "Resumed Spotify playback."

    query = query.strip()

    if type == "playlist":
        try:
            config = load_config()
            configured_user = config.tools.spotify_username
            if configured_user:
                clean_user = _get_clean_spotify_username(configured_user)
                if clean_user:
                    found_user_playlist = _find_user_playlist(query, clean_user)
                    if found_user_playlist is not None:
                        uri, name, artist = found_user_playlist
                        run_applescript(f'tell application "Spotify" to play track "{uri}"')
                        return f"Playing playlist '{name}' by {artist} on Spotify."
        except Exception:
            pass
    client_id, client_secret = _spotify_credentials()
    if client_id and client_secret:
        token = _get_access_token(client_id, client_secret)
        found = _search_spotify(query, type, token)
        if found is not None:
            uri, name, artist = found
            run_applescript(f'tell application "Spotify" to play track "{uri}"')
            if type == "playlist":
                return f"Playing playlist '{name}' by {artist} on Spotify."
            elif type == "album":
                return f"Playing album '{name}' by {artist} on Spotify."
            elif type == "artist":
                return f"Playing artist '{name}' on Spotify."
            return f"Playing '{name}' by {artist} on Spotify."
        return f"No Spotify {type} found for '{query}'."

    # No API credentials: fall back to opening the search view + resume.
    open_uri(f"spotify:search:{urllib.parse.quote(query)}")
    run_applescript('tell application "Spotify" to play')
    return (
        f"Opened Spotify search for '{query}'. "
        "Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to play tracks directly."
    )


def pause_music() -> str:
    run_applescript('tell application "Spotify" to pause')
    return "Paused Spotify playback."



def _spotify_credentials() -> tuple[str | None, str | None]:
    client_id = (
        os.getenv("SPOTIFY_CLIENT_ID")
        or get_api_key("spotify_client_id")
    )
    client_secret = (
        os.getenv("SPOTIFY_CLIENT_SECRET")
        or get_api_key("spotify_client_secret")
    )
    return client_id, client_secret


def _get_access_token(client_id: str, client_secret: str) -> str:
    auth = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
    request = urllib.request.Request(
        TOKEN_URL,
        data=data,
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["access_token"])


def _search_spotify(query: str, search_type: str, token: str) -> tuple[str, str, str] | None:
    params = urllib.parse.urlencode({"q": query, "type": search_type, "limit": 10})
    request = urllib.request.Request(
        f"{SEARCH_URL}?{params}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return _parse_first_item(payload, search_type)


def _parse_first_item(payload: dict[str, Any], search_type: str) -> tuple[str, str, str] | None:
    key = f"{search_type}s"
    items = payload.get(key, {}).get("items", [])
    items = [item for item in items if item is not None]
    if not items:
        return None
    item = items[0]
    uri = item["uri"]
    name = item.get("name", "")

    if search_type == "track":
        artists = item.get("artists", [])
        artist = artists[0]["name"] if artists else "Unknown"
    elif search_type == "playlist":
        owner = item.get("owner", {})
        artist = owner.get("display_name") or owner.get("id") or "Spotify"
    elif search_type == "album":
        artists = item.get("artists", [])
        artist = artists[0]["name"] if artists else "Unknown"
    elif search_type == "artist":
        artist = "Artist"
    else:
        artist = "Unknown"

    return uri, name, artist


def _parse_first_track(payload: dict[str, Any]) -> tuple[str, str, str] | None:
    return _parse_first_item(payload, "track")


def _get_clean_spotify_username(configured: str) -> str:
    configured = configured.strip()
    if not configured:
        return ""
    if "spotify.com/user/" in configured:
        parts = configured.split("spotify.com/user/")
        if len(parts) > 1:
            return parts[1].split("?")[0].split("/")[0].strip()
    return configured


def _fetch_user_playlists(user_id: str) -> list[tuple[str, str]]:
    url = f"https://open.spotify.com/user/{user_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html_content = response.read().decode("utf-8")
    except Exception:
        return []

    matches = re.findall(
        r'href="/playlist/([a-zA-Z0-9]+)"[^>]*>.*?<span[^>]*>(.*?)</span>',
        html_content,
        re.DOTALL
    )

    playlists = []
    for playlist_id, name in matches:
        unescaped_name = html.unescape(name).strip()
        playlists.append((playlist_id, unescaped_name))
    return playlists


def _find_user_playlist(query: str, user_id: str) -> tuple[str, str, str] | None:
    playlists = _fetch_user_playlists(user_id)
    if not playlists:
        return None

    query_lower = query.lower()

    # 1. Look for case-insensitive exact match
    for playlist_id, name in playlists:
        if name.lower() == query_lower:
            return f"spotify:playlist:{playlist_id}", name, "You"

    # 2. Look for case-insensitive substring match
    for playlist_id, name in playlists:
        if query_lower in name.lower() or name.lower() in query_lower:
            return f"spotify:playlist:{playlist_id}", name, "You"

    # 3. Token-based matching (fuzzy fallback)
    query_tokens = _normalize_tokens(query)
    query_tokens.discard("moriant")
    query_tokens.discard("morian")
    query_tokens.discard(user_id.lower())

    if not query_tokens:
        return None

    best_match = None
    max_score = 0

    for playlist_id, name in playlists:
        playlist_tokens = _normalize_tokens(name)
        score = 0
        for qt in query_tokens:
            for pt in playlist_tokens:
                if qt == pt:
                    score += 2  # Exact token match
                elif (len(qt) >= 4 or len(pt) >= 4) and (qt.startswith(pt) or pt.startswith(qt)):
                    score += 1  # Prefix match (e.g. lana and lanaa)

        if score > max_score:
            max_score = score
            best_match = (f"spotify:playlist:{playlist_id}", name, "You")

    # Only return the match if we have a significant overlap
    if max_score >= 1:
        return best_match

    return None


def _normalize_tokens(text: str) -> set[str]:
    text = text.lower()
    tokens = re.findall(r'[a-z0-9]+', text)
    stop_words = {
        "my", "to", "the", "a", "of", "in", "for", "from", "dari", "yang",
        "user", "username", "spotify", "playlist", "album", "artist",
        "song", "track", "music", "musik", "lagu"
    }
    return {t for t in tokens if t not in stop_words}


def set_spotify_volume(level: int) -> str:
    """Set the Spotify playback volume level (0-100)."""
    try:
        target = max(0, min(100, int(level)))
        run_applescript(f'tell application "Spotify" to set sound volume to {target}')
        return f"Spotify volume set to {target}%."
    except Exception as exc:
        return f"Could not set Spotify volume: {exc}. Make sure Spotify is running."


def get_spotify_volume() -> str:
    """Get the current Spotify playback volume level (0-100)."""
    try:
        vol = run_applescript('tell application "Spotify" to get sound volume')
        return f"Spotify volume is at {vol}%."
    except Exception as exc:
        return f"Could not get Spotify volume: {exc}. Make sure Spotify is running."


def skip_music(direction: str = "next") -> str:
    """Skip to the next or previous track on Spotify."""
    try:
        clean_dir = direction.strip().lower()
        if clean_dir == "previous":
            run_applescript('tell application "Spotify" to previous track')
            return "Skipped to the previous track."
        else:
            run_applescript('tell application "Spotify" to next track')
            return "Skipped to the next track."
    except Exception as exc:
        return f"Could not skip music: {exc}. Make sure Spotify is running."


def get_now_playing() -> str:
    """Retrieve details about the track currently playing on Spotify."""
    try:
        state = run_applescript('tell application "Spotify" to player state')
        if state != "playing":
            return "Spotify is not currently playing."

        name = run_applescript('tell application "Spotify" to name of current track')
        artist = run_applescript('tell application "Spotify" to artist of current track')
        album = run_applescript('tell application "Spotify" to album of current track')
        return f"Currently playing '{name}' by {artist} from the album '{album}'."
    except Exception as exc:
        return f"Could not read player state: {exc}. Make sure Spotify is running."


