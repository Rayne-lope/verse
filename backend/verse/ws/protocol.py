from __future__ import annotations

from typing import TYPE_CHECKING, Any

from verse.state import StateChangedEvent

if TYPE_CHECKING:
    from verse.config import AppConfig

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


MSG_PIPELINE_EVENT = "pipeline_event"


def pipeline_event_message(stage: str, event: str, **kwargs: Any) -> dict[str, Any]:
    return {
        "type": MSG_PIPELINE_EVENT,
        "stage": stage,
        "event": event,
        **kwargs
    }


MSG_CONFIG_DATA = "config_data"
MSG_CONFIG_UPDATED = "config_updated"
MSG_API_KEY_SET = "api_key_set"


def config_data_message(config: "AppConfig", api_keys: dict[str, bool]) -> dict[str, Any]:
    return {
        "type": MSG_CONFIG_DATA,
        "config": {
            "tts": {
                "provider": config.tts.provider,
                "voice_id": config.tts.voice_id,
                "speed": config.tts.speed,
            },
            "stt": {
                "language": config.stt.language,
            },
            "llm": {
                "provider": config.llm.provider,
                "model": config.llm.model,
                "temperature": config.llm.temperature,
                "max_history": config.llm.max_history,
            },
            "hotkey": {
                "trigger": config.hotkey.trigger,
            },
            "memory": {
                "enabled": config.memory.enabled,
                "max_facts": config.memory.max_facts,
            },
        },
        "api_keys": api_keys,
    }


def config_updated_message(success: bool, error: str | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"type": MSG_CONFIG_UPDATED, "success": success}
    if error is not None:
        msg["error"] = error
    return msg


def api_key_set_message(key_name: str, success: bool) -> dict[str, Any]:
    return {"type": MSG_API_KEY_SET, "key_name": key_name, "success": success}
