from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class LocalIntentMatch:
    intent: str
    confidence: float
    tool_name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    reply: str | None = None


class LocalIntentRouter:
    """Small deterministic router for high-confidence local commands."""

    _APP_ALIASES = {
        "spotify": "Spotify",
        "vs code": "Visual Studio Code",
        "vscode": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "code": "Visual Studio Code",
        "brave": "Brave Browser",
        "brave browser": "Brave Browser",
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "safari": "Safari",
    }

    def route(self, transcript: str) -> LocalIntentMatch | None:
        text = _normalize(transcript)
        if not text:
            return None

        match = self._route_control(text)
        if match is not None:
            return match

        match = self._route_time(text)
        if match is not None:
            return match

        match = self._route_pause_music(text)
        if match is not None:
            return match

        match = self._route_open_app(text)
        if match is not None:
            return match

        return self._route_play_music(text)

    def _route_control(self, text: str) -> LocalIntentMatch | None:
        if re.fullmatch(
            r"(cancel|nevermind|never mind|stop|batal|batalkan|tidak jadi|nggak jadi|gak jadi|ga jadi|sudah)",
            text,
        ):
            return LocalIntentMatch(
                intent="control.cancel",
                confidence=0.92,
                reply="Oke.",
            )
        return None

    def _route_time(self, text: str) -> LocalIntentMatch | None:
        if re.search(
            r"\b(what time|time is it|current time|jam berapa|sekarang jam|hari apa|tanggal berapa)\b",
            text,
        ):
            return LocalIntentMatch(
                intent="system.get_time",
                confidence=0.96,
                tool_name="get_time",
            )
        return None

    def _route_pause_music(self, text: str) -> LocalIntentMatch | None:
        has_music_context = any(
            token in text
            for token in ("musik", "music", "lagu", "spotify", "playback", "pause", "jeda")
        )
        if re.fullmatch(
            r"(pause|jeda|hentikan|stop|matikan)( musik| music| lagu| spotify| playback)?",
            text,
        ) and has_music_context:
            return LocalIntentMatch(
                intent="music.pause",
                confidence=0.94,
                tool_name="pause_music",
            )
        return None

    def _route_open_app(self, text: str) -> LocalIntentMatch | None:
        match = re.fullmatch(r"(open|launch|buka|jalankan) (?P<app>.+)", text)
        if match is None:
            return None

        app = self._APP_ALIASES.get(match.group("app").strip())
        if app is None:
            return None

        return LocalIntentMatch(
            intent="system.open_app",
            confidence=0.96,
            tool_name="open_app",
            arguments={"app_name": app},
        )

    def _route_play_music(self, text: str) -> LocalIntentMatch | None:
        match = re.fullmatch(
            r"(play|putar|mainkan) (?P<kind>music|musik|song|lagu|track|spotify|playlist|album|artist)(?P<tail> .+)?",
            text,
        )
        if match is None:
            return None

        kind = match.group("kind")
        tail = (match.group("tail") or "").strip()
        query = _strip_music_prefix(tail)
        
        arguments = {}
        if query:
            arguments["query"] = query

        type_mapping = {
            "playlist": "playlist",
            "album": "album",
            "artist": "artist",
        }
        if kind in type_mapping:
            arguments["type"] = type_mapping[kind]
        elif kind in ("song", "lagu", "track"):
            arguments["type"] = "track"

        return LocalIntentMatch(
            intent="music.play",
            confidence=0.9 if query else 0.86,
            tool_name="play_music",
            arguments=arguments,
        )


def _normalize(text: str) -> str:
    lowered = text.lower().strip()
    lowered = re.sub(r"[^\w\s]", " ", lowered)
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip()


def _strip_music_prefix(text: str) -> str:
    text = re.sub(r"^(music|musik|song|lagu|track|playlist|album|artist)\b", "", text).strip()
    text = re.sub(r"^(yang|for|about|tentang)\b", "", text).strip()
    return text
