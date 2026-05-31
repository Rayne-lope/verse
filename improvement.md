# Verse Jarvis Latency Overhaul — Super Detailed Engineering Report

## Goal

Refactor Verse from a classic sequential voice assistant into a smoother Jarvis-like realtime assistant.

The target experience:

```txt
User speaks
→ UI reacts instantly
→ endpointing feels natural
→ simple commands execute almost instantly
→ complex answers start speaking before the full LLM response is finished
→ user can interrupt at any time
→ old audio/LLM/TTS never leaks into the new turn
```

The current architecture is usable, but the latency profile is dominated by blocking stages:

```txt
record/VAD full utterance
→ STT final transcript
→ local router or LLM full response
→ optional tool calls and extra LLM calls
→ TTS full synthesis
→ WAV playback
```

The desired architecture:

```txt
mic chunks / VAD
→ partial or final STT
→ fast local intent router
→ streaming LLM
→ sentence/chunk segmenter
→ streaming TTS to PCM
→ realtime playback
→ cancellable turn controller
```

---

## Product Targets

### Perceived latency targets

For simple local commands:

```txt
speech end → action started: 100–500 ms
speech end → audible acknowledgement: 300–900 ms
```

For normal chat/assistant replies:

```txt
speech end → LLM request sent: <100 ms after transcript ready
LLM request → first text delta: 300–1200 ms typical
first useful text → TTS request: immediately
TTS request → first audio PCM: 200–800 ms
speech end → first audible assistant sound: 900–1800 ms typical
```

For interruption:

```txt
user starts speaking while assistant speaks
→ playback stops: <100 ms
→ old TTS/LLM cancelled: <250 ms
→ next turn starts cleanly
```

### UX target

The assistant should never feel like it is doing nothing. UI state should move quickly:

```txt
LISTENING
→ ENDPOINTING
→ THINKING / ACTING
→ SPEAKING
```

For long tasks, speak a tiny acknowledgement quickly:

```txt
"Siap."
"Bentar, aku cek."
"Oke, aku buka."
```

Then continue the actual result.

---

# Current Root Causes

## 1. Current orchestrator is serial

Current flow is effectively:

```python
transcript = await self._transcribe(audio)
reply = await self._respond(transcript, history or [])
await self._speak(reply)
```

This means no overlap between STT, LLM, TTS, and playback.

Impact:

```txt
Total latency ≈ VAD delay + STT full latency + LLM full latency + TTS full latency + playback startup
```

For Jarvis-style voice, the correct mental model is not “make every stage faster only”; it is “overlap stages and emit first feedback early.”

---

## 2. VAD endpointing is too conservative for realtime

Current default:

```toml
end_silence_ms = 1400
min_utterance_ms = 500
speech_start_ms = 160
```

This creates a built-in delay after user stops talking. Even before STT starts, Verse can wait around 1.4 seconds of silence.

Recommended first tuning:

```toml
[vad]
speech_start_ms = 100
min_utterance_ms = 350
end_silence_ms = 650
pre_roll_ms = 250
followup_timeout_s = 3.0
```

Do not hardcode fallback silence as 1.5 seconds. Use config for both Silero and RMS fallback paths.

Need to test Indonesian speech patterns. If 650 ms cuts user off too often, raise to 750–850 ms.

---

## 3. STT is final-only

Current STT interface:

```python
async def transcribe(audio: bytes, language: str | None = None) -> str
```

This forces the whole audio recording to finish before any transcript exists.

Current Groq Whisper path uploads a complete WAV file and waits for final text.

Impact:

```txt
LLM cannot start until all audio is captured, encoded, uploaded, and transcribed.
```

Fix direction:

Introduce a new streaming STT interface later:

```python
class StreamingSTTAdapter:
    async def start_turn(self, language: str | None) -> None: ...
    async def send_audio(self, pcm_chunk: bytes) -> None: ...
    async def end_turn(self) -> None: ...
    async def events(self) -> AsyncIterator[STTEvent]: ...
```

Event types:

