from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib


DEFAULT_CONFIG_PATH = Path("~/.verse/config.toml").expanduser()


@dataclass(frozen=True)
class HotkeyConfig:
    trigger: str = "alt+space"
    mode: str = "push_to_talk"
    conversation_mode: bool = True


@dataclass(frozen=True)
class STTConfig:
    provider: str = "groq"
    language: str = "auto"


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    temperature: float = 0.7
    max_history: int = 10


@dataclass(frozen=True)
class TTSConfig:
    provider: str = "edge-tts"
    voice_id: str = "id-ID-GadisNeural"
    speed: float = 1.0


@dataclass(frozen=True)
class ToolsConfig:
    enabled: list[str] = field(
        default_factory=lambda: [
            "play_music",
            "pause_music",
            "open_app",
            "web_search",
            "open_url",
            "get_weather",
            "take_note",
            "read_note",
            "list_notes",
            "read_calendar",
            "read_reminders",
            "add_reminder",
        ]
    )
    spotify_client_id: str = ""


@dataclass(frozen=True)
class AppConfig:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).expanduser() if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return AppConfig()

    with config_path.open("rb") as config_file:
        raw_config = tomllib.load(config_file)

    return config_from_mapping(raw_config)


def config_from_mapping(raw_config: dict[str, Any]) -> AppConfig:
    hotkey = raw_config.get("hotkey", {})
    stt = raw_config.get("stt", {})
    llm = raw_config.get("llm", {})
    tts = raw_config.get("tts", {})
    tools = raw_config.get("tools", {})

    return AppConfig(
        hotkey=HotkeyConfig(
            trigger=str(hotkey.get("trigger", HotkeyConfig.trigger)),
            mode=str(hotkey.get("mode", HotkeyConfig.mode)),
            conversation_mode=bool(hotkey.get("conversation_mode", HotkeyConfig.conversation_mode)),
        ),
        stt=STTConfig(
            provider=str(stt.get("provider", STTConfig.provider)),
            language=str(stt.get("language", STTConfig.language)),
        ),
        llm=LLMConfig(
            provider=str(llm.get("provider", LLMConfig.provider)),
            model=str(llm.get("model", LLMConfig.model)),
            base_url=str(llm.get("base_url", LLMConfig.base_url)),
            temperature=float(llm.get("temperature", LLMConfig.temperature)),
            max_history=int(llm.get("max_history", LLMConfig.max_history)),
        ),
        tts=TTSConfig(
            provider=str(tts.get("provider", TTSConfig.provider)),
            voice_id=str(tts.get("voice_id", TTSConfig.voice_id)),
            speed=float(tts.get("speed", TTSConfig.speed)),
        ),
        tools=ToolsConfig(
            enabled=list(tools.get("enabled", ToolsConfig().enabled)),
            spotify_client_id=str(
                tools.get("spotify_client_id", ToolsConfig.spotify_client_id)
            ),
        ),
    )
