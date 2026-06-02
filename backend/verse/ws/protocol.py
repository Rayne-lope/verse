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
MSG_MIC_STATUS = "mic_status"

# Streaming STT partial transcript events
MSG_USER_PARTIAL_TRANSCRIPT = "user_partial_transcript"
MSG_USER_FINAL_TRANSCRIPT = "user_final_transcript"


def state_change_message(event: StateChangedEvent, *, turn_id: str | int | None = None) -> dict[str, Any]:
    msg = {"type": MSG_STATE_CHANGE, "state": str(event.state)}
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg


def audio_level_message(level: float, *, turn_id: str | int | None = None) -> dict[str, Any]:
    msg = {"type": MSG_AUDIO_LEVEL, "level": float(level)}
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg


def transcript_message(text: str, *, partial: bool = False, turn_id: str | int | None = None) -> dict[str, Any]:
    msg = {"type": MSG_TRANSCRIPT, "text": text, "partial": partial}
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg


def assistant_text_message(text: str, *, turn_id: str | int | None = None) -> dict[str, Any]:
    msg = {"type": MSG_ASSISTANT_TEXT, "text": text}
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg


def tool_executed_message(name: str, result: Any, *, turn_id: str | int | None = None) -> dict[str, Any]:
    msg = {"type": MSG_TOOL_EXECUTED, "name": name, "result": result}
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg


def error_message(message: str, *, recoverable: bool = True, turn_id: str | int | None = None) -> dict[str, Any]:
    msg = {"type": MSG_ERROR, "message": message, "recoverable": recoverable}
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg


def mic_status_message(active: bool, mode: str = "off") -> dict[str, Any]:
    return {"type": MSG_MIC_STATUS, "active": bool(active), "mode": mode}


MSG_PIPELINE_EVENT = "pipeline_event"


def pipeline_event_message(stage: str, event: str, *, turn_id: str | int | None = None, **kwargs: Any) -> dict[str, Any]:
    msg = {
        "type": MSG_PIPELINE_EVENT,
        "stage": stage,
        "event": event,
        **kwargs
    }
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg


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
                "model": config.tts.model,
                "base_url": config.tts.base_url,
            },
            "stt": {
                "language": config.stt.language,
                "partial_mode": getattr(config.stt, "partial_mode", "off"),
            },
            "llm": {
                "provider": config.llm.provider,
                "model": config.llm.model,
                "base_url": config.llm.base_url,
                "temperature": config.llm.temperature,
                "max_history": config.llm.max_history,
            },
            "hotkey": {
                "trigger": config.hotkey.trigger,
            },
            "always_on": {
                "enabled": config.always_on.enabled,
                "keyword": config.always_on.keyword,
                "keyword_path": config.always_on.keyword_path,
                "model_path": config.always_on.model_path,
                "sensitivity": config.always_on.sensitivity,
                "device": config.always_on.device,
            },
            "memory": {
                "enabled": config.memory.enabled,
                "max_facts": config.memory.max_facts,
            },
            "voice": {
                "engine": config.voice.engine,
                "low_latency": getattr(config.voice, "low_latency", True),
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


# --- Streaming STT messages ------------------------------------------------


def user_partial_transcript_message(
    text: str, stability: float | None = None, *, turn_id: str | int | None = None
) -> dict[str, Any]:
    msg = {"type": MSG_USER_PARTIAL_TRANSCRIPT, "text": text, "stability": stability}
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg


def user_final_transcript_message(text: str, *, turn_id: str | int | None = None) -> dict[str, Any]:
    msg = {"type": MSG_USER_FINAL_TRANSCRIPT, "text": text}
    if turn_id is not None:
        msg["turn_id"] = turn_id
    return msg