```python
@dataclass
class STTEvent:
    type: Literal["partial", "final", "speech_started", "speech_ended", "error"]
    text: str = ""
    stability: float | None = None
    timestamp_ms: int | None = None
```

Short-term, keep final STT but make the rest of the pipeline streaming.

---

## 4. LLM is non-streaming

Current LLM adapter returns a complete `LLMResponse`:

```python
@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None
```

Current DeepSeek adapter uses a normal `chat.completions.create()` call without `stream=True`.

Impact:

```txt
TTS cannot start until the whole response is finished.
UI cannot show assistant partial text.
User perceives “thinking” for the entire generation duration.
```

Fix direction:

Add streaming interface:

```python
@dataclass
class LLMStreamEvent:
    type: Literal[
        "text_delta",
        "tool_call_delta",
        "tool_call_done",
        "done",
        "error"
    ]
    text: str = ""
    tool_call: ToolCall | None = None
    raw: Any = None
```

New base interface:

```python
class LLMAdapter(ABC):
    async def chat(...) -> LLMResponse:
        ...

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        ...
```

DeepSeek streaming implementation should use the OpenAI-compatible stream API:

```python
stream = self.client.chat.completions.create(
    model=self.config.model,
    messages=messages,
    tools=tools or None,
    temperature=self.config.temperature,
    stream=True,
)
```

Important: tool calls need careful handling. If the model starts a tool call, do not speak speculative final text. For tool-heavy requests, either:

1. route locally before LLM, or
2. let the LLM produce tool calls silently, then speak after tool result, or
3. play a canned acknowledgement immediately: “Bentar, aku cek.”

---

## 5. Tool calling can multiply latency

Current `_respond` can loop through tool calls up to `max_tool_iterations`, default 5.

A single command can become:

```txt
LLM call #1 decides tool
→ tool executes
→ LLM call #2 summarizes result
→ TTS
```

For local commands, this is too slow.

Examples that should skip LLM:

```txt
open Chrome
pause music
resume music
set volume 40%
turn brightness up
what time is it
open notes
start listening
stop listening
```

Recommended policy:

```txt
simple action → local router → direct tool → template reply
complex action → small tool subset → one LLM call
chat/reasoning → no tools or selected tools only
```

Change default voice max tool iterations:

```toml
[llm]
max_tool_iterations = 2
```

Or add separate:

```toml
[voice]
max_tool_iterations = 2
```

---

## 6. Too many tools are sent by default

The default tool list is large: music, app, web, notes, reminders, calendar, messaging, contacts, shortcuts, system settings, browser automation, memory, etc.

Sending all tool definitions to the model increases:

```txt
prompt tokens
tool selection complexity
first-token latency
chance of unnecessary tool call
```

Fix direction:

Create tool selection before LLM.

Example:

```python
class ToolSelector:
    def select(self, transcript: str) -> list[str]:
        if looks_like_music(transcript):
            return ["play_music", "pause_music", "resume_music", "stop_music"]
        if looks_like_system_setting(transcript):
            return ["get_volume", "set_volume", "get_brightness", "set_brightness"]
        if looks_like_browser(transcript):
            return ["browser_navigate", "browser_click", "browser_input", "open_url"]
        if looks_like_calendar(transcript):
            return ["calendar_create_event", "calendar_list_events"]
        if looks_like_memory(transcript):
            return ["remember"]
        return []
```

LLM call modes:

```txt
NO_TOOLS:
  normal chat, simple Q&A

FAST_TOOLS:
  tiny selected subset

FULL_TOOLS:
  only when user asks broad agentic task
```

Acceptance target:

```txt
For 80% of voice turns, send 0–5 tools, not the full registry.
```

---

## 7. Memory injection is too heavy for realtime voice

Current defaults include:

```toml
max_history = 10
memory.enabled = true
memory.inject_facts = 18
```

This is fine for rich chat, but too heavy for realtime voice.

For voice mode, use a smaller context budget:

```toml
[llm]
max_history = 4

[memory]
inject_facts = 6
```

Better: create separate voice context config:

```toml
[voice.context]
max_history = 4
inject_facts = 6
max_system_prompt_chars = 2500
```

