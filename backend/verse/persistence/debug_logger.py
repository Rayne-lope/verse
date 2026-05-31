from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


class DebugSessionLogger:
    """Captures and stores metadata, timeline data, pipeline events, audio,

    metrics, and logs for a voice assistant debug session.
    """

    def __init__(self, base_dir: str | Path = "~/.verse/debug_sessions") -> None:
        self.base_dir = Path(base_dir).expanduser()
        self.session_id = f"session_{int(time.time())}_{uuid.uuid4().hex[:8]}"
        self.session_dir = self.base_dir / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.turn_counter = 0

        self._write_metadata()

    def _write_metadata(self) -> None:
        metadata = {
            "session_id": self.session_id,
            "started_at": time.time(),
            "os": "macos",
        }
        with open(self.session_dir / "session.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

    def new_turn(self) -> int:
        self.turn_counter += 1
        turn_dir = self.get_turn_dir(self.turn_counter)
        turn_dir.mkdir(parents=True, exist_ok=True)
        return self.turn_counter

    def get_turn_dir(self, turn_id: int) -> Path:
        return self.session_dir / f"turn_{turn_id:03d}"

    def log_input_audio(self, turn_id: int, audio_bytes: bytes) -> None:
        turn_dir = self.get_turn_dir(turn_id)
        with open(turn_dir / "input.wav", "wb") as f:
            f.write(audio_bytes)

    def log_output_audio(self, turn_id: int, audio_bytes: bytes) -> None:
        turn_dir = self.get_turn_dir(turn_id)
        with open(turn_dir / "output.wav", "wb") as f:
            f.write(audio_bytes)

    def log_vad_timeline(self, turn_id: int, timeline: list[dict[str, Any]]) -> None:
        turn_dir = self.get_turn_dir(turn_id)
        with open(turn_dir / "vad_timeline.jsonl", "w", encoding="utf-8") as f:
            for entry in timeline:
                f.write(json.dumps(entry) + "\n")

    def log_pipeline_events(self, turn_id: int, events: list[dict[str, Any]]) -> None:
        turn_dir = self.get_turn_dir(turn_id)
        with open(turn_dir / "pipeline_events.jsonl", "w", encoding="utf-8") as f:
            for entry in events:
                f.write(json.dumps(entry) + "\n")

    def log_llm_transaction(
        self, turn_id: int, messages: list[dict[str, Any]], response: dict[str, Any]
    ) -> None:
        turn_dir = self.get_turn_dir(turn_id)
        redacted_messages = self._redact(messages)
        redacted_response = self._redact(response)

        transaction = {
            "messages": redacted_messages,
            "response": redacted_response,
        }
        with open(turn_dir / "llm_transaction.json", "w", encoding="utf-8") as f:
            json.dump(transaction, f, indent=2)

    def log_metrics(self, turn_id: int, metrics: dict[str, Any]) -> None:
        turn_dir = self.get_turn_dir(turn_id)
        with open(turn_dir / "metrics.json", "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)

    def log_latency_summary(self, turn_id: int, summary: dict[str, Any]) -> None:
        turn_dir = self.get_turn_dir(turn_id)
        with open(turn_dir / "latency_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    def log_error(
        self,
        turn_id: int,
        error_type: str,
        message: str,
        traceback: str | None = None,
    ) -> None:
        turn_dir = self.get_turn_dir(turn_id)
        err = {
            "timestamp": time.time(),
            "error_type": error_type,
            "message": message,
            "traceback": traceback,
        }
        with open(turn_dir / "errors.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(err) + "\n")

    def _redact(self, data: Any) -> Any:
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if any(
                    sec in k.lower()
                    for sec in ("key", "secret", "token", "auth", "password")
                ):
                    redacted[k] = "[REDACTED]"
                else:
                    redacted[k] = self._redact(v)
            return redacted
        elif isinstance(data, list):
            return [self._redact(item) for item in data]
        return data
