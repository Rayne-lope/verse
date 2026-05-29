from __future__ import annotations

from typing import Any

from verse.state import StateChangedEvent

MSG_STATE_CHANGE = "state_change"
MSG_AUDIO_LEVEL = "audio_level"
MSG_TRANSCRIPT = "transcript"
MSG_ASSISTANT_TEXT = "assistant_text"
MSG_TOOL_EXECUTED = "tool_executed"
MSG_ERROR = "error"


def state_change_message(event: StateChangedEvent) -> dict[str, Any]:
    return {"type": MSG_STATE_CHANGE, "state": str(event.state)}


def audio_level_message(level: float) -> dict[str, Any]:
    return {"type": MSG_AUDIO_LEVEL, "level": float(level)}


def transcript_message(text: str, *, partial: bool = False) -> dict[str, Any]:
    return {"type": MSG_TRANSCRIPT, "text": text, "partial": partial}


def assistant_text_message(text: str) -> dict[str, Any]:
    return {"type": MSG_ASSISTANT_TEXT, "text": text}


def tool_executed_message(name: str, result: Any) -> dict[str, Any]:
    return {"type": MSG_TOOL_EXECUTED, "name": name, "result": result}


def error_message(message: str, *, recoverable: bool = True) -> dict[str, Any]:
    return {"type": MSG_ERROR, "message": message, "recoverable": recoverable}