Also avoid injecting memory for obvious local commands:

```txt
"pause music"
"open chrome"
"volume 30"
```

Those should not need long-term memory.

---

## 8. TTS is the biggest perceived latency bottleneck

Current `_speak()` waits for full TTS synthesis:

```python
audio = await self.tts.synthesize(clean_text)
await asyncio.to_thread(self._play_audio_blocking, audio, stop_event)
```

Current Edge TTS synthesize path:

```txt
text
→ generate full MP3
→ save temp MP3
→ afconvert MP3 to WAV
→ read full WAV bytes
→ play WAV
```

This is bad for realtime.

There is already an `EdgeTTSAdapter.stream()` method, but classic orchestrator does not use it. There is also a `StreamingPlayer`, but it expects 24 kHz int16 mono PCM, while Edge TTS stream likely emits compressed audio chunks.

Required fix:

Add a realtime TTS path that outputs PCM chunks.

New interface:

```python
@dataclass
class AudioFormat:
    sample_rate: int
    channels: int
    sample_width: int
    encoding: Literal["pcm_s16le"]

class StreamingTTSAdapter(ABC):
    @property
    def output_format(self) -> AudioFormat:
        ...

    async def stream_pcm(self, text: str) -> AsyncIterator[bytes]:
        ...
```

Options:

### Option A — Use a provider that supports PCM streaming

Preferred for lowest engineering complexity:

```txt
LLM text segment
→ TTS provider streaming PCM
→ StreamingPlayer.enqueue()
```

### Option B — Keep Edge TTS and decode stream to PCM

Pipeline:

```txt
EdgeTTS MP3 stream
→ ffmpeg stdin
→ PCM s16le stdout
→ StreamingPlayer.enqueue()
```

Pseudo:

```python
async def edge_tts_stream_pcm(text: str) -> AsyncIterator[bytes]:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-i", "pipe:0",
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ac", "1",
        "-ar", "24000",
        "pipe:1",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )

    async def feed_mp3():
        async for mp3_chunk in edge_stream(text):
            proc.stdin.write(mp3_chunk)
            await proc.stdin.drain()
        proc.stdin.close()

    feed_task = asyncio.create_task(feed_mp3())

    while True:
        pcm = await proc.stdout.read(4096)
        if not pcm:
            break
        yield pcm

    await feed_task
```

Acceptance criteria:

```txt
No temp MP3 file in realtime path.
No afconvert in realtime path.
Playback starts after first PCM chunks, not after full sentence audio is finished.
tts_first_audio_ms is logged.
```

---

## 9. StreamingPlayer needs micro-optimization

`StreamingPlayer` is conceptually good, but `enqueue()` uses array concatenation:

```python
self._buffer = np.concatenate([self._buffer, samples])
```

For many small chunks, this repeatedly copies the whole buffer and can become inefficient.

Replace with a deque/ring buffer.

Recommended design:

```python
from collections import deque

self._chunks: deque[np.ndarray] = deque()
self._current_chunk: np.ndarray | None = None
self._current_offset = 0
```

Callback drains chunks without repeatedly concatenating.

Acceptance:

```txt
No large repeated np.concatenate on every audio chunk.
Audio callback never blocks on expensive allocation.
clear() immediately drops queued chunks.
```

---

## 10. Current interruption only stops playback, not the whole turn

Current barge-in mostly stops playback. It does not fully cancel:

```txt
active STT request
active LLM request
active TTS synthesis
active tool task
queued audio chunks
stale callbacks from old turn
```

Need a `TurnContext`.

```python
@dataclass
class TurnContext:
    id: str
    cancel_event: asyncio.Event
    started_at: float
    llm_task: asyncio.Task | None = None
    tts_task: asyncio.Task | None = None
    playback: StreamingPlayer | None = None
    tool_tasks: set[asyncio.Task] = field(default_factory=set)
    cancelled: bool = False

    def is_cancelled(self) -> bool:
        return self.cancelled or self.cancel_event.is_set()
```

Orchestrator should keep:

```python
self.current_turn: TurnContext | None
```

On new turn:

