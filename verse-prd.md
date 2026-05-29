# Verse — Product Requirements Document

> A voice-first AI companion for macOS. Push-to-talk powered, agentic, and built to be your second brain.

**Version**: 1.0
**Status**: Draft
**Owner**: Rayne
**Last Updated**: May 29, 2026

---

## 1. Overview

### 1.1 Product Vision

**Verse** adalah AI agent personal yang hidup di MacBook sebagai floating presence — selalu siap dipanggil via shortcut, mendengarkan suara user, memproses dengan LLM, dan merespon dengan natural voice + visual feedback. Bukan sekadar chatbot, Verse adalah **conversational interface** untuk mengontrol macOS, mencari informasi, dan menjalankan tugas multi-step.

**Tagline**: *"Speak. Verse listens."*

### 1.2 Why Build This?

- Voice interaction adalah interface terbaik untuk **quick capture & quick action**
- LLM modern (DeepSeek, Gemini Flash) udah cukup cerdas untuk reliable tool calling
- macOS punya powerful automation layer (AppleScript, Shortcuts) yang underused
- Existing solutions (Siri, Alexa) terlalu locked-down — kita butuh yang **extensible & customizable**

### 1.3 Non-Goals (v1)

- ❌ Always-on listening / wake word ("Hey Verse") — defer ke v2
- ❌ Mobile/iOS companion app
- ❌ Multi-language support (English & Indonesian only di v1)
- ❌ Multi-user/account system
- ❌ Cloud sync — fully local-first
- ❌ Visual screen understanding (computer vision)

---

## 2. User Stories

### Primary Persona

**Rayne** — Student/indie hacker yang multitasking antara coding, ngoprek design, dan main game. Butuh tools yang cepet diakses tanpa break flow.

### Core User Stories

| ID | As a... | I want to... | So that... |
|----|---------|--------------|------------|
| US-01 | User | Press a hotkey and speak naturally | I don't have to context-switch to a chat window |
| US-02 | User | See visual feedback when Verse is listening/thinking/speaking | I know its current state without watching console |
| US-03 | User | Ask Verse to play music or control Spotify | I don't have to alt-tab to control playback |
| US-04 | User | Ask Verse to open apps or files | I can launch things faster than Spotlight |
| US-05 | User | Ask Verse to search the web | I get answers without opening a browser |
| US-06 | User | Have natural back-and-forth conversation | Follow-up questions feel fluid |
| US-07 | User | Configure which LLM provider to use | I can balance cost vs quality vs speed |
| US-08 | User | See conversation history | I can reference past queries |

---

## 3. Functional Requirements

### 3.1 Core Interaction Flow

```
[1] User presses & holds hotkey (default: ⌥ Space)
[2] Verse UI appears + bubble enters "Listening" state
[3] Mic records audio while key held
[4] User releases key
[5] Bubble enters "Thinking" state
[6] Audio → STT → text transcript
[7] Transcript + history → LLM (with tool definitions)
[8] LLM responds with text + optional tool calls
[9] If tool calls: execute → feed results back → LLM continues
[10] Final text response → TTS → audio playback
[11] Bubble enters "Speaking" state, reactive to audio amplitude
[12] On audio end: bubble returns to "Idle"
[13] Conversation history persisted
```

### 3.2 Modes

**Push-to-Talk (MVP)**
- Hold hotkey → speak → release → response
- Default hotkey: `⌥ Space` (configurable)
- Optional: tap-to-toggle mode (tap once to start, tap again to stop)

**Conversation Mode**
- After response, brief window (~5s) where user can follow up without re-pressing hotkey
- Indicated by bubble pulsing softly
- Exits on timeout or explicit "stop" command

### 3.3 Tool Calling (MVP Tools)

Verse harus support function calling dengan tools berikut:

