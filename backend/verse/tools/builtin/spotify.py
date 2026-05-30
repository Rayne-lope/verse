from __future__ import annotations

import base64
import json
import os
import subprocess
import urllib.parse
import urllib.request
from typing import Any

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
    params = urllib.parse.urlencode({"q": query, "type": search_type, "limit": 1})
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