```python
await self.cancel_current_turn(reason="new_user_turn")
self.current_turn = TurnContext(...)
```

On barge-in:

```python
async def request_barge_in(self) -> bool:
    turn = self.current_turn
    if not turn:
        return False

    turn.cancelled = True
    turn.cancel_event.set()

    if turn.playback:
        turn.playback.clear()

    for task in [turn.llm_task, turn.tts_task, *turn.tool_tasks]:
        if task and not task.done():
            task.cancel()

    await self._safe_stop_audio()
    self._emit_event("barge_in_cancelled", turn_id=turn.id)
    await self.start_listening()
    return True
```

Every callback must check `turn_id`:

```python
def is_current_turn(turn: TurnContext) -> bool:
    return self.current_turn is not None and self.current_turn.id == turn.id
```

Before playing audio:

```python
if not is_current_turn(turn) or turn.is_cancelled():
    return
```

Before sending UI text:

```python
if not is_current_turn(turn):
    return
```

Acceptance:

```txt
If user interrupts while TTS is generating, generation stops.
If user interrupts while LLM is streaming, stream is cancelled.
If old stream emits after cancellation, it is ignored.
No old audio resumes after interruption.
```

---

# Recommended Implementation Roadmap

## P0 — Add latency instrumentation before changing architecture

Do this first so every improvement is measurable.

Add a `LatencyTracker`.

```python
@dataclass
class LatencyEvent:
    name: str
    ts: float
    data: dict[str, Any] = field(default_factory=dict)

class LatencyTracker:
    def __init__(self, turn_id: str):
        self.turn_id = turn_id
        self.t0 = time.perf_counter()
        self.events: list[LatencyEvent] = []

    def mark(self, name: str, **data: Any) -> None:
        self.events.append(
            LatencyEvent(name=name, ts=time.perf_counter(), data=data)
        )

    def summary(self) -> dict[str, Any]:
        base = self.t0
        return {
            "turn_id": self.turn_id,
            "events": [
                {
                    "name": e.name,
                    "ms": round((e.ts - base) * 1000),
                    "data": e.data,
                }
                for e in self.events
            ],
        }
```

Log these events:

```txt
hotkey_down
record_start
vad_speech_start
vad_speech_end
audio_wav_ready
stt_start
stt_final
local_intent_start
local_intent_done
llm_request_start
llm_first_token
llm_done
tool_start
tool_done
tts_request_start
tts_first_audio
playback_start
playback_done
barge_in_detected
cancel_start
cancel_done
turn_done
```

Each turn summary should include:

```json
{
  "turn_id": "...",
  "audio_ms": 1240,
  "transcript_chars": 42,
  "provider": {
    "stt": "groq",
    "llm": "deepseek",
    "tts": "edge-tts"
  },
  "latency": {
    "vad_to_stt_start_ms": 20,
    "stt_ms": 850,
    "llm_first_token_ms": 620,
    "llm_total_ms": 1700,
    "tts_first_audio_ms": 430,
    "tts_total_ms": 1300,
    "speech_end_to_first_audio_ms": 1650
  },
  "tool_count": 0,
  "cancelled": false
}
```

Acceptance:

```txt
Every voice turn produces one JSON latency summary.
Metrics separate STT, LLM, TTS, playback, tools, and cancellation.
```

---

## P1 — Low-risk quick wins

### P1.1 Tune VAD defaults

Change default:

```toml
[vad]
speech_start_ms = 100
min_utterance_ms = 350
end_silence_ms = 700
pre_roll_ms = 250
followup_timeout_s = 3.0
```

Make RMS fallback use the same endpointing config instead of hardcoded 1.5 seconds.

Acceptance:

```txt
Silence after speech feels under 1 second.
No frequent cutoff during normal Indonesian speech.
```

### P1.2 Separate UI state: thinking vs speaking

Current `_speak()` marks TTS-ready before audio is actually available. That can make UI say “speaking” while TTS is still generating.

Change states:

```txt
THINKING: LLM/tool running
PREPARING_AUDIO: TTS request started
SPEAKING: first audio chunk is actually playing
```

Acceptance:

