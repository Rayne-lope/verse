from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Simple in-memory artwork cache keyed by (player, track, artist)
_artwork_cache: dict[tuple[str, str, str], str | None] = {}


def _fetch_spotify_artwork(track: str, artist: str) -> str | None:
    """Get Spotify album art URL for the current track.

    Strategy:
    1. Ask AppleScript for the spotify:track:ID URI (fast, local).
    2. Use the Spotify Web API /v1/tracks/{id} with client credentials to get
       album images.  Falls back to a search query if credentials are absent.
    """
    try:
        # Step 1 – get the Spotify track URI via AppleScript
        uri_cmd = (
            'if application "Spotify" is running then '
            'tell application "Spotify" to get (spotify url of current track as text)'
        )
        res = subprocess.run(
            ["osascript", "-e", uri_cmd],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        track_id: str | None = None
        if res.returncode == 0:
            raw = res.stdout.strip()
            # raw is something like "spotify:track:4iV5W9uYEdYUVa79Axb7Rh"
            if raw.startswith("spotify:track:"):
                track_id = raw.split(":")[-1]

        # Step 2 – Spotify API (requires client credentials)
        try:
            from verse.tools.builtin.spotify import _spotify_credentials, _get_access_token  # noqa: PLC0415
            client_id, client_secret = _spotify_credentials()
            if client_id and client_secret:
                token = _get_access_token(client_id, client_secret)
                if track_id:
                    url = f"https://api.spotify.com/v1/tracks/{track_id}"
                else:
                    # Fallback: search by track + artist name
                    q = urllib.parse.urlencode({"q": f"{track} {artist}", "type": "track", "limit": 1})
                    url = f"https://api.spotify.com/v1/search?{q}"

                req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())

                # /v1/tracks/{id} returns the track directly; /v1/search wraps it
                if "album" in data:
                    images = data["album"].get("images", [])
                else:
                    items = data.get("tracks", {}).get("items", [])
                    images = items[0]["album"].get("images", []) if items else []

                if images:
                    # images are sorted largest → smallest; use smallest (≥64px) for notch
                    return images[-1]["url"]
        except Exception as exc:
            logger.debug("Spotify API artwork fetch failed: %s", exc)
    except Exception as exc:
        logger.debug("Spotify artwork fetch failed: %s", exc)
    return None


def _fetch_itunes_artwork(track: str, artist: str) -> str | None:
    """Get album art URL from the iTunes Search API (no auth required)."""
    try:
        term = urllib.parse.quote_plus(f"{track} {artist}")
        url = f"https://itunes.apple.com/search?term={term}&entity=song&limit=1&media=music"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        results = data.get("results", [])
        if results:
            # artworkUrl100 is 100×100; swap for 300×300
            art = results[0].get("artworkUrl100", "")
            return art.replace("100x100bb", "300x300bb") if art else None
    except Exception as exc:
        logger.debug("iTunes artwork fetch failed: %s", exc)
    return None


def _get_artwork_url(player: str, track: str, artist: str) -> str | None:
    """Return a cached artwork URL, fetching it on first call for each track."""
    key = (player, track, artist)
    if key in _artwork_cache:
        return _artwork_cache[key]

    url: str | None = None
    if player == "spotify":
        url = _fetch_spotify_artwork(track, artist)
    if url is None and player == "music":
        url = _fetch_itunes_artwork(track, artist)
    # For Spotify without API creds, also try iTunes as fallback
    if url is None and player == "spotify":
        url = _fetch_itunes_artwork(track, artist)

    _artwork_cache[key] = url
    return url


def check_media_state() -> dict[str, Any]:
    """Check running player state of Spotify and Music.app on macOS.

    Uses non-blocking AppleScript check to get player state, track title,
    and artist. Delimits components with '|||' to prevent comma splitting errors.
    """
    # Check Spotify
    try:
        cmd = 'if application "Spotify" is running then tell application "Spotify" to get (player state as text) & "|||" & (name of current track as text) & "|||" & (artist of current track as text)'
        res = subprocess.run(
            ["osascript", "-e", cmd],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            if out and "|||" in out:
                parts = out.split("|||")
                if len(parts) >= 1:
                    state = parts[0].strip()
                    track = parts[1].strip() if len(parts) >= 2 else ""
                    artist = parts[2].strip() if len(parts) >= 3 else ""
                    if state == "playing":
                        artwork_url = _get_artwork_url("spotify", track, artist)
                        return {
                            "playing": True,
                            "player": "spotify",
                            "track": track,
                            "artist": artist,
                            "artwork_url": artwork_url,
                        }
    except Exception as exc:
        logger.debug("Spotify media check failed: %s", exc)

    # Check Music.app
    try:
        cmd = 'if application "Music" is running then tell application "Music" to get (player state as text) & "|||" & (name of current track as text) & "|||" & (artist of current track as text)'
        res = subprocess.run(
            ["osascript", "-e", cmd],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if res.returncode == 0:
            out = res.stdout.strip()
            if out and "|||" in out:
                parts = out.split("|||")
                if len(parts) >= 1:
                    state = parts[0].strip()
                    track = parts[1].strip() if len(parts) >= 2 else ""
                    artist = parts[2].strip() if len(parts) >= 3 else ""
                    if state == "playing":
                        artwork_url = _get_artwork_url("music", track, artist)
                        return {
                            "playing": True,
                            "player": "music",
                            "track": track,
                            "artist": artist,
                            "artwork_url": artwork_url,
                        }
    except Exception as exc:
        logger.debug("Music.app media check failed: %s", exc)

    return {
        "playing": False,
        "player": "",
        "track": "",
        "artist": "",
        "artwork_url": None,
    }


async def media_monitor_task(ws_server: Any, interval: float = 2.0) -> None:
    """Background loop that polls macOS media states and enqueues websocket events."""
    last_state: dict[str, Any] = {
        "playing": False,
        "player": "",
        "track": "",
        "artist": "",
        "artwork_url": None,
    }

    # Initialize the server media state structure
    ws_server._now_playing = {
        "type": "now_playing",
        "playing": False,
        "player": "",
        "track": "",
        "artist": "",
        "artwork_url": None,
    }

    while True:
        try:
            # Shift blocking subprocess task off the main event loop
            state = await asyncio.to_thread(check_media_state)

            if (
                state["playing"] != last_state["playing"]
                or state["player"] != last_state["player"]
                or state["track"] != last_state["track"]
                or state["artist"] != last_state["artist"]
                or state["artwork_url"] != last_state["artwork_url"]
            ):
                last_state = state
                msg = {
                    "type": "now_playing",
                    "playing": state["playing"],
                    "player": state["player"],
                    "track": state["track"],
                    "artist": state["artist"],
                    "artwork_url": state["artwork_url"],
                }
                ws_server.enqueue(msg)

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("Error in media monitor loop: %s", exc)
            await asyncio.sleep(interval)
