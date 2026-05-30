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
            "complete_reminder",
            "create_event",
            "send_message",
            "find_contact",
            "run_shortcut",
            "list_shortcuts",
            "remember",
        ]
    )
    spotify_client_id: str = ""
    spotify_username: str = ""


@dataclass(frozen=True)
class IntentConfig:
    local_router_enabled: bool = True
    local_router_confidence_threshold: float = 0.75


@dataclass(frozen=True)
class VADConfig:
    enabled: bool = True
    model_path: str = "~/.verse/models/silero_vad.onnx"
    start_threshold: float = 0.55
    end_threshold: float = 0.35
    rms_fallback_enabled: bool = True
    rms_start_level: float = 0.03
    rms_end_level: float = 0.02
    speech_start_ms: int = 160
    min_utterance_ms: int = 500
    end_silence_ms: int = 1400
    max_utterance_ms: int = 20000
    pre_roll_ms: int = 300
    followup_timeout_s: float = 5.0


@dataclass(frozen=True)
class GeminiLiveConfig:
    model: str = "gemini-2.5-flash-preview-native-audio-dialog"
    voice_name: str = "Puck"
    language_code: str = "en-US"


@dataclass(frozen=True)
class VoiceConfig:
    engine: str = "classic_pipeline"  # "classic_pipeline" | "gemini_live"
    gemini_live: GeminiLiveConfig = field(default_factory=GeminiLiveConfig)


@dataclass(frozen=True)
class DebugConfig:
    session_logging: bool = True


@dataclass(frozen=True)
class MemoryConfig:
    enabled: bool = True       # master switch for all memory (history + long-term)
    extract: bool = True       # run async long-term fact extraction after each turn
    max_facts: int = 50        # cap on stored durable facts (pruned beyond this)
    inject_facts: int = 18     # how many facts to inject into the system prompt


@dataclass(frozen=True)
class AppConfig:
    hotkey: HotkeyConfig = field(default_factory=HotkeyConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    intent: IntentConfig = field(default_factory=IntentConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    voice: VoiceConfig = field(default_factory=VoiceConfig)
    debug: DebugConfig = field(default_factory=DebugConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)


def _save_tools_enabled_to_toml(config_path: Path, new_enabled: list[str]) -> None:
    try:
        content = config_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        in_tools = False
        replaced = False
        
        import json
        new_enabled_str = json.dumps(new_enabled)
        
        for i, line in enumerate(lines):
            trimmed = line.strip()
            if trimmed.startswith("[") and trimmed.endswith("]"):
                section_name = trimmed[1:-1].strip()
                if section_name == "tools":
                    in_tools = True
                else:
                    in_tools = False
            
            if in_tools and trimmed.startswith("enabled"):
                lines[i] = f"enabled = {new_enabled_str}"
                replaced = True
                break
                
        if replaced:
            config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(f"Failed to auto-migrate config.toml: {exc}")


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).expanduser() if path is not None else DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return AppConfig()

    with config_path.open("rb") as config_file:
        raw_config = tomllib.load(config_file)

    # Auto-migrate default config path if missing tools
    if path is None and "tools" in raw_config and isinstance(raw_config["tools"], dict):
        tools_sec = raw_config["tools"]
        if "enabled" in tools_sec and isinstance(tools_sec["enabled"], list):
            enabled_list = list(tools_sec["enabled"])
            default_tools = ToolsConfig().enabled
            missing_defaults = [t for t in default_tools if t not in enabled_list]
            if missing_defaults:
                tools_sec["enabled"] = enabled_list + missing_defaults
                _save_tools_enabled_to_toml(config_path, tools_sec["enabled"])

    return config_from_mapping(raw_config)


def _as_bool(value: Any, default: bool) -> bool:
    """Parse a TOML value into a bool, tolerating string forms like "false"."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off", "")
    if value is None:
        return default
    return bool(value)


def config_from_mapping(raw_config: dict[str, Any]) -> AppConfig:
    hotkey = raw_config.get("hotkey", {})
    stt = raw_config.get("stt", {})
    llm = raw_config.get("llm", {})
    tts = raw_config.get("tts", {})
    tools = raw_config.get("tools", {})
    intent = raw_config.get("intent", {})
    vad = raw_config.get("vad", {})
    voice_raw = raw_config.get("voice", {})
    gl_raw = voice_raw.get("gemini_live", {})

    debug = raw_config.get("debug", {})
    memory = raw_config.get("memory", {})

    return AppConfig(
        hotkey=HotkeyConfig(
            trigger=str(hotkey.get("trigger", HotkeyConfig.trigger)),
            conversation_trigger=str(hotkey.get("conversation_trigger", HotkeyConfig.conversation_trigger)),
            mode=str(hotkey.get("mode", HotkeyConfig.mode)),
            conversation_mode=_as_bool(hotkey.get("conversation_mode"), HotkeyConfig.conversation_mode),
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
            spotify_username=str(
                tools.get("spotify_username", ToolsConfig.spotify_username)
            ),
        ),
        intent=IntentConfig(
            local_router_enabled=_as_bool(
                intent.get("local_router_enabled"),
                IntentConfig.local_router_enabled,
            ),
            local_router_confidence_threshold=float(
                intent.get(
                    "local_router_confidence_threshold",
                    IntentConfig.local_router_confidence_threshold,
                )
            ),
        ),
        vad=VADConfig(
            enabled=_as_bool(vad.get("enabled"), VADConfig.enabled),
            model_path=str(vad.get("model_path", VADConfig.model_path)),
            start_threshold=float(vad.get("start_threshold", VADConfig.start_threshold)),
            end_threshold=float(vad.get("end_threshold", VADConfig.end_threshold)),
            rms_fallback_enabled=_as_bool(
                vad.get("rms_fallback_enabled"),
                VADConfig.rms_fallback_enabled,
            ),
            rms_start_level=float(vad.get("rms_start_level", VADConfig.rms_start_level)),
            rms_end_level=float(vad.get("rms_end_level", VADConfig.rms_end_level)),
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
        debug=DebugConfig(
            session_logging=_as_bool(
                debug.get("session_logging"), DebugConfig.session_logging
            ),
        ),
        memory=MemoryConfig(
            enabled=_as_bool(memory.get("enabled"), MemoryConfig.enabled),
            extract=_as_bool(memory.get("extract"), MemoryConfig.extract),
            max_facts=int(memory.get("max_facts", MemoryConfig.max_facts)),
            inject_facts=int(memory.get("inject_facts", MemoryConfig.inject_facts)),
        ),
    )