```txt
SPEAKING state only begins when playback starts or first PCM chunk is queued.
```

### P1.3 Shrink voice context

For voice turns:

```toml
[llm]
max_history = 4

[memory]
inject_facts = 6
```

Skip memory injection for local commands.

Acceptance:

```txt
Local commands do not build long memory-heavy prompts.
```

### P1.4 Reduce voice tool iterations

Set:

```toml
[voice]
max_tool_iterations = 2
```

or change voice path to use 2 while preserving 5 for non-voice agent mode.

Acceptance:

```txt
Voice tool requests do not loop up to 5 LLM calls unless explicitly in agentic mode.
```

### P1.5 Improve local intent router coverage

Commands to route locally:

```txt
open app
close app
play music
pause music
resume music
volume up/down/set
brightness up/down/set
open website
search web
what time is it
take note
remember this
```

For local intent, return canned reply immediately:

```txt
"Siap."
"Oke."
"Volume aku set ke 40%."
"Aku buka Chrome."
```

Acceptance:

```txt
Common system commands avoid LLM entirely.
```

---

## P2 — Realtime TTS and playback

This should be the first major architectural improvement because it directly reduces perceived latency.

### P2.1 Add streamable PCM TTS interface

Add:

```python
class RealtimeTTSAdapter(ABC):
    @property
    def sample_rate(self) -> int:
        return 24000

    @property
    def channels(self) -> int:
        return 1

    async def stream_pcm(self, text: str) -> AsyncIterator[bytes]:
        ...
```

### P2.2 Add `speak_streaming()`

New orchestrator method:

```python
async def speak_streaming(
    self,
    turn: TurnContext,
    text_stream: AsyncIterator[str],
) -> None:
    segmenter = TextSegmenter()
    player = StreamingPlayer(sample_rate=24000)
    turn.playback = player

    async for delta in text_stream:
        if turn.is_cancelled():
            break

        for segment in segmenter.push(delta):
            if not segment.strip():
                continue

            async for pcm in self.tts.stream_pcm(segment):
                if turn.is_cancelled():
                    break
                if not player.is_playing:
                    self.latency.mark("tts_first_audio")
                    self.latency.mark("playback_start")
                player.enqueue(pcm)

    for final_segment in segmenter.flush():
        async for pcm in self.tts.stream_pcm(final_segment):
            if turn.is_cancelled():
                break
            player.enqueue(pcm)

    player.signal_end()
    await player.wait_drained()
```

### P2.3 Text segmentation rules

Do not send one character at a time to TTS. Buffer until useful phrase boundary.

Segment when:

```txt
- sentence punctuation appears: . ! ? … 
- comma/semicolon with enough length
- buffer length >= 80 chars
- no new token for 250–400 ms and buffer length >= 20 chars
```

Avoid tiny segments like:

```txt
"aku"
"akan"
"membuka"
```

Better:

```txt
"Aku buka Chrome sekarang."
"Bentar, aku cek kalender kamu."
```

### P2.4 Keep canned acknowledgements separate

For slow tools, do not wait for model text.

Example:

```python
await self.speak_text_immediately(turn, "Bentar, aku cek.")
result = await run_tool(...)
await self.speak_streaming(turn, summarize_result_stream(result))
```

Acceptance:

```txt
TTS first audio starts before the full response is generated.
No temp file or afconvert in realtime TTS path.
Playback uses StreamingPlayer for realtime voice.
```

---

## P3 — Streaming LLM

### P3.1 Add stream interface to all LLM adapters

Implement at least for DeepSeek first. Keep non-streaming `chat()` for compatibility.

```python
async def stream_chat(
    self,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
) -> AsyncIterator[LLMStreamEvent]:
    ...
```

### P3.2 Wire stream to TTS

New flow after transcript:

```txt
transcript
→ local intent?
  → yes: execute and speak canned reply
  → no: stream LLM
      → text deltas to segmenter
      → segmenter to TTS
      → TTS PCM to playback
```

Pseudo:

