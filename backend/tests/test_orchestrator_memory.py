import asyncio

from verse.config import AppConfig, MemoryConfig
from verse.llm.base import LLMResponse
from verse.orchestrator import Orchestrator
from verse.persistence.db import ConversationStore
from verse.state import State, StateMachine
from verse.tools.registry import ToolRegistry


class FakeSTT:
    def __init__(self, text):
        self.text = text

    async def transcribe(self, audio, language=None):
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

    async def synthesize(self, text):
        self.spoken.append(text)
        return text.encode()


def _orch(store, *, stt, llm, tts, machine, extract=False):
    return Orchestrator(
        stt=stt,
        llm=llm,
        tts=tts,
        registry=ToolRegistry(),
        state_machine=machine,
        play=lambda audio: None,
        store=store,
        config=AppConfig(memory=MemoryConfig(extract=extract)),
    )


def test_handle_audio_records_history_and_persists():
    store = ConversationStore(":memory:")
    machine = StateMachine(initial_state=State.THINKING)
    orch = _orch(
        store,
        stt=FakeSTT("namaku Rapi"),
        llm=FakeLLM([LLMResponse(text="Halo Rapi!", tool_calls=[])]),
        tts=FakeTTS(),
        machine=machine,
    )

    asyncio.run(orch.handle_audio(b"audio"))

    assert orch._conversation_history == [
        {"role": "user", "content": "namaku Rapi"},
        {"role": "assistant", "content": "Halo Rapi!"},
    ]
    saved = store.load_recent_messages(limit=10)
    assert [(m["role"], m["content"]) for m in saved] == [
        ("user", "namaku Rapi"),
        ("assistant", "Halo Rapi!"),
    ]
    store.close()


def test_second_turn_sees_previous_turn_as_context():
    store = ConversationStore(":memory:")
    machine = StateMachine(initial_state=State.THINKING)
    llm = FakeLLM(
        [
            LLMResponse(text="Halo Rapi!", tool_calls=[]),
            LLMResponse(text="Namamu Rapi.", tool_calls=[]),
        ]
    )
    orch = _orch(store, stt=FakeSTT("namaku Rapi"), llm=llm, tts=FakeTTS(), machine=machine)

    asyncio.run(orch.handle_audio(b"a"))
    # Reset to THINKING for the second turn (handle_audio leaves it IDLE).
    machine._state = State.THINKING
    orch.stt = FakeSTT("siapa namaku?")
    asyncio.run(orch.handle_audio(b"b"))

    # The second LLM call must include the first turn in its messages.
    second_messages = llm.requests[1][0]
    contents = [m.get("content") for m in second_messages]
    assert "namaku Rapi" in contents
    assert "Halo Rapi!" in contents
    store.close()


def test_history_seeded_from_previous_session():
    store = ConversationStore(":memory:")
    conv = store.new_conversation()
    store.save_message(conv, "user", "namaku Rapi")
    store.save_message(conv, "assistant", "Halo Rapi!")

    orch = _orch(
        store,
        stt=FakeSTT("x"),
        llm=FakeLLM([]),
        tts=FakeTTS(),
        machine=StateMachine(),
    )

    assert {"role": "user", "content": "namaku Rapi"} in orch._conversation_history
    assert {"role": "assistant", "content": "Halo Rapi!"} in orch._conversation_history
    store.close()


def test_system_prompt_injects_long_term_memories():
    store = ConversationStore(":memory:")
    store.upsert_memory("User's name is Rapi")
    orch = _orch(store, stt=FakeSTT("x"), llm=FakeLLM([]), tts=FakeTTS(), machine=StateMachine())

    prompt = orch._compose_system_prompt()
    assert "User's name is Rapi" in prompt
    assert "Long-term memory" in prompt
    store.close()


def test_extract_memories_parses_and_stores_facts():
    store = ConversationStore(":memory:")
    llm = FakeLLM(
        [LLMResponse(text='["User is a student", "User builds Verse"]', tool_calls=[])]
    )
    orch = _orch(store, stt=FakeSTT("x"), llm=llm, tts=FakeTTS(), machine=StateMachine())

    asyncio.run(orch._extract_memories("aku mahasiswa bikin Verse", "keren!"))

    facts = store.load_memories(limit=10)
    assert "User is a student" in facts
    assert "User builds Verse" in facts
    store.close()


def test_memory_is_noop_without_store():
    machine = StateMachine(initial_state=State.THINKING)
    orch = Orchestrator(
        stt=FakeSTT("hi"),
        llm=FakeLLM([LLMResponse(text="hello", tool_calls=[])]),
        tts=FakeTTS(),
        registry=ToolRegistry(),
        state_machine=machine,
        play=lambda audio: None,
        store=None,
    )

    asyncio.run(orch.handle_audio(b"a"))

    assert orch._compose_system_prompt() == orch.system_prompt
    assert orch.conv_id is None
