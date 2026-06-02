import asyncio
import io
import wave
from types import SimpleNamespace

from verse.config import TTSConfig
from verse.tts.gemini import GeminiTTSAdapter, _gemini_voice_name


class FakeModels:
    def __init__(self, pcm: bytes):
        self.pcm = pcm
        self.request = None

    def generate_content(self, **kwargs):
        self.request = kwargs
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(
                                inline_data=SimpleNamespace(data=self.pcm)
                            )
                        ]
                    )
                )
            ]
        )


class FakeClient:
    def __init__(self, pcm: bytes):
        self.models = FakeModels(pcm)


def test_gemini_tts_adapter_generates_wav_from_pcm():
    pcm = b"\x01\x00\x02\x00" * 12
    client = FakeClient(pcm)
    adapter = GeminiTTSAdapter(
        TTSConfig(
            provider="gemini",
            model="gemini-3.1-flash-tts",
            base_url="https://generativelanguage.googleapis.com/v1beta",
            voice_id="Puck",
        ),
        client=client,
    )

    wav_bytes = asyncio.run(adapter.synthesize("Halo dunia"))

    assert client.models.request["model"] == "gemini-3.1-flash-tts"
    assert client.models.request["contents"] == "Halo dunia"
    config = client.models.request["config"]
    assert config.response_modalities == ["AUDIO"]
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"

    with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
        assert wav.getframerate() == 24000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.readframes(wav.getnframes()) == pcm


def test_gemini_tts_stream_pcm_returns_raw_pcm():
    pcm = b"\x03\x00\x04\x00"
    adapter = GeminiTTSAdapter(TTSConfig(provider="gemini"), client=FakeClient(pcm))

    async def collect():
        return [chunk async for chunk in adapter.stream_pcm("Halo")]

    assert asyncio.run(collect()) == [pcm]


def test_gemini_tts_adapter_builds_client_with_config_base_url(monkeypatch):
    created = {}

    def fake_client(**kwargs):
        created.update(kwargs)
        return "client"

    monkeypatch.setenv("GEMINI_API_KEY", "dummy-key")
    monkeypatch.setattr("google.genai.Client", fake_client)
    adapter = GeminiTTSAdapter(
        TTSConfig(
            provider="gemini",
            model="gemini-2.5-flash-tts",
            base_url="https://generativelanguage.googleapis.com/v1beta",
        )
    )

    assert adapter.client == "client"
    assert created["api_key"] == "dummy-key"
    assert created["http_options"].base_url == "https://generativelanguage.googleapis.com/v1beta"


def test_gemini_tts_maps_existing_edge_voice_to_prebuilt_voice():
    assert _gemini_voice_name("id-ID-GadisNeural") == "Kore"
    assert _gemini_voice_name("Kore") == "Kore"