```python
async def respond_streaming(self, turn: TurnContext, transcript: str):
    local = await self._try_local_intent(transcript)
    if local:
        await self.speak_text_immediately(turn, local.reply)
        return

    messages = await self._build_messages(transcript)
    tools = self._select_tools(transcript)

    async def text_stream():
        async for event in self.llm.stream_chat(messages, tools=tools):
            if turn.is_cancelled():
                break

            if event.type == "text_delta":
                yield event.text

            elif event.type in ("tool_call_delta", "tool_call_done"):
                # stop normal speech path; handle tool flow
                ...

    await self.speak_streaming(turn, text_stream())
```

### P3.3 Tool calls in streaming mode

For streaming tool calls, use a conservative policy:

```txt
If tool call starts before any user-facing text:
  do not speak model text yet
  run tool
  then stream final answer

If model already emitted meaningful text:
  either continue only if no tool call,
  or cancel that stream and switch to tool mode
```

For most local commands, avoid this entirely by routing before LLM.

Acceptance:

```txt
`llm_first_token_ms` is logged.
Assistant text appears incrementally in UI.
TTS begins before `llm_done` for normal text responses.
```

---

## P4 — Full turn controller and cancellation

### P4.1 Add `TurnContext`

```python
@dataclass
class TurnContext:
    id: str
    cancel_event: asyncio.Event
    latency: LatencyTracker
    playback: StreamingPlayer | None = None
    llm_task: asyncio.Task | None = None
    tts_task: asyncio.Task | None = None
    tool_tasks: set[asyncio.Task] = field(default_factory=set)
    cancelled: bool = False

    def cancel(self):
        self.cancelled = True
        self.cancel_event.set()

    def is_cancelled(self) -> bool:
        return self.cancelled or self.cancel_event.is_set()
```

### P4.2 Guard all output by turn ID

Never let stale turn update UI or play audio.

```python
def _is_active_turn(self, turn: TurnContext) -> bool:
    return self.current_turn is not None and self.current_turn.id == turn.id
```

Use this guard before:

```txt
on_transcript
on_assistant_text
on_assistant_partial_text
on_tool_status
on_audio_start
playback enqueue
state transitions
debug output finalization
```

### P4.3 Make barge-in cancel all active work

```python
async def cancel_current_turn(self, reason: str):
    turn = self.current_turn
    if not turn:
        return

    turn.latency.mark("cancel_start", reason=reason)
    turn.cancel()

    if turn.playback:
        turn.playback.clear()

    for task in [turn.llm_task, turn.tts_task, *turn.tool_tasks]:
        if task and not task.done():
            task.cancel()

    await self._stop_audio_output()

    turn.latency.mark("cancel_done")
```

### P4.4 Barge-in while THINKING too

Do not only allow barge-in while assistant is audibly speaking. If user starts speaking again while LLM/TTS is still preparing, cancel that pending turn.

```txt
SPEAKING + user speech → cancel playback and generation
THINKING + user speech → cancel LLM/tool/TTS
PREPARING_AUDIO + user speech → cancel TTS before audio starts
```

Acceptance:

```txt
User can interrupt during thinking, TTS preparation, and speaking.
Old request cannot leak text or audio into the new turn.
```

---

## P5 — Tool selection and local-first command execution

### P5.1 Add intent categories

```python
class IntentCategory(Enum):
    LOCAL_SYSTEM = "local_system"
    MUSIC = "music"
    APP = "app"
    BROWSER = "browser"
    CALENDAR = "calendar"
    NOTES = "notes"
    MEMORY = "memory"
    CHAT = "chat"
    UNKNOWN = "unknown"
```

### P5.2 Route before LLM

```python
category, confidence = fast_intent_classifier(transcript)

if confidence >= 0.70 and category in LOCAL_CATEGORIES:
    return await execute_local(transcript, category)

tools = tool_selector.select(transcript, category)
return await llm_stream(transcript, tools)
```

Use lower threshold for harmless commands and higher threshold for destructive commands.

Examples:

```txt
set volume → okay at 0.65
delete reminder → require 0.85 or confirmation
send message → require confirmation
```

### P5.3 Template replies for local tools

Do not call LLM just to say “done.”