| Tool | Description | Parameters | Implementation |
|------|-------------|------------|----------------|
| `play_music` | Play song/artist/playlist on Spotify | `query: str` | AppleScript / Spotify Web API |
| `pause_music` | Pause current playback | — | AppleScript |
| `next_track` | Skip to next song | — | AppleScript |
| `previous_track` | Go to previous song | — | AppleScript |
| `set_volume` | Set system volume | `level: 0-100` | AppleScript |
| `open_app` | Open a macOS application | `app_name: str` | `subprocess` + `open -a` |
| `web_search` | Search the web and return summary | `query: str` | Brave Search API / SerpAPI |
| `open_url` | Open URL in default browser | `url: str` | `webbrowser` module |
| `get_time` | Get current time/date | `timezone: str?` | `datetime` |
| `get_weather` | Get weather for location | `location: str` | OpenWeatherMap API |
| `take_note` | Save a quick note to local file | `content: str` | File write to `~/Verse/notes/` |

### 3.4 Conversation History

- History persisted ke local SQLite: `~/.verse/history.db`
- Schema: `conversations` (id, started_at, ended_at), `messages` (id, conv_id, role, content, tool_calls, audio_path, created_at)
- Last N messages (configurable, default 10) di-include sebagai context tiap LLM call
- Audio recordings optional disimpan (default: off) di `~/.verse/audio/`

### 3.5 Configuration

User-editable config di `~/.verse/config.toml`:

```toml
[hotkey]
trigger = "alt+space"
mode = "push_to_talk"  # or "toggle"

[stt]
provider = "groq"  # or "openai", "local_whisper"
language = "auto"  # or "en", "id"

[llm]
provider = "deepseek"  # or "gemini", "claude", "openai"
model = "deepseek-chat"
temperature = 0.7
max_history = 10

[tts]
provider = "elevenlabs"  # or "openai", "macos_say"
voice_id = "..."
speed = 1.0

[tools]
enabled = ["play_music", "pause_music", "open_app", "web_search", "open_url"]
spotify_client_id = "..."
spotify_client_secret = "..."
brave_api_key = "..."

[ui]
bubble_position = "top_right"  # or center, etc.
theme = "auto"
```

---

## 4. Non-Functional Requirements

### 4.1 Performance

| Metric | Target | Critical |
|--------|--------|----------|
| Hotkey press → bubble visible | <100ms | Yes |
| End of speech → STT result | <800ms (Groq) | Yes |
| STT done → first LLM token | <1.5s | High |
| Total round-trip (no tools) | <3s | High |
| Total round-trip (with 1 tool) | <5s | Medium |
| Memory footprint (idle) | <150MB | Medium |
| CPU usage (idle) | <2% | High |

### 4.2 Reliability

- Graceful degradation kalau API down (e.g. STT fail → tampilkan error visual, jangan crash)
- Network timeout: 10s per API call, dengan retry exponential backoff (max 2 retry)
- Tool execution timeout: 15s per tool
- Crash recovery: state restored dari last persisted conversation

### 4.3 Security & Privacy

- API keys disimpan di **macOS Keychain**, bukan plain text config
- Audio recordings **off by default**
- Conversation history bisa di-purge via CLI: `verse history purge`
- No telemetry, no analytics
- Permissions: microphone, automation (System Preferences → Security & Privacy)

### 4.4 Compatibility

- macOS 13 (Ventura) or later
- Apple Silicon (M1+) primary target, Intel best-effort
- Python 3.11+

---

## 5. Technical Architecture

### 5.1 High-Level Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     VERSE FRONTEND (Tauri)                  │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  React UI                                            │   │
│  │  ├── Bubble (audio-reactive visualization)          │   │
│  │  ├── State manager (idle/listening/thinking/speak)  │   │
│  │  └── History panel (optional)                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                          ↕ WebSocket                         │
└─────────────────────────────────────────────────────────────┘
                            ↕
