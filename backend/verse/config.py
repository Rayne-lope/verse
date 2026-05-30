from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib


DEFAULT_CONFIG_PATH = Path("~/.verse/config.toml").expanduser()


@dataclass(frozen=True)
class HotkeyConfig:
    trigger: str = "alt+space"
    conversation_trigger: str = "shift+alt+space"
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
class VADConfig:
    enabled: bool = True
    model_path: str = "~/.verse/models/silero_vad.onnx"
    start_threshold: float = 0.55
    end_threshold: float = 0.35
    speech_start_ms: int = 160
    min_utterance_ms: int = 500
    end_silence_ms: int = 1400
    max_utterance_ms: int = 20000
    pre_roll_ms: int = 300
    followup_timeout_s: float = 5.0


@dataclass(frozen=True)
class GeminiLiveConfig:
    model: str = "gemini-2.0-flash-live-001"
    voice_name: str = "Puck"
    language_code: str = "en-US"


@dataclass(frozen=True)
class VoiceConfig:
    engine: str = "classic_pipeline"  # "classic_pipeline" | "gemini_live"
    gemini_live: GeminiLiveConfig = field(default_factory=GeminiLiveConfig)


@dataclass(frozen=True)
class AppConfig:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)


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
    vad = raw_config.get("vad", {})
    voice_raw = raw_config.get("voice", {})
    gl_raw = voice_raw.get("gemini_live", {})

    return AppConfig(
        hotkey=HotkeyConfig(
            trigger=str(hotkey.get("trigger", HotkeyConfig.trigger)),
            conversation_trigger=str(hotkey.get("conversation_trigger", HotkeyConfig.conversation_trigger)),
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
        vad=VADConfig(
            enabled=bool(vad.get("enabled", VADConfig.enabled)),
            model_path=str(vad.get("model_path", VADConfig.model_path)),
            start_threshold=float(vad.get("start_threshold", VADConfig.start_threshold)),
            end_threshold=float(vad.get("end_threshold", VADConfig.end_threshold)),
            speech_start_ms=int(vad.get("speech_start_ms", VADConfig.speech_start_ms)),
            min_utterance_ms=int(vad.get("min_utterance_ms", VADConfig.min_utterance_ms)),
            end_silence_ms=int(vad.get("end_silence_ms", VADConfig.end_silence_ms)),
            max_utterance_ms=int(vad.get("max_utterance_ms", VADConfig.max_utterance_ms)),
            pre_roll_ms=int(vad.get("pre_roll_ms", VADConfig.pre_roll_ms)),
            followup_timeout_s=float(vad.get("followup_timeout_s", VADConfig.followup_timeout_s)),
        ),
        voice=VoiceConfig(
            engine=str(voice_raw.get("engine", VoiceConfig.engine)),
            gemini_live=GeminiLiveConfig(
                model=str(gl_raw.get("model", GeminiLiveConfig.model)),
                voice_name=str(gl_raw.get("voice_name", GeminiLiveConfig.voice_name)),
                language_code=str(gl_raw.get("language_code", GeminiLiveConfig.language_code)),
            ),
        ),
    )