```python
LOCAL_REPLIES = {
    "set_volume": "Oke, volume aku set ke {value}%.",
    "open_app": "Siap, aku buka {app}.",
    "pause_music": "Oke, aku pause.",
}
```

Acceptance:

```txt
Common commands execute with zero LLM calls.
Tool definitions sent to LLM are selected, not the whole list.
```

---

## P6 — Streaming STT / partial transcript

After P2–P4 are stable, implement partial STT.

### P6.1 Add streaming STT provider

Use a provider that supports realtime partials. The interface should support:

```txt
send PCM chunks
receive partial transcript
receive final transcript
receive endpoint event
```

### P6.2 UI partial transcript

Frontend should receive:

```json
{
  "type": "user_partial_transcript",
  "turn_id": "...",
  "text": "open chrom..."
}
```

Then:

```json
{
  "type": "user_final_transcript",
  "turn_id": "...",
  "text": "open Chrome"
}
```

### P6.3 Early local intent from stable partials

For safe local commands, execute from stable partials:

```txt
partial: "open chrome"
stable for 250 ms
confidence high
→ execute immediately
```

Be conservative for actions like messaging, deleting, buying, sending.

Acceptance:

```txt
Partial text appears while user speaks.
Safe local commands can trigger before final STT when stable.
```

---

## P7 — Optional true realtime engine

The config already has a concept of:

```txt
classic_pipeline
gemini_live
```

For the smoothest Jarvis demo, a live speech-to-speech engine may outperform manually chained STT→LLM→TTS.

Implement `VoiceEngine` abstraction:

```python
class VoiceEngine(ABC):
    async def start_session(self): ...
    async def send_audio(self, pcm: bytes): ...
    async def events(self) -> AsyncIterator[VoiceEvent]: ...
    async def cancel_response(self): ...
    async def close(self): ...
```

Engines:

```txt
ClassicPipelineEngine:
  current architecture, improved with streaming

LiveRealtimeEngine:
  one persistent realtime session
  server-side VAD
  streaming audio response
  built-in interruption
```

Acceptance:

```txt
Can switch engine from config.
Classic pipeline remains fallback.
Live engine supports persistent session and response cancellation.
```

---

# Micro UX Recommendations

## 1. Immediate UI feedback

When user starts speaking:

```txt
Dynamic Island: listening animation immediately
```

When VAD thinks speech ended:

```txt
Dynamic Island: tiny pulse / endpointing
```

When STT is done:

```txt
Dynamic Island: show transcript immediately
```

When LLM starts:

```txt
Dynamic Island: thinking
```

When tool starts:

```txt
Dynamic Island: "Opening Chrome..." / "Checking calendar..."
```

When first audio plays:

```txt
Dynamic Island: speaking
```

## 2. Fake “dead time” with honest micro acknowledgements

For slow tasks:

```txt
"Bentar."
"Siap, aku cek."
"Oke, aku jalanin."
```

But do not use acknowledgements for every turn. For very short commands, action itself is enough.

## 3. Do not wait for final response to update UI

Stream assistant partial text:

```json
{
  "type": "assistant_text_delta",
  "turn_id": "...",
  "delta": "Aku buka Chrome"
}
```

## 4. Keep voice replies short

For voice mode, system prompt should say:

```txt
You are a realtime voice assistant. Keep responses concise.
For local actions, answer in one short phrase.
Do not explain unless asked.
```

This reduces LLM generation and TTS time.

---

# Testing Plan

## Unit tests

### VAD endpointing

Fake frames:

```txt
speech 1.2s
silence 0.7s
```

Expected:

```txt
endpoint fires around configured end_silence_ms
```

### Local router

Inputs:

```txt
"open chrome"
"pause music"
"volume 40"
"brightness down"
```

Expected:

```txt
no LLM call
correct tool called
template reply returned
```

### Text segmenter

Input deltas:

```txt
"Aku "
"buka "
"Chrome "
"sekarang."
```

Expected segment:

```txt
"Aku buka Chrome sekarang."
```

### Turn cancellation

Simulate:

```txt
LLM streaming
TTS streaming
playback active
barge-in event
```

