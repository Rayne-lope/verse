from verse.config import AppConfig, load_config


def test_load_config_defaults_when_file_is_missing(tmp_path):
    config = load_config(tmp_path / "missing.toml")

    assert config == AppConfig()
    assert config.llm.max_history == 4
    assert config.llm.base_url == "https://api.deepseek.com"
    assert config.tts.model == "gemini-3.1-flash-tts"
    assert config.tts.base_url == "https://generativelanguage.googleapis.com/v1beta"
    assert config.memory.inject_facts == 6
    assert config.voice.max_tool_iterations == 2
    assert config.vad.speech_start_ms == 100
    assert config.vad.min_utterance_ms == 350
    assert config.vad.end_silence_ms == 700
    assert config.vad.pre_roll_ms == 250
    assert config.vad.followup_timeout_s == 3.0


def test_load_config_parses_llm_base_url(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm]
model = "deepseek-v4-flash-free"
base_url = "https://opencode.ai/zen/v1"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.llm.model == "deepseek-v4-flash-free"
    assert config.llm.base_url == "https://opencode.ai/zen/v1"


def test_load_config_parses_tts_model_and_base_url(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[tts]
provider = "gemini"
voice_id = "Puck"
model = "gemini-2.5-flash-tts"
base_url = "https://generativelanguage.googleapis.com/v1beta"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.tts.provider == "gemini"
    assert config.tts.voice_id == "Puck"
    assert config.tts.model == "gemini-2.5-flash-tts"
    assert config.tts.base_url == "https://generativelanguage.googleapis.com/v1beta"


def test_load_config_merges_toml_values(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hotkey]
trigger = "cmd+space"
conversation_mode = false

[llm]
provider = "openai"
model = "gpt-4.1-mini"
max_history = 4

[tools]
enabled = ["open_app"]

[vad]
enabled = false
start_threshold = 0.65

[voice]
max_tool_iterations = 3
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.hotkey.trigger == "cmd+space"
    assert config.hotkey.mode == "push_to_talk"
    assert config.hotkey.conversation_mode is False
    assert config.llm.provider == "openai"
    assert config.llm.model == "gpt-4.1-mini"
    assert config.llm.max_history == 4
    assert config.tools.enabled == ["open_app"]
    assert config.vad.enabled is False
    assert config.vad.start_threshold == 0.65
    assert config.vad.end_threshold == 0.35
    assert config.vad.rms_fallback_enabled is True
    assert config.vad.rms_start_level == 0.03
    assert config.vad.rms_end_level == 0.02
    assert config.voice.max_tool_iterations == 3


def test_load_config_parses_vad_rms_fallback_values(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[vad]
rms_fallback_enabled = "false"
rms_start_level = 0.07
rms_end_level = 0.04
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.vad.rms_fallback_enabled is False
    assert config.vad.rms_start_level == 0.07
    assert config.vad.rms_end_level == 0.04


def test_load_config_parses_local_intent_router_values(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[intent]
local_router_enabled = "false"
local_router_confidence_threshold = 0.9
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.intent.local_router_enabled is False
    assert config.intent.local_router_confidence_threshold == 0.9


def test_load_config_parses_always_on_values(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[always_on]
enabled = true
keyword = "picovoice"
keyword_path = ""
model_path = "/tmp/model.pv"
sensitivity = 0.8
device = "cpu:2"
""",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.always_on.enabled is True
    assert config.always_on.keyword == "picovoice"
    assert config.always_on.keyword_path == ""
    assert config.always_on.model_path == "/tmp/model.pv"
    assert config.always_on.sensitivity == 0.8
    assert config.always_on.device == "cpu:2"


def test_load_config_auto_migrates_default_path(tmp_path, monkeypatch):
    default_config_path = tmp_path / "config.toml"
    
    default_config_path.write_text(
        """
[tools]
enabled = ["play_music", "open_app"]
""",
        encoding="utf-8",
    )
    
    import verse.config
    monkeypatch.setattr(verse.config, "DEFAULT_CONFIG_PATH", default_config_path)
    
    config = load_config()
    
    assert "create_event" in config.tools.enabled
    assert "remember" in config.tools.enabled
    assert "play_music" in config.tools.enabled
    assert "open_app" in config.tools.enabled
    
    new_content = default_config_path.read_text(encoding="utf-8")
    assert "create_event" in new_content
    assert "remember" in new_content