┌─────────────────────────────────────────────────────────────┐
│                  VERSE BACKEND (Python)                     │
│                                                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Hotkey      │  │  Audio I/O   │  │  WebSocket   │      │
│  │  Listener    │  │  Manager     │  │  Server      │      │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘      │
│         │                 │                 │              │
│         └─────────────────┼─────────────────┘              │
│                           ↓                                │
│  ┌─────────────────────────────────────────────────┐       │
│  │           AGENT ORCHESTRATOR                    │       │
│  │  (state machine, conversation loop)             │       │
│  └─────────────────────────────────────────────────┘       │
│         ↓           ↓           ↓           ↓              │
│  ┌─────────┐ ┌──────────┐ ┌─────────┐ ┌─────────┐         │
│  │  STT    │ │   LLM    │ │  TTS    │ │  Tools  │         │
│  │ Adapter │ │ Adapter  │ │ Adapter │ │ Registry│         │
│  └─────────┘ └──────────┘ └─────────┘ └─────────┘         │
│       ↓          ↓             ↓            ↓              │
│   [Groq]    [DeepSeek]   [ElevenLabs]  [AppleScript,       │
│   [OpenAI]  [Gemini]     [OpenAI]       Spotify API,       │
│   [Local]   [Claude]     [macOS say]    Web Search, ...]   │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │           PERSISTENCE LAYER                     │       │
│  │  ├── SQLite (~/.verse/history.db)              │       │
│  │  ├── Config (~/.verse/config.toml)             │       │
│  │  └── Keychain (API keys)                       │       │
│  └─────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Tech Stack

**Backend**

| Layer | Choice | Justification |
|-------|--------|---------------|
| Language | Python 3.11+ | Best AI ecosystem |
| Framework | FastAPI | WebSocket support, async-first |
| Audio capture | `sounddevice` | Cross-platform, low-latency |
| Hotkey | `pynput` | Global hotkey listener for macOS |
| STT (primary) | Groq Whisper API | Fastest hosted Whisper (~300ms) |
| STT (fallback) | `faster-whisper` (local) | Offline backup |
| LLM (primary) | DeepSeek API | Cheap, capable, supports function calling |
| LLM (alternate) | Gemini Flash, Claude, OpenAI | Pluggable via adapter |
| TTS (primary) | ElevenLabs streaming | Natural voice, real-time |
| TTS (fallback) | macOS `say` | Always available, free |
| DB | SQLite via `sqlite3` | Zero-config, file-based |
| Keychain | `keyring` library | Secure API key storage |
| Config | `tomli` / `tomllib` | Human-readable |
| WebSocket | `websockets` library | Bi-directional comms with UI |

**Frontend** *(Rayne handles design, this is just infrastructure)*

