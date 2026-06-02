import asyncio
import threading
from unittest.mock import patch

from verse.config import AppConfig, DebugConfig, IntentConfig, MemoryConfig, ToolsConfig
from verse.llm.base import LLMResponse, LLMStreamEvent
from verse.orchestrator import Orchestrator
from verse.state import State, StateChangedEvent, StateMachine, StateTrigger
from verse.tools.registry import Tool, ToolRegistry


class FakeSTT:
    def __init__(self, text):
        self.text = text
        self.calls = []

    async def transcribe(self, audio, language=None):
        self.calls.append((audio, language))
        return self.text


class FakeLLM:
    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []

    async def chat(self, messages, tools=None):
        self.requests.append((messages, tools))
        return self._responses.pop(0)


class FakeTTS:
    def __init__(self):
        self.spoken = []

    async def stream(self, text):
        yield text.encode()

    async def synthesize(self, text):
        self.spoken.append(text)
        return text.encode()


def _registry_with(name, handler):
    registry = ToolRegistry()
    registry.register(
        Tool(
            name=name,
            description="test tool",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )
    return registry


def _registry_with_handlers(handlers):
    registry = ToolRegistry()
    for name, handler in handlers.items():
        registry.register(
            Tool(
                name=name,
                description="test tool",
                parameters={"type": "object", "properties": {}},
                handler=handler,
            )
        )
    return registry


def _orchestrator(stt, llm, tts, registry, machine, **kwargs):
    played = []
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=registry,
        state_machine=machine,
        play=played.append,
        **kwargs,
    )
    return orch, played


def test_handle_audio_plain_text_response():
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("hello there")
    llm = FakeLLM([LLMResponse(text="Hi!", tool_calls=[])])
    tts = FakeTTS()
    orch, played = _orchestrator(stt, llm, tts, ToolRegistry(), machine)

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "Hi!"
    assert tts.spoken == ["Hi!"]
    assert played == [b"Hi!"]
    assert machine.state is State.IDLE


def test_handle_audio_executes_tool_then_replies():
    calls = []

    def play_music(query=None):
        calls.append(query)
        return "Playing jazz."

    registry = _registry_with("play_music", play_music)
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("play some jazz")
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "play_music", "arguments": '{"query": "jazz"}'},
    }
    llm = FakeLLM(
        [
            LLMResponse(text="", tool_calls=[tool_call]),
            LLMResponse(text="Done, playing jazz.", tool_calls=[]),
        ]
    )
    tts = FakeTTS()
    executed = []
    orch, _ = _orchestrator(
        stt, llm, tts, registry, machine, on_tool_executed=lambda n, r: executed.append((n, r))
    )

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert calls == ["jazz"]
    assert reply == "Done, playing jazz."
    assert executed == [("play_music", "Playing jazz.")]
    # second LLM request includes the tool result message
    second_messages = llm.requests[1][0]
    assert any(m.get("role") == "tool" for m in second_messages)


def test_default_voice_tool_iterations_limit_agentic_loops():
    calls = []

    def do_it():
        calls.append("tool")
        return "done"

    registry = _registry_with("do_it", do_it)
    machine = StateMachine(initial_state=State.THINKING)
    tool_call = {
        "id": "call_1",
        "type": "function",
        "function": {"name": "do_it", "arguments": "{}"},
    }
    llm = FakeLLM(
        [
            LLMResponse(text="", tool_calls=[tool_call]),
            LLMResponse(text="", tool_calls=[tool_call]),
            LLMResponse(text="Final answer.", tool_calls=[]),
        ]
    )
    orch, _ = _orchestrator(FakeSTT("do the long task"), llm, FakeTTS(), registry, machine)

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "Final answer."
    assert calls == ["tool", "tool"]
    assert len(llm.requests) == 3


