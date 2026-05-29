from verse.config import AppConfig, load_config


def test_load_config_defaults_when_file_is_missing(tmp_path):
    config = load_config(tmp_path / "missing.toml")

    assert config == AppConfig()
    assert config.llm.max_history == 10


def test_load_config_merges_toml_values(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[hotkey]
trigger = "cmd+space"

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
    assert config.llm.provider == "openai"
    assert config.llm.model == "gpt-4.1-mini"
    assert config.llm.max_history == 4
    assert config.tools.enabled == ["open_app"]