| Layer | Choice | Justification |
|-------|--------|---------------|
| Shell | Tauri 2.x | Native feel, lightweight, Rust-powered |
| UI | React + TypeScript | Familiar stack |
| Audio Viz | Web Audio API + Canvas | Real-time audio analysis |
| Animation | (Rayne's choice) | UI/UX layer |
| Comms | WebSocket | Real-time sync with backend |

### 5.3 Adapter Pattern (Critical Design Decision)

Setiap external service (STT, LLM, TTS) di-abstraksi via adapter interface biar gampang swap provider:

```python
# stt/base.py
class STTAdapter(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes, language: str | None) -> str: ...

# stt/groq.py
class GroqWhisperAdapter(STTAdapter):
    async def transcribe(self, audio, language): ...

# stt/local.py
class FasterWhisperAdapter(STTAdapter):
    async def transcribe(self, audio, language): ...
```

Sama pattern untuk `LLMAdapter` & `TTSAdapter`. Config menentukan adapter mana yang di-load saat startup.

### 5.4 LLM Adapter — Function Calling Contract

Setiap LLM adapter harus expose unified interface untuk function calling:

```python
class LLMAdapter(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[Message],
        tools: list[ToolDefinition],
    ) -> LLMResponse:
        """
        Returns LLMResponse with either:
        - text: str (final response)
        - tool_calls: list[ToolCall] (need execution)
        """
```

Karena DeepSeek, Gemini, OpenAI, Claude punya schema function calling beda-beda, adapter handle translation internal.

### 5.5 Tool Registry

```python
# tools/registry.py
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema
    handler: Callable

class ToolRegistry:
    def register(tool: Tool): ...
    def get(name: str) -> Tool: ...
    def list_definitions() -> list[dict]: ...  # For LLM
    async def execute(name: str, params: dict) -> ToolResult: ...
```

Tools di-register pas startup. Bisa enabled/disabled via config.

### 5.6 Agent Loop (Pseudocode)

```python
async def handle_voice_input(audio_bytes: bytes):
    set_state("thinking")

    # 1. STT
    transcript = await stt.transcribe(audio_bytes)
    save_message(role="user", content=transcript)

    # 2. Load context
    history = load_recent_messages(limit=config.max_history)
    tools = registry.list_definitions()

    # 3. LLM loop (handle multi-step tool calls)
    while True:
        response = await llm.chat(history, tools=tools)

        if response.tool_calls:
            for call in response.tool_calls:
                result = await registry.execute(call.name, call.params)
                history.append({"role": "tool", "content": result})
            continue  # let LLM see results & decide next step

        # No more tools, final text response
        save_message(role="assistant", content=response.text)
        break

    # 4. TTS
    set_state("speaking")
    async for audio_chunk in tts.stream(response.text):
        send_audio_to_frontend(audio_chunk)  # for bubble viz
        play_audio(audio_chunk)

    set_state("idle")
```

### 5.7 WebSocket Protocol (Backend ↔ Frontend)

Backend pushes state events ke frontend, frontend bisa kirim commands.

**Backend → Frontend:**
```json
{ "type": "state_change", "state": "listening" }
{ "type": "audio_level", "level": 0.73 }   // for bubble reactivity
{ "type": "transcript", "text": "play some jazz", "partial": false }
{ "type": "assistant_text", "text": "Playing jazz..." }
{ "type": "tool_executed", "name": "play_music", "result": "ok" }
{ "type": "error", "message": "...", "recoverable": true }
```

**Frontend → Backend:**
```json
{ "type": "manual_trigger", "action": "start_listening" }
{ "type": "manual_trigger", "action": "stop_listening" }
{ "type": "interrupt" }   // stop current TTS
{ "type": "config_update", "key": "...", "value": "..." }
```

### 5.8 State Machine

```
   ┌───────┐  hotkey press   ┌────────────┐
   │ IDLE  │ ──────────────► │ LISTENING  │
   └───┬───┘                  └─────┬──────┘
       ▲                            │ hotkey release
       │ tts done                   ▼
   ┌───┴────────┐  llm done   ┌──────────────┐
   │  SPEAKING  │ ◄────────── │   THINKING   │
   └────────────┘             └──────────────┘
                                    │
                                    │ on error
                                    ▼
                              ┌──────────┐
                              │  ERROR   │ ──► IDLE (after 3s)
                              └──────────┘
```

---

## 6. Project Structure

```
verse/
├── backend/
│   ├── pyproject.toml
│   ├── verse/
│   │   ├── __init__.py
│   │   ├── main.py                 # Entry point
│   │   ├── config.py               # Config loader
│   │   ├── state.py                # State machine
│   │   ├── orchestrator.py         # Agent loop
│   │   ├── hotkey.py               # Global hotkey listener
│   │   ├── audio/
│   │   │   ├── capture.py          # Mic recording
│   │   │   └── playback.py         # Audio output
│   │   ├── stt/
│   │   │   ├── base.py
│   │   │   ├── groq.py
│   │   │   ├── openai.py
│   │   │   └── local.py
│   │   ├── llm/
│   │   │   ├── base.py
│   │   │   ├── deepseek.py
│   │   │   ├── gemini.py
│   │   │   ├── claude.py
│   │   │   └── openai.py
│   │   ├── tts/
│   │   │   ├── base.py
│   │   │   ├── elevenlabs.py
│   │   │   ├── openai.py
│   │   │   └── macos_say.py
│   │   ├── tools/
│   │   │   ├── registry.py
│   │   │   ├── builtin/
│   │   │   │   ├── spotify.py
│   │   │   │   ├── system.py
│   │   │   │   ├── web.py
│   │   │   │   └── notes.py
│   │   │   └── custom/             # User-defined tools
│   │   ├── persistence/
│   │   │   ├── db.py
│   │   │   └── keychain.py
│   │   └── ws/
│   │       └── server.py
│   └── tests/
├── frontend/
│   ├── src-tauri/                  # Tauri Rust shell
│   ├── src/                        # React app
│   │   ├── components/
│   │   ├── hooks/
│   │   └── App.tsx
│   └── package.json
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   └── TOOLS.md
└── README.md
```

---

## 7. Development Phases

### Phase 0 — Foundation (Week 1)
**Goal**: Get a working CLI prototype.

- [ ] Project scaffolding (Python + Tauri shells)
- [ ] Config loader + Keychain integration
- [ ] Audio capture + playback (test recording + playing)
- [ ] STT adapter (Groq) + working transcribe
- [ ] LLM adapter (DeepSeek) + basic chat (no tools)
- [ ] TTS adapter (macOS `say` first, ElevenLabs after)
- [ ] **Milestone**: Run from CLI, speak into mic, hear response.

### Phase 1 — Push-to-Talk MVP (Week 2)
**Goal**: Hotkey-triggered voice interaction with basic tools.

- [ ] Global hotkey listener (`⌥ Space`)
- [ ] State machine implementation
- [ ] Tool registry + 5 core tools (play_music, pause, open_app, web_search, get_time)
- [ ] LLM function calling integration
- [ ] SQLite history persistence
- [ ] **Milestone**: Press hotkey, say "play some jazz", Spotify starts.

### Phase 2 — Frontend Integration (Week 3)
**Goal**: Visual feedback via Tauri UI.

- [ ] Tauri shell with transparent floating window
- [ ] WebSocket server + client
- [ ] State sync (idle/listening/thinking/speaking)
- [ ] Audio level streaming for bubble reactivity
- [ ] Basic UI scaffolding for Rayne to design on top
- [ ] **Milestone**: Bubble appears, reacts to mic, then to TTS output.

### Phase 3 — Polish & Extended Tools (Week 4)
**Goal**: Production-ready experience.

- [ ] ElevenLabs streaming TTS
- [ ] Error handling & graceful degradation
- [ ] Conversation mode (follow-up window)
- [ ] More tools: weather, notes, calendar (read), reminders
- [ ] Settings UI
- [ ] Onboarding flow (first-run API key setup)
- [ ] Logging & debugging tools

---

## 8. Roadmap (v2+)

### v2.0 — Always-On Verse

- **Wake word**: "Hey Verse" via Picovoice Porcupine (custom model)
- **Ambient mode**: low-power idle, wake on trigger
- **Privacy indicator**: visual cue when mic active

### v2.1 — Browser Agent

- Playwright integration for web automation
- "Cari MacBook M4 di Tokopedia" → buka browser, scrape, summarize
- Login session persistence
- Approval flow untuk destructive actions

### v2.2 — Memory & Context

- Long-term memory (vector DB: `chromadb` or `sqlite-vec`)
- "Remember that I prefer dark mode" → persist preference
- Per-app context (lagi di VS Code? Verse aware of current project)

### v2.3 — Computer Use

- Claude Computer Use API integration
- Verse can "see" screen + click/type
- Multi-step task completion ("upload these photos to Drive then send the link to Andre")

### v2.4 — Multi-Modal

- Screenshot understanding ("what's this error?")
- Camera input (visual queries)
- Document Q&A (drag PDF, ask questions via voice)

### v2.5 — Verse SDK

- Plugin system for community tools
- Tool marketplace
- Custom voice training

---

## 9. Cost Analysis

### Monthly Cost Estimate (Personal Use ~50 queries/day)

| Service | Pricing Model | Est. Monthly |
|---------|---------------|--------------|
| Groq Whisper API | $0.04 / hour audio | ~$2 |
| DeepSeek API | $0.27 / M input tokens | ~$3 |
| ElevenLabs | $5/mo (Starter) for 30k chars | ~$5 |
| Brave Search API | Free tier (2k queries/mo) | $0 |
| **Total** | | **~$10/mo** |

### Free-Tier Alternative

- STT: local `faster-whisper` (free, ~1s latency on M-series)
- LLM: Gemini Flash free tier (free up to limits)
- TTS: macOS `say` (free, robotic but acceptable)
- **Total: $0/mo**

---

## 10. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM picks wrong tool / hallucinates params | High (broken UX) | Strong prompt engineering, structured outputs, validation layer |
| Audio latency too high | High | Stream STT + TTS, parallelize where possible |
| macOS permission friction | Medium | Clear onboarding, link to System Settings, retry flow |
| API key leakage | High | Keychain only, never log, never send to LLM |
| Spotify AppleScript inconsistency | Medium | Fallback to Spotify Web API |
| WebSocket disconnect mid-conversation | Medium | Auto-reconnect, state recovery from DB |
| LLM provider outage | Medium | Multi-provider failover (DeepSeek → Gemini → Claude) |
| Battery drain from idle CPU | Low | Profile early, optimize hotkey listener |

---

## 11. Success Metrics

### MVP Success Criteria
- ✅ Can complete 10 common voice tasks reliably (>95% success rate)
- ✅ Total round-trip <3s for simple queries
- ✅ Works offline for basic tools (system controls)
- ✅ Zero crashes over 24h usage
- ✅ Rayne uses it daily for 1 week without major friction

### Long-Term Metrics
- Daily active sessions
- Average queries per day
- Tool execution success rate (per tool)
- LLM call latency p50/p95/p99
- User-defined custom tools count

---

## 12. Open Questions

1. **Interruption handling** — Should user be able to interrupt Verse mid-speech by pressing hotkey again? (Lean: yes, but defer to Phase 3)
2. **Multi-turn tools** — How to handle tools that need confirmation? (e.g., "delete file X" → "are you sure?")
3. **Privacy mode** — Should there be a "incognito" mode that doesn't persist history?
4. **Voice cloning** — Allow user to use their own voice for TTS? (Defer to v2)
5. **Localization** — Voice commands in mixed Indonesian/English (code-switching) — how to handle in STT/LLM?

---

## 13. Appendix

### A. Glossary

- **STT**: Speech-to-Text
- **TTS**: Text-to-Speech
- **VAD**: Voice Activity Detection
- **Wake word**: Keyword that activates always-on listening (e.g., "Hey Siri")
- **Tool calling / Function calling**: LLM capability to invoke predefined functions
- **Adapter pattern**: Design pattern that abstracts implementations behind a common interface

### B. References

- Picovoice Porcupine: https://picovoice.ai/platform/porcupine/
- Groq API docs: https://console.groq.com/docs
- DeepSeek API: https://api-docs.deepseek.com/
- ElevenLabs streaming: https://elevenlabs.io/docs/api-reference/streaming
- Tauri docs: https://tauri.app/
- Spotify Web API: https://developer.spotify.com/documentation/web-api

### C. Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-05-29 | Push-to-talk for MVP, defer wake word | Faster MVP, avoid wake word tuning hell |
| 2026-05-29 | Tauri + Python over Electron | Lighter, native feel, matches design sensibility |
| 2026-05-29 | Adapter pattern for STT/LLM/TTS | Future-proof, easy to swap providers |
| 2026-05-29 | SQLite over Postgres | Zero-config, single-user, file-based |
| 2026-05-29 | DeepSeek as primary LLM | Cost-effective, capable function calling |

---

*End of PRD v1.0*
