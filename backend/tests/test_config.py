from verse.config import AppConfig, load_config


def test_load_config_defaults_when_file_is_missing(tmp_path):
    config = load_config(tmp_path / "missing.toml")

    assert config == AppConfig()
    assert config.llm.max_history == 10
    assert config.llm.base_url == "https://api.deepseek.com"


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
