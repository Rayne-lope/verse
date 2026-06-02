from verse.config import AppConfig, LLMConfig, TTSConfig
from verse.ws.protocol import config_data_message


def test_config_data_message_includes_llm_and_tts_model_base_url():
    config = AppConfig(
        llm=LLMConfig(
            provider="gemini",
            model="gemini-3.5-flash",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        ),
        tts=TTSConfig(
            provider="gemini",
            voice_id="Puck",
            model="gemini-3.1-flash-tts",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        ),
    )

    message = config_data_message(config, {"gemini": True})

    assert message["config"]["llm"]["base_url"] == "https://generativelanguage.googleapis.com/v1beta"
    assert message["config"]["tts"]["model"] == "gemini-3.1-flash-tts"
    assert message["config"]["tts"]["base_url"] == "https://generativelanguage.googleapis.com/v1beta"
    assert message["api_keys"]["gemini"] is True