Expected:

```txt
playback.clear called
LLM task cancelled
TTS task cancelled
stale deltas ignored
```

---

## Integration tests with fake providers

Create fake adapters:

```python
class FakeSTT:
    delay_ms = 500

class FakeLLM:
    first_token_delay_ms = 300
    token_interval_ms = 50

class FakeTTS:
    first_audio_delay_ms = 200
    chunk_interval_ms = 20
```

Test:

```txt
LLM stream lasts 3 seconds
TTS should start before LLM stream ends
playback_start should occur before llm_done
```

Acceptance:

```txt
speech_end_to_first_audio_ms < 1500 in fake pipeline
barge-in stops audio <100 ms
```

---

# Suggested Implementation Order

## Milestone 1 — Measurement and safe quick wins

1. Add `LatencyTracker`.
2. Emit per-turn JSON summary.
3. Tune VAD config.
4. Reduce voice history and memory facts.
5. Lower voice tool iterations.
6. Expand local intent templates.
7. Separate `PREPARING_AUDIO` and `SPEAKING` state.

Expected outcome:

```txt
Less random delay.
Clear bottleneck metrics.
Simple commands feel faster.
```

---

## Milestone 2 — Realtime TTS

1. Add `stream_pcm()` TTS interface.
2. Wire `StreamingPlayer` into orchestrator.
3. Remove temp-file/afconvert path from realtime speaking.
4. Add text segmenter.
5. Start playback from first audio chunk.
6. Optimize StreamingPlayer buffer from concat to deque/ring buffer.

Expected outcome:

```txt
Assistant starts speaking much earlier.
TTS no longer waits for full audio file.
```

---

## Milestone 3 — Streaming LLM

1. Add `LLMStreamEvent`.
2. Implement `DeepSeekAdapter.stream_chat`.
3. Stream text deltas into text segmenter.
4. TTS begins before LLM completion.
5. Add streaming UI deltas.

Expected outcome:

```txt
Normal replies feel alive.
Dynamic Island can show assistant text while model is still generating.
```

---

## Milestone 4 — Full cancellation / interruption

1. Add `TurnContext`.
2. Make all stages cancellable.
3. Guard callbacks by `turn_id`.
4. Cancel LLM/TTS/tool/playback on barge-in.
5. Allow barge-in during THINKING and PREPARING_AUDIO, not only SPEAKING.

Expected outcome:

```txt
Interruption feels instant and reliable.
No stale response leaks.
```

---

## Milestone 5 — Streaming STT

1. Add streaming STT adapter.
2. Send mic chunks while user speaks.
3. Show partial transcript in UI.
4. Execute safe local commands from stable partial transcript.
5. Keep final transcript for correction.

Expected outcome:

```txt
Assistant can prepare before the user fully stops.
Simple commands can trigger extremely fast.
```

---

# Definition of Done

The overhaul is successful when these are true:

```txt
1. Common local command uses zero LLM calls.
2. VAD endpoint delay is normally under 800 ms.
3. LLM first token is measured separately from total LLM time.
4. TTS first audio is measured separately from total TTS time.
5. Playback can start before LLM response is complete.
6. User can interrupt while assistant is thinking, preparing audio, or speaking.
7. Old turn text/audio never appears after interruption.
8. Per-turn latency summary is saved for debugging.
9. Dynamic Island state reflects actual stage accurately.
10. No temp MP3/WAV conversion is used in realtime speaking path.
```

---

# Most Important Code-Level Priorities

Implement in this order:

```txt
P0: LatencyTracker + JSON summaries
P1: VAD tuning + voice context reduction + better local intent
P2: Streaming TTS to PCM + StreamingPlayer integration
P3: Streaming LLM + assistant text deltas
P4: TurnContext cancellation + robust barge-in
P5: Tool selector and local-first execution
P6: Streaming STT with partial transcripts
P7: Optional live realtime engine
```

The biggest immediate latency win is P2: streaming TTS. The biggest “Jarvis feel” win is P4: true interruption. The biggest long-term architecture win is P6/P7: streaming STT or a persistent realtime voice engine.