def test_browser_history_sanitization_keeps_tools_available():
    calls = []

    def browser_navigate(url):
        calls.append(url)
        return "Page Content:\nAntarktika adalah benua di kutub selatan."

    registry = _registry_with("browser_navigate", browser_navigate)
    machine = StateMachine(initial_state=State.THINKING)
    tool_call = {
        "id": "call_browser",
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "arguments": '{"url": "https://id.wikipedia.org/wiki/Antartika"}',
        },
    }
    llm = FakeLLM(
        [
            LLMResponse(text="", tool_calls=[tool_call]),
            LLMResponse(text="Antarktika itu benua es.", tool_calls=[]),
        ]
    )
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        registry,
        machine,
        config=AppConfig(
            tools=ToolsConfig(enabled=["browser_navigate"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )
    history = [
        {
            "role": "assistant",
            "content": "Maaf, aku tidak punya kemampuan untuk membuka halaman web atau membaca internet.",
        },
        {"role": "assistant", "content": "Mocked LLM reply"},
    ]

    reply = asyncio.run(
        orch._respond("tolong rangkum artikel tentang Antartika dari wikipedia", history)
    )

    assert reply == "Antarktika itu benua es."
    assert calls == ["https://id.wikipedia.org/wiki/Antartika"]
    first_messages, first_tools = llm.requests[0]
    first_contents = [m.get("content") for m in first_messages]
    assert all("tidak punya kemampuan" not in str(content) for content in first_contents)
    assert "Mocked LLM reply" not in first_contents
    assert first_tools is not None
    assert [t["function"]["name"] for t in first_tools] == ["browser_navigate"]


def test_browser_refusal_fallback_executes_playwright_tool():
    calls = []

    def browser_navigate(url):
        calls.append(url)
        return "Page Content:\nAntarktika adalah gurun es yang sangat dingin."

    registry = _registry_with("browser_navigate", browser_navigate)
    machine = StateMachine(initial_state=State.THINKING)
    llm = FakeLLM(
        [
            LLMResponse(
                text="Maaf, aku tidak punya kemampuan untuk membuka halaman web.",
                tool_calls=[],
            ),
            LLMResponse(
                text="Maaf, aku hanya bisa membuka Brave Browser saja dan tidak bisa membaca halaman.",
                tool_calls=[],
            ),
            LLMResponse(text="Antarktika adalah gurun es yang sangat dingin.", tool_calls=[]),
        ]
    )
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        registry,
        machine,
        config=AppConfig(
            tools=ToolsConfig(enabled=["browser_navigate"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    reply = asyncio.run(
        orch._respond(
            "iya kamu buka Brave Browser abis itu buka artikel tentang Antartika terus rangkum",
            [{"role": "user", "content": "Tolong buka Wikipedia dan rangkum artikelnya"}],
        )
    )

    assert reply == "Antarktika adalah gurun es yang sangat dingin."
    assert calls == ["https://id.wikipedia.org/wiki/Antartika"]
    assert len(llm.requests) == 3
    final_messages, final_tools = llm.requests[-1]
    assert final_tools is None
    assert any(m.get("role") == "tool" for m in final_messages)


def test_whatsapp_open_turn_uses_tool_without_llm():
    calls = []
    registry = _registry_with_handlers({
        "whatsapp_open": lambda: calls.append("open") or "WhatsApp Web is open and ready.",
    })
    llm = FakeLLM([])
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        registry,
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["whatsapp_open"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    reply = asyncio.run(orch._respond("Tolong buka WhatsApp di Brave", []))

    assert "WhatsApp Web sudah terbuka" in reply
    assert calls == ["open"]
    assert llm.requests == []


def test_whatsapp_multiturn_reply_asks_then_sends():
    calls = []

    def whatsapp_open():
        calls.append(("open", {}))
        return "WhatsApp Web is open and ready."

    def whatsapp_send_message(contact, text):
        calls.append(("send", {"contact": contact, "text": text}))
        return f"Sent WhatsApp message to {contact}: {text}"

    registry = _registry_with_handlers({
        "whatsapp_open": whatsapp_open,
        "whatsapp_send_message": whatsapp_send_message,
    })
    llm = FakeLLM([])
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        registry,
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["whatsapp_open", "whatsapp_send_message"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    first = asyncio.run(
        orch._respond("Tolong buat balasan ke Ridho Maulana di WhatsApp aku di Brave", [])
    )
    second = asyncio.run(orch._respond("bilang oke gas", []))

    assert "Pesan ke Ridho Maulana mau bilang apa" in first
    assert second == "Sudah, pesan WhatsApp ke Ridho Maulana aku kirim."
    assert calls == [
        ("open", {}),
        ("send", {"contact": "Ridho Maulana", "text": "oke gas"}),
    ]
    assert llm.requests == []


def test_whatsapp_status_query_recovers_pending_send():
    calls = []

    def whatsapp_send_message(contact, text):
        calls.append((contact, text))
        return f"Sent WhatsApp message to {contact}: {text}"

    registry = _registry_with_handlers({"whatsapp_send_message": whatsapp_send_message})
    orch, _ = _orchestrator(
        FakeSTT(""),
        FakeLLM([]),
        FakeTTS(),
        registry,
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["whatsapp_send_message"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )
    orch._pending_whatsapp_task = {
        "channel": "whatsapp",
        "contact": "Ridho Maulana",
        "text": "oke gas",
        "send_requested": True,
    }

    reply = asyncio.run(orch._respond("Mana gak kekirim?", []))

    assert reply == "Sudah, pesan WhatsApp ke Ridho Maulana aku kirim."
    assert calls == [("Ridho Maulana", "oke gas")]


def test_whatsapp_history_sanitizes_denials_and_fake_send_claims():
    registry = _registry_with("whatsapp_open", lambda: "WhatsApp Web is open and ready.")
    llm = FakeLLM([LLMResponse(text="Aku cek WhatsApp Web.", tool_calls=[])])
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        registry,
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["whatsapp_open"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )
    history = [
        {"role": "user", "content": "Tolong buka WhatsApp di Brave"},
        {
            "role": "assistant",
            "content": "Aku bisa buka Brave, tapi nggak bisa navigasi di dalamnya.",
        },
        {"role": "assistant", "content": "Oke, aku kirim sekarang pesan WhatsApp itu."},
        {"role": "assistant", "content": "Mocked LLM reply"},
    ]

    asyncio.run(orch._respond("Tolong cek status WhatsApp di Brave", history))

    first_messages, first_tools = llm.requests[0]
    contents = [str(m.get("content")) for m in first_messages]
    assert all("nggak bisa navigasi" not in content for content in contents)
    assert all("aku kirim sekarang" not in content for content in contents)
    assert all("Mocked LLM reply" not in content for content in contents)
    assert first_tools is not None
    assert [tool["function"]["name"] for tool in first_tools] == ["whatsapp_open"]


def test_whatsapp_fake_send_claim_without_tool_is_blocked():
    registry = _registry_with("whatsapp_open", lambda: "WhatsApp Web is open and ready.")
    llm = FakeLLM([
        LLMResponse(text="Oke, aku kirim pesan WhatsApp itu sekarang.", tool_calls=[]),
    ])
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        registry,
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["whatsapp_open"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    reply = asyncio.run(orch._respond("Tolong cek status WhatsApp di Brave", []))

    assert reply == "Aku belum menjalankan tool WhatsApp, jadi aku belum bisa bilang pesannya terkirim."


def test_browser_streaming_suppresses_long_pre_tool_text():
    calls = []
    tool_call = {
        "id": "call_browser",
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "arguments": '{"url": "https://id.wikipedia.org/wiki/Samudra"}',
        },
    }

    class StreamingBrowserLLM:
        def __init__(self):
            self.requests = []

        async def stream_chat(self, messages, tools=None):
            self.requests.append((messages, tools))
            if len(self.requests) == 1:
                yield LLMStreamEvent(type="text_delta", text="Aku akan buka Brave lalu membaca panjang dulu.")
                yield LLMStreamEvent(type="tool_call_done", tool_call=tool_call)
                yield LLMStreamEvent(type="done")
            else:
                yield LLMStreamEvent(type="text_delta", text="Samudra menutupi sebagian besar Bumi.")
                yield LLMStreamEvent(type="done")

    registry = _registry_with(
        "browser_navigate",
        lambda url: calls.append(url) or "Page Content:\nSamudra menutupi 71% Bumi.",
    )
    tts = FakeTTS()
    orch, _ = _orchestrator(
        FakeSTT(""),
        StreamingBrowserLLM(),
        tts,
        registry,
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["browser_navigate"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    reply = asyncio.run(orch._respond_and_speak_streaming("buka Wikipedia tentang Samudra", []))

    assert reply == "Samudra menutupi sebagian besar Bumi."
    assert calls == ["https://id.wikipedia.org/wiki/Samudra"]
    spoken = " ".join(tts.spoken)
    assert "membaca panjang dulu" not in spoken
    assert "Bentar, aku buka halamannya dulu." in tts.spoken
    assert "Samudra menutupi sebagian besar Bumi." in tts.spoken


def test_browser_turn_exposes_intent_and_form_tools():
    registry = _registry_with_handlers({
        "browser_click_best_match": lambda query: "clicked",
        "browser_click_text": lambda text, exact=False: "clicked",
        "browser_click_role": lambda role, name, exact=False: "clicked",
        "browser_fill_form": lambda fields, submit=False, submit_label="": "filled",
        "browser_go_back": lambda: "back",
    })
    llm = FakeLLM([LLMResponse(text="Aku cek dulu.", tool_calls=[])])
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        registry,
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=[
                "browser_click_best_match",
                "browser_click_text",
                "browser_click_role",
                "browser_fill_form",
                "browser_go_back",
            ]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    asyncio.run(orch._respond("klik tombol login di browser", []))

    _, tools = llm.requests[0]
    assert tools is not None
    names = [tool["function"]["name"] for tool in tools]
    assert names == [
        "browser_click_best_match",
        "browser_click_text",
        "browser_click_role",
        "browser_fill_form",
        "browser_go_back",
    ]


def test_browser_streaming_suppresses_pre_tool_text_for_intent_click():
    calls = []
    tool_call = {
        "id": "call_click",
        "type": "function",
        "function": {
            "name": "browser_click_best_match",
            "arguments": '{"query": "Login"}',
        },
    }

    class StreamingClickLLM:
        def __init__(self):
            self.requests = []

        async def stream_chat(self, messages, tools=None):
            self.requests.append((messages, tools))
            if len(self.requests) == 1:
                yield LLMStreamEvent(type="text_delta", text="Aku akan jelaskan panjang sebelum klik.")
                yield LLMStreamEvent(type="tool_call_done", tool_call=tool_call)
                yield LLMStreamEvent(type="done")
            else:
                yield LLMStreamEvent(type="text_delta", text="Tombol Login sudah aku klik.")
                yield LLMStreamEvent(type="done")

    registry = _registry_with(
        "browser_click_best_match",
        lambda query: calls.append(query) or "Successfully clicked best match for 'Login': [1] button.",
    )
    tts = FakeTTS()
    orch, _ = _orchestrator(
        FakeSTT(""),
        StreamingClickLLM(),
        tts,
        registry,
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["browser_click_best_match"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    reply = asyncio.run(orch._respond_and_speak_streaming("klik tombol Login di browser", []))

    assert reply == "Tombol Login sudah aku klik."
    assert calls == ["Login"]
    spoken = " ".join(tts.spoken)
    assert "jelaskan panjang" not in spoken
    assert "Bentar, aku cari elemen yang cocok dulu." in tts.spoken
    assert "Tombol Login sudah aku klik." in tts.spoken


def test_browser_failed_action_result_blocks_fake_success_reply():
    calls = []
    tool_call = {
        "id": "call_click",
        "type": "function",
        "function": {
            "name": "browser_click_best_match",
            "arguments": '{"query": "Login"}',
        },
    }

    def browser_click_best_match(query):
        calls.append(query)
        return "Failed to click best match for 'Login': match is ambiguous.\nCandidates:\n[1] button - text=\"Login\""

    llm = FakeLLM([
        LLMResponse(text="", tool_calls=[tool_call]),
        LLMResponse(text="Berhasil, aku sudah klik tombol Login.", tool_calls=[]),
    ])
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        _registry_with("browser_click_best_match", browser_click_best_match),
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["browser_click_best_match"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    reply = asyncio.run(orch._respond("klik tombol Login di browser", []))

    assert calls == ["Login"]
    assert reply.startswith("Aku belum bisa menyelesaikan aksi browser-nya:")
    assert "match is ambiguous" in reply


def test_browser_fill_form_submit_requires_explicit_intent():
    calls = []
    tool_call = {
        "id": "call_form",
        "type": "function",
        "function": {
            "name": "browser_fill_form",
            "arguments": '{"fields": [{"target": "Email", "value": "rayne@example.com"}], "submit": true}',
        },
    }

    def browser_fill_form(fields, submit=False, submit_label=""):
        calls.append((fields, submit, submit_label))
        return "Successfully filled form."

    llm = FakeLLM([
        LLMResponse(text="", tool_calls=[tool_call]),
        LLMResponse(text="Berhasil, form sudah aku submit.", tool_calls=[]),
    ])
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        _registry_with("browser_fill_form", browser_fill_form),
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["browser_fill_form"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    reply = asyncio.run(orch._respond("isi form ini di browser", []))

    assert calls == []
    assert reply.startswith("Aku belum bisa menyelesaikan aksi browser-nya:")
    assert "Blocked browser_fill_form" in reply


def test_whatsapp_send_tool_requires_explicit_send_intent():
    calls = []
    tool_call = {
        "id": "call_send",
        "type": "function",
        "function": {
            "name": "whatsapp_send_message",
            "arguments": '{"contact": "Ridho Maulana", "text": "oke gas"}',
        },
    }

    def whatsapp_send_message(contact, text):
        calls.append((contact, text))
        return f"Sent WhatsApp message to {contact}: {text}"

    llm = FakeLLM([
        LLMResponse(text="", tool_calls=[tool_call]),
        LLMResponse(text="Sudah, pesan WhatsApp ke Ridho aku kirim.", tool_calls=[]),
    ])
    orch, _ = _orchestrator(
        FakeSTT(""),
        llm,
        FakeTTS(),
        _registry_with("whatsapp_send_message", whatsapp_send_message),
        StateMachine(initial_state=State.THINKING),
        config=AppConfig(
            tools=ToolsConfig(enabled=["whatsapp_send_message"]),
            debug=DebugConfig(session_logging=False),
            memory=MemoryConfig(enabled=False),
        ),
    )

    reply = asyncio.run(orch._respond("cek WhatsApp di Brave", []))

    assert calls == []
    assert reply.startswith("Aku belum menjalankan tool WhatsApp")


def test_idle_state_does_not_close_browser_session():
    orch, _ = _orchestrator(
        FakeSTT(""),
        FakeLLM([]),
        FakeTTS(),
        ToolRegistry(),
        StateMachine(initial_state=State.IDLE),
    )
    event = StateChangedEvent(
        previous_state=State.SPEAKING,
        state=State.IDLE,
        trigger=StateTrigger.AUDIO_DONE,
    )

    with patch("verse.tools.builtin.browser.browser_close") as mock_close:
        orch._on_state_changed(event)

    mock_close.assert_not_called()


def test_handle_audio_uses_local_intent_before_llm():
    registry = _registry_with("get_time", lambda: "It is noon.")
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("jam berapa sekarang")
    llm = FakeLLM([])
    tts = FakeTTS()
    executed = []
    orch, played = _orchestrator(
        stt,
        llm,
        tts,
        registry,
        machine,
        config=AppConfig(tools=ToolsConfig(enabled=["get_time"])),
        on_tool_executed=lambda n, r: executed.append((n, r)),
    )

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "It is noon."
    assert llm.requests == []
    assert executed == [("get_time", "It is noon.")]
    assert tts.spoken == ["It is noon."]
    assert played == [b"It is noon."]


def test_local_intent_can_be_disabled_for_llm_fallback():
    registry = _registry_with("get_time", lambda: "It is noon.")
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("jam berapa sekarang")
    llm = FakeLLM([LLMResponse(text="LLM answer.", tool_calls=[])])
    tts = FakeTTS()
    orch, _ = _orchestrator(
        stt,
        llm,
        tts,
        registry,
        machine,
        config=AppConfig(intent=IntentConfig(local_router_enabled=False)),
    )

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "LLM answer."
    assert len(llm.requests) == 1


def test_tool_failure_is_reported_to_llm_not_raised():
    def boom():
        raise RuntimeError("spotify offline")

    registry = _registry_with("play_music", boom)
    machine = StateMachine(initial_state=State.THINKING)
    tool_call = {"id": "c1", "type": "function", "function": {"name": "play_music", "arguments": "{}"}}
    llm = FakeLLM(
        [
            LLMResponse(text="", tool_calls=[tool_call]),
            LLMResponse(text="Sorry, could not play.", tool_calls=[]),
        ]
    )
    orch, _ = _orchestrator(FakeSTT("play"), llm, FakeTTS(), registry, machine)

    reply = asyncio.run(orch.handle_audio(b"audio"))

    assert reply == "Sorry, could not play."
    tool_messages = [m for m in llm.requests[1][0] if m.get("role") == "tool"]
    assert "spotify offline" in tool_messages[0]["content"]


def test_handle_audio_failure_sets_error_state():
    class BrokenSTT:
        async def transcribe(self, audio, language=None):
            raise RuntimeError("mic dead")

    machine = StateMachine(initial_state=State.THINKING, error_reset_seconds=-1)
    orch, _ = _orchestrator(BrokenSTT(), FakeLLM([]), FakeTTS(), ToolRegistry(), machine)

    try:
        asyncio.run(orch.handle_audio(b"audio"))
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")

    assert machine.state is State.ERROR


class FakeRecorder:
    def __init__(self):
        self.is_recording = False
        self.started = 0

    def start_recording(self, on_audio_level=None):
        self.is_recording = True
        self.started += 1
        self.on_audio_level = on_audio_level

    def stop_recording(self):
        self.is_recording = False
        import numpy as np
        from verse.audio.capture import samples_to_wav_bytes
        return samples_to_wav_bytes(np.zeros(3200), 16000)


def test_start_listening_ignored_when_not_idle():
    machine = StateMachine(initial_state=State.ERROR, error_reset_seconds=-1)
    recorder = FakeRecorder()
    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )

    assert orch.start_listening() is False
    assert recorder.started == 0
    assert machine.state is State.ERROR


def test_stop_and_respond_noop_when_not_recording():
    machine = StateMachine()
    recorder = FakeRecorder()
    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )

    assert asyncio.run(orch.stop_and_respond()) == ""
    assert machine.state is State.IDLE


def test_transcript_callback_fires():
    machine = StateMachine(initial_state=State.THINKING)
    seen = []
    orch, _ = _orchestrator(
        FakeSTT("  hello  "),
        FakeLLM([LLMResponse(text="hi", tool_calls=[])]),
        FakeTTS(),
        ToolRegistry(),
        machine,
        on_transcript=seen.append,
    )

    asyncio.run(orch.handle_audio(b"audio"))
    assert seen == ["hello"]


def test_conversation_mode_auto_listens_after_speak():
    from verse.config import AppConfig, VADConfig

    machine = StateMachine(initial_state=State.THINKING)
    recorder = FakeRecorder()
    stt = FakeSTT("x")
    llm = FakeLLM([])
    tts = FakeTTS()
    
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
        config=AppConfig(vad=VADConfig(enabled=False)),
    )
    
    # Conversation mode is active (as if toggled on via start_auto_listening).
    orch._conversation_mode_active = True
    asyncio.run(orch._speak("hello"))

    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True


def test_speak_uses_preparing_audio_before_playback():
    machine = StateMachine(initial_state=State.THINKING)
    states = []

    def play(audio, *, on_audio_level=None, stop_event=None):
        states.append(machine.state)

    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        play=play,
    )
    machine.subscribe(lambda event: states.append(event.state))

    asyncio.run(orch._speak("hello"))

    assert State.PREPARING_AUDIO in states
    assert State.SPEAKING in states
    assert states[-1] is State.IDLE


def test_request_barge_in_interrupts_speaking_and_starts_listening():
    machine = StateMachine(initial_state=State.SPEAKING)
    recorder = FakeRecorder()
    events = []
    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
        play=lambda audio: None,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))
    orch._playback_stop_event = threading.Event()

    assert orch.request_barge_in() is True

    assert orch._playback_stop_event.is_set()
    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert ("tts", "interrupted", {}) in events


def test_barge_in_preserves_conversation_auto_listening():
    from verse.config import VADConfig

    machine = StateMachine(initial_state=State.SPEAKING)
    recorder = FakeRecorder()
    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
        config=AppConfig(vad=VADConfig(enabled=False)),
        play=lambda audio: None,
    )
    orch._conversation_mode_active = True
    orch._playback_stop_event = threading.Event()

    assert orch.request_barge_in() is True

    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert orch._auto_listening is True
    assert orch.conversation_mode_active is True


def test_speak_interruption_does_not_emit_completed_event():
    machine = StateMachine(initial_state=State.THINKING)
    recorder = FakeRecorder()
    events = []

    def interrupting_play(audio, *, on_audio_level=None, stop_event=None):
        assert stop_event is not None
        stop_event.set()

    orch = Orchestrator(
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
        play=interrupting_play,
    )
    orch.on_pipeline_event = lambda stage, event, metadata: events.append((stage, event, metadata))

    asyncio.run(orch._speak("hello"))

    assert machine.state is State.LISTENING
    assert recorder.is_recording is True
    assert ("tts", "interrupted", {}) in events
    assert ("tts", "completed", {}) not in events


def test_conversation_mode_silence_detection_triggers_response():
    import time
    machine = StateMachine(initial_state=State.LISTENING)
    recorder = FakeRecorder()
    stt = FakeSTT("test")
    llm = FakeLLM([LLMResponse(text="response", tool_calls=[])])
    tts = FakeTTS()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )
    
    from verse.config import AppConfig, HotkeyConfig, VADConfig
    orch.config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=False),
        vad=VADConfig(enabled=False)
    )
    recorder.is_recording = True
    orch._loop = loop
    orch._auto_listening = True
    orch._speech_detected = False
    orch._last_speech_time = 0.0
    
    orch._handle_audio_level(0.1)
    assert orch._speech_detected is True
    
    orch._last_speech_time = time.time() - 2.0
    orch._handle_audio_level(0.01)
    
    async def run_brief():
        await asyncio.sleep(0.1)
        
    loop.run_until_complete(run_brief())
    
    assert orch._auto_listening is False
    assert tts.spoken == ["response."]
    assert machine.state is State.IDLE
    loop.close()


def test_conversation_mode_timeout_returns_to_idle():
    import time
    machine = StateMachine(initial_state=State.LISTENING)
    recorder = FakeRecorder()
    stt = FakeSTT("x")
    llm = FakeLLM([])
    tts = FakeTTS()
    
    loop = asyncio.new_event_loop()
    
    orch = Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
        recorder=recorder,
    )
    
    from verse.config import AppConfig, HotkeyConfig, VADConfig
    orch.config = AppConfig(
        hotkey=HotkeyConfig(conversation_mode=False),
        vad=VADConfig(enabled=False)
    )
    recorder.is_recording = True
    orch._loop = loop
    orch._auto_listening = True
    orch._speech_detected = False
    orch._auto_listen_start_real_time = time.time() - 6.0
    
    orch._handle_audio_level(0.01)
    
    async def run_brief():
        await asyncio.sleep(0.1)
        
    loop.run_until_complete(run_brief())
    
    assert orch._auto_listening is False
    assert recorder.is_recording is False
    assert machine.state is State.IDLE
    loop.close()


def test_clean_markdown_for_tts():
    orch = Orchestrator(
        stt=FakeSTT(""),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=StateMachine(),
    )
    
    input_text = "Berikut beberapa catatan Anda:\n* **Belanja**: Beli susu\n* **Kerja**: Kirim email ke Rayne"
    cleaned = orch._clean_markdown_for_tts(input_text)
    
    # Expected output should have clean text and correct pauses
    assert "Berikut beberapa catatan Anda:" in cleaned
    assert "Belanja: Beli susu." in cleaned
    assert "Kerja: Kirim email ke Rayne." in cleaned
    assert "*" not in cleaned
    assert "**" not in cleaned


def test_conversational_local_intent_replies(monkeypatch):
    registry = ToolRegistry()
    registry.register(
        Tool(
            name="set_volume",
            description="set volume",
            parameters={"type": "object", "properties": {"level": {"type": "integer"}}},
            handler=lambda level: f"System volume set to {level}%.",
        )
    )
    
    machine = StateMachine(initial_state=State.THINKING)
    stt = FakeSTT("kecilin volume")
    llm = FakeLLM([])
    tts = FakeTTS()
    
    orch, played = _orchestrator(
        stt,
        llm,
        tts,
        registry,
        machine,
        config=AppConfig(tools=ToolsConfig(enabled=["set_volume"])),
    )
    
    reply = asyncio.run(orch.handle_audio(b"audio"))
    
    # Verify that the reply is a local template instead of raw "System volume set to 25%."
    assert "volume aku set ke 25%" in reply
    assert tts.spoken == [reply]
    assert played == [reply.encode()]
