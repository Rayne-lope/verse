from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LatencyEvent:
    name: str
    ts: float
    data: dict[str, Any] = field(default_factory=dict)


class LatencyTracker:
    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.t0 = time.perf_counter()
        self.events: list[LatencyEvent] = []
        self.metadata: dict[str, Any] = {}

    def mark(self, event_name: str, **data: Any) -> None:
        self.events.append(LatencyEvent(name=event_name, ts=time.perf_counter(), data=data))

    def set_metadata(self, **data: Any) -> None:
        self.metadata.update(data)

    def summary(self) -> dict[str, Any]:
        event_counts = self._event_counts()
        provider = self.metadata.get("provider") or {}
        cancelled = bool(
            self.metadata.get("cancelled")
            or self._first("barge_in_detected") is not None
            or self._first("cancel_start") is not None
        )

        return {
            "turn_id": self.turn_id,
            "audio_ms": self.metadata.get("audio_ms"),
            "transcript_chars": self.metadata.get("transcript_chars", 0),
            "provider": {
                "stt": provider.get("stt"),
                "llm": provider.get("llm"),
                "tts": provider.get("tts"),
            },
            "latency": {
                "vad_to_stt_start_ms": self._ms_between("vad_speech_end", "stt_start"),
                "stt_ms": self._ms_between("stt_start", "stt_final"),
                "llm_first_token_ms": self._ms_between("llm_request_start", "llm_first_token"),
                "llm_total_ms": self._ms_between("llm_request_start", "llm_done"),
                "tts_first_audio_ms": self._ms_between("tts_request_start", "tts_first_audio"),
                "tts_total_ms": self._ms_between("tts_request_start", "tts_done"),
                "playback_ms": self._ms_between("playback_start", "playback_done"),
                "speech_end_to_first_audio_ms": self._speech_end_to_first_audio_ms(),
                "tools_ms": self._tool_total_ms(),
                "cancellation_ms": self._ms_between("cancel_start", "cancel_done"),
            },
            "tool_count": self.metadata.get("tool_count", event_counts.get("tool_start", 0)),
            "cancelled": cancelled,
            "events": [
                {
                    "name": event.name,
                    "ms": round((event.ts - self.t0) * 1000),
                    "data": event.data,
                }
                for event in self.events
            ],
        }

    def _first(self, name: str) -> LatencyEvent | None:
        for event in self.events:
            if event.name == name:
                return event
        return None

    def _last(self, name: str) -> LatencyEvent | None:
        for event in reversed(self.events):
            if event.name == name:
                return event
        return None

    def _ms_between(self, start_name: str, end_name: str) -> int | None:
        start = self._first(start_name)
        end = self._last(end_name)
        if start is None or end is None or end.ts < start.ts:
            return None
        return round((end.ts - start.ts) * 1000)

    def _speech_end_to_first_audio_ms(self) -> int | None:
        end = self._last("vad_speech_end") or self._last("audio_wav_ready")
        first_audio = self._first("tts_first_audio")
        if end is None or first_audio is None or first_audio.ts < end.ts:
            return None
        return round((first_audio.ts - end.ts) * 1000)

    def _tool_total_ms(self) -> int | None:
        total = 0.0
        pending: LatencyEvent | None = None
        saw_tool = False
        for event in self.events:
            if event.name == "tool_start":
                pending = event
                saw_tool = True
            elif event.name == "tool_done" and pending is not None:
                total += max(0.0, event.ts - pending.ts)
                pending = None
        if not saw_tool:
            return 0
        return round(total * 1000)

    def _event_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self.events:
            counts[event.name] = counts.get(event.name, 0) + 1
        return counts
