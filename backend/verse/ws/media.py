from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import Any

logger = logging.getLogger(__name__)


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
                        return {
                            "playing": True,
                            "player": "spotify",
                            "track": track,
                            "artist": artist,
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
                        return {
                            "playing": True,
                            "player": "music",
                            "track": track,
                            "artist": artist,
                        }
    except Exception as exc:
        logger.debug("Music.app media check failed: %s", exc)

    return {
        "playing": False,
        "player": "",
        "track": "",
        "artist": "",
    }


async def media_monitor_task(ws_server: Any, interval: float = 2.0) -> None:
    """Background loop that polls macOS media states and enqueues websocket events."""
    last_state = {
        "playing": False,
        "player": "",
        "track": "",
        "artist": "",
    }
    
    # Initialize the server media state structure
    ws_server._now_playing = {
        "type": "now_playing",
        "playing": False,
        "player": "",
        "track": "",
        "artist": "",
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
            ):
                last_state = state
                msg = {
                    "type": "now_playing",
                    "playing": state["playing"],
                    "player": state["player"],
                    "track": state["track"],
                    "artist": state["artist"],
                }
                ws_server.enqueue(msg)

            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("Error in media monitor loop: %s", exc)
            await asyncio.sleep(interval)
