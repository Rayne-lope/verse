from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from verse.config import AppConfig
from verse.intent import LocalIntentMatch, LocalIntentRouter
from verse.llm.base import LLMAdapter
from verse.state import State, StateMachine, StateChangedEvent
from verse.stt.base import STTAdapter
from verse.tools.registry import ToolRegistry
from verse.tts.base import TTSAdapter
from verse.persistence.debug_logger import DebugSessionLogger

DEFAULT_SYSTEM_PROMPT = (
    "You are Verse, a concise voice assistant for macOS. "
    "Reply in the same language the user speaks. "
    "Keep answers short and natural since they will be spoken aloud. "
    "Use the available tools to control music, open apps, search the web, "
    "or check the time when the user asks for those actions. "
    "CRITICAL: When the user asks to change or check system settings (volume, brightness, mute, dark mode, DND), "
    "you MUST always call the respective tool first in the same turn. "
    "NEVER guess, assume, or claim that a setting has changed or been checked unless you have successfully executed the tool. "
    "If the user provides a standalone setting parameter (e.g., '30', 'gelap', 'terang') during a settings conversation, "
    "treat it as a command to adjust that setting and call the tool immediately."
)

logger = logging.getLogger(__name__)

PlaybackFn = Callable[..., None]


def _project_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project stored message rows down to clean LLM messages.

    `ConversationStore.load_recent_messages` returns extra columns (id, conv_id,
    created_at) that LLM adapters don't expect — keep only role/content (+ tool_calls
    for assistant messages). Rows without text content are dropped.
    """
    projected: list[dict[str, Any]] = []
    for row in rows:
        role = row.get("role")
        content = row.get("content")
        if not role or content is None:
            continue
        msg: dict[str, Any] = {"role": role, "content": content}
        if role == "assistant" and row.get("tool_calls"):
            msg["tool_calls"] = row["tool_calls"]
        projected.append(msg)
    return projected


def _parse_fact_list(text: str) -> list[str]:
    """Best-effort parse of an LLM reply into a list of fact strings. Tolerates
    code fences and surrounding prose by extracting the first JSON array."""
    if not text:
        return []
    import json
    import re

    snippet = text.strip()
    if "```" in snippet:
        snippet = re.sub(r"```(?:json)?", "", snippet).strip("` \n")
    match = re.search(r"\[.*\]", snippet, re.DOTALL)
    if match:
        snippet = match.group(0)
    try:
        data = json.loads(snippet)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [item.strip() for item in data if isinstance(item, str) and item.strip()]


class Orchestrator:
    def __init__(
        self,
        *,
        stt: STTAdapter,
        llm: LLMAdapter,
        tts: TTSAdapter,
        registry: ToolRegistry,
        state_machine: StateMachine,
        config: AppConfig | None = None,
        recorder: Any | None = None,
        play: PlaybackFn | None = None,
        on_transcript: Callable[[str], None] | None = None,
        on_assistant_text: Callable[[str], None] | None = None,
        on_tool_executed: Callable[[str, str], None] | None = None,
        on_audio_level: Callable[[float], None] | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tool_iterations: int = 5,
        vad_manager: Any | None = None,
        vad_state_machine: Any | None = None,
        pre_vad_audio_hook: Callable[[Any], Any] | None = None,
        post_recording_audio_hook: Callable[[Any], Any] | None = None,
        clean_for_stt: Callable[[bytes], bytes] | None = None,
        debug_logger: DebugSessionLogger | None = None,
        store: Any | None = None,
    ) -> None:
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.registry = registry
        self.state_machine = state_machine
        self.config = config or AppConfig()
        self.recorder = recorder
        self._play = play
        self.on_transcript = on_transcript
        self.on_assistant_text = on_assistant_text
        self.on_tool_executed = on_tool_executed
        self.on_audio_level = on_audio_level
        self.system_prompt = system_prompt
        self.max_tool_iterations = max_tool_iterations
        self.local_intent_router = LocalIntentRouter()

        self.pre_vad_audio_hook = pre_vad_audio_hook
        self.post_recording_audio_hook = post_recording_audio_hook
        self.clean_for_stt = clean_for_stt

        if self.recorder is not None:
            for hook_name in ("pre_vad_audio_hook", "post_recording_audio_hook", "clean_for_stt"):
                val = getattr(self, hook_name)
                if val is not None:
                    try:
                        setattr(self.recorder, hook_name, val)
                    except AttributeError:
                        pass

        self.vad_manager = vad_manager
        if self.vad_manager is None:
            from verse.audio.vad import SileroVADManager
            self.vad_manager = SileroVADManager(model_path=self.config.vad.model_path)

        self.vad_state_machine = vad_state_machine
        if self.vad_state_machine is None:
            from verse.audio.vad import VADEndpointingStateMachine
            self.vad_state_machine = VADEndpointingStateMachine(self.config.vad)

        self.on_vad_state: Callable[[str, float], None] | None = None
        self._user_on_pipeline_event = None
        self._wrapped_on_pipeline_event = None

        self.debug_logger = debug_logger
        if self.debug_logger is None and getattr(self.config.debug, "session_logging", False):
            try:
                from verse.persistence.debug_logger import DebugSessionLogger
                self.debug_logger = DebugSessionLogger()
            except Exception as exc:
                logger.error(f"Failed to auto-initialize DebugSessionLogger: {exc}")

        self._update_wrapped_on_pipeline_event()
        self._vad_task: asyncio.Task | None = None

        self._auto_listening = False
        # Continuous conversation is OFF until explicitly toggled on via
        # start_auto_listening(). PTT stays one-shot.
        self._conversation_mode_active: bool = False
        self._speech_detected = False
        self._last_speech_time = 0.0
        self._auto_listen_start_real_time = 0.0
        self._loop = None
        self._playback_stop_event: threading.Event | None = None
        self._barge_in_requested = False
        self._barge_in_handled = False

        self._current_turn_id: int | None = None
        self._current_vad_timeline: list[dict[str, Any]] = []
        self._current_pipeline_events: list[dict[str, Any]] = []
        self._current_latency_metrics: dict[str, Any] = {}
        self._input_audio_bytes: bytes | None = None
        self._output_audio_bytes: bytes | None = None
        self._llm_messages: list[dict[str, Any]] = []
        self._llm_response: dict[str, Any] = {}

        # --- Memory ---------------------------------------------------------
        # Short-term: a rolling window of {role, content} messages used as LLM
        # context. Long-term: durable facts persisted in `store`, injected into
        # the system prompt. The store is optional so tests run without a DB.
        self.store = store
        self.conv_id: int | None = None
        self._conversation_history: list[dict[str, Any]] = []
        if self.store is not None and self.config.memory.enabled:
            try:
                self.conv_id = self.store.new_conversation()
                # Seed with recent messages across previous sessions so Verse
                # "remembers" the last conversation when it starts up.
                seeded = self.store.load_recent_messages(
                    limit=self.config.llm.max_history * 2
                )
                self._conversation_history = _project_history(seeded)
            except Exception as exc:
                logger.error(f"Failed to init conversation memory: {exc}")
                self.store = None

        self._state_machine_unsubscribe = self.state_machine.subscribe(self._on_state_changed)

    @property
    def conversation_mode_active(self) -> bool:
        return self._conversation_mode_active

    @property
    def on_pipeline_event(self) -> Callable[[str, str, dict[str, Any]], None] | None:
        if self.debug_logger is not None:
            return self._wrapped_on_pipeline_event
        return self._user_on_pipeline_event

    @on_pipeline_event.setter
    def on_pipeline_event(self, value: Callable[[str, str, dict[str, Any]], None] | None) -> None:
        self._user_on_pipeline_event = value
        self._update_wrapped_on_pipeline_event()

    def _update_wrapped_on_pipeline_event(self) -> None:
        def wrapped(stage: str, event: str, metadata: dict[str, Any]) -> None:
            import time
            if self._current_turn_id is not None:
                self._current_pipeline_events.append({
                    "timestamp": time.time(),
                    "stage": stage,
                    "event": event,
                    "metadata": metadata
                })
            if self._user_on_pipeline_event is not None:
                try:
                    self._user_on_pipeline_event(stage, event, metadata)
                except Exception:
                    logger.exception("Error in user on_pipeline_event callback")
        self._wrapped_on_pipeline_event = wrapped

    def _write_current_turn_data(self) -> None:
        if self.debug_logger is None or self._current_turn_id is None:
            return
        
        turn_id = self._current_turn_id
        
        if self._input_audio_bytes is not None:
            self.debug_logger.log_input_audio(turn_id, self._input_audio_bytes)
            
        if self._output_audio_bytes is not None:
            self.debug_logger.log_output_audio(turn_id, self._output_audio_bytes)
            
        if self._current_vad_timeline:
            self.debug_logger.log_vad_timeline(turn_id, self._current_vad_timeline)
            
        if self._current_pipeline_events:
            self.debug_logger.log_pipeline_events(turn_id, self._current_pipeline_events)
            
        if self._llm_messages or self._llm_response:
            self.debug_logger.log_llm_transaction(turn_id, self._llm_messages, self._llm_response)
            
        if self._current_latency_metrics:
            self.debug_logger.log_metrics(turn_id, self._current_latency_metrics)
            
        self._current_turn_id = None

    def start_listening(self, is_auto: bool = False) -> bool:
        if self.recorder is None:
            raise RuntimeError("Orchestrator has no recorder configured")
        # Ignore presses while busy or during the error-reset window.
        if self.recorder.is_recording or not self.state_machine.is_idle:
            return False
        if not is_auto:
            # Explicit PTT press → one-shot turn, no auto-continue.
            self._auto_listening = False
            self._conversation_mode_active = False

        if self.debug_logger is not None:
            if self._current_turn_id is not None:
                self._write_current_turn_data()
            self._current_turn_id = self.debug_logger.new_turn()
            self._current_vad_timeline = []
            self._current_pipeline_events = []
            self._current_latency_metrics = {}
            self._input_audio_bytes = None
            self._output_audio_bytes = None
            self._llm_messages = []
            self._llm_response = {}

        self.state_machine.hotkey_pressed()
        self.recorder.start_recording(on_audio_level=self._handle_audio_level)
        return True

    async def stop_and_respond(
        self, *, history: list[dict[str, Any]] | None = None
    ) -> str:
        if self.recorder is None:
            raise RuntimeError("Orchestrator has no recorder configured")
        if not self.recorder.is_recording:
            return ""
        self._auto_listening = False
        self._cancel_vad_task()
        audio = self.recorder.stop_recording()
        
        if _is_audio_too_short(audio):
            self.state_machine.audio_done()
            if self.conversation_mode_active:
                self.start_auto_listening()
            return ""
            
        self._input_audio_bytes = audio

        self.state_machine.hotkey_released()
        return await self.handle_audio(audio, history=history)

    async def handle_audio(
        self, audio: bytes, *, history: list[dict[str, Any]] | None = None
    ) -> str:
        import time
        turn_id = self._current_turn_id
        self._input_audio_bytes = audio

        try:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            start_stt = time.time()
            transcript = await self._transcribe(audio)
            stt_duration = time.time() - start_stt
            print(f"[Debug] STT took: {stt_duration:.2f}s")
            
            if self.debug_logger is not None and self._current_turn_id == turn_id and turn_id is not None:
                self._current_latency_metrics["stt_ms"] = int(stt_duration * 1000)

            start_llm = time.time()
            reply = await self._respond(transcript, history or [])
            llm_duration = time.time() - start_llm
            print(f"[Debug] LLM took: {llm_duration:.2f}s")

            if self.debug_logger is not None and self._current_turn_id == turn_id and turn_id is not None:
                self._current_latency_metrics["llm_ms"] = int(llm_duration * 1000)

            start_tts = time.time()
            await self._speak(reply)
            tts_duration = time.time() - start_tts
            print(f"[Debug] TTS took: {tts_duration:.2f}s")

            if self.debug_logger is not None and self._current_turn_id == turn_id and turn_id is not None:
                self._current_latency_metrics["tts_ms"] = int(tts_duration * 1000)
                self._write_current_turn_data()

            return reply
        except Exception as exc:  # surface failure to UI/state machine
            if self.on_pipeline_event:
                self.on_pipeline_event(
                    "error",
                    "recoverable_error",
                    {"code": "pipeline_failure", "message": str(exc)}
                )
            self.state_machine.fail(str(exc))
            if self.debug_logger is not None and turn_id is not None:
                import traceback
                self.debug_logger.log_error(
                    turn_id,
                    error_type=exc.__class__.__name__,
                    message=str(exc),
                    traceback=traceback.format_exc(),
                )
                if self._current_turn_id == turn_id:
                    self._write_current_turn_data()
            raise

    async def _transcribe(self, audio: bytes) -> str:
        language = self.config.stt.language
        if self.on_pipeline_event:
            self.on_pipeline_event("stt", "started", {})
        transcript = await self.stt.transcribe(audio, language=language)
        transcript = transcript.strip()
        if self.on_pipeline_event:
            self.on_pipeline_event("stt", "completed", {"text": transcript})
        if self.on_transcript:
            self.on_transcript(transcript)
        return transcript

    async def _respond(self, transcript: str, history: list[dict[str, Any]]) -> str:
        local_reply = self._try_local_intent(transcript)
        if local_reply is not None:
            self._llm_messages = [{"role": "user", "content": transcript}]
            self._llm_response = {"text": local_reply}
            self._remember_turn(transcript, local_reply)
            return local_reply

        # Use caller-supplied history if given (tests), else the rolling session
        # history (within + carried over from previous sessions).
        base_history = history if history else self._conversation_history
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._compose_system_prompt()},
            *base_history,
            {"role": "user", "content": transcript},
        ]
        definitions = self.registry.list_definitions(self.config.tools.enabled)
        tools = definitions or None

        reply = ""
        total_tool_ms = 0.0
        for _ in range(self.max_tool_iterations):
            response = await self.llm.chat(messages, tools=tools)
            if not response.tool_calls:
                reply = response.text.strip()
                self._llm_response = {
                    "text": reply,
                    "tool_calls": []
                }
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response.text or None,
                    "tool_calls": response.tool_calls,
                }
            )
            for tool_call in response.tool_calls:
                import time
                start_tool = time.time()
                result = self._run_tool(tool_call)
                tool_duration = time.time() - start_tool
                total_tool_ms += tool_duration

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": result,
                    }
                )
        else:
            # Exhausted iterations; do a final toolless call for a clean answer.
            response = await self.llm.chat(messages)
            reply = response.text.strip()
            self._llm_response = {
                "text": reply,
                "tool_calls": []
            }

        self._llm_messages = messages
        if self.debug_logger is not None and self._current_turn_id is not None:
            self._current_latency_metrics["tool_ms"] = int(total_tool_ms * 1000)

        self._remember_turn(transcript, reply)

        if self.on_assistant_text:
            self.on_assistant_text(reply)
        return reply

    # --- Memory -----------------------------------------------------------
    def _compose_system_prompt(self) -> str:
        """Base system prompt + a compact block of long-term facts about the user."""
        base = self.system_prompt
        if self.store is None or not self.config.memory.enabled:
            return base
        try:
            facts = self.store.load_memories(limit=self.config.memory.inject_facts)
        except Exception as exc:
            logger.error(f"load_memories failed: {exc}")
            return base
        if not facts:
            return base
        block = "\n".join(f"- {fact}" for fact in facts)
        return (
            f"{base}\n\n"
            "Long-term memory about the user (use naturally, don't recite verbatim):\n"
            f"{block}"
        )

    def _remember_turn(self, transcript: str, reply: str) -> None:
        """Append the turn to the rolling history, persist it, and schedule
        long-term fact extraction. Best-effort: never raises into the pipeline."""
        if not self.config.memory.enabled:
            return
        transcript = (transcript or "").strip()
        reply = (reply or "").strip()
        if not transcript:
            return

        self._conversation_history.append({"role": "user", "content": transcript})
        if reply:
            self._conversation_history.append({"role": "assistant", "content": reply})
        max_msgs = max(2, self.config.llm.max_history * 2)
        if len(self._conversation_history) > max_msgs:
            self._conversation_history = self._conversation_history[-max_msgs:]

        if self.store is None or self.conv_id is None:
            return
        try:
            self.store.save_message(self.conv_id, "user", transcript)
            if reply:
                self.store.save_message(self.conv_id, "assistant", reply)
        except Exception as exc:
            logger.error(f"save_message failed: {exc}")
        self._schedule_memory_extraction(transcript, reply)

    def _schedule_memory_extraction(self, transcript: str, reply: str) -> None:
        """Fire-and-forget extraction so it never adds latency to the spoken reply."""
        if self.store is None or not self.config.memory.extract:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # no event loop (e.g. sync unit test) → skip extraction
        loop.create_task(self._extract_memories(transcript, reply))

    async def _extract_memories(self, transcript: str, reply: str) -> None:
        try:
            existing = self.store.load_memories(limit=self.config.memory.max_facts)
            existing_block = "\n".join(f"- {fact}" for fact in existing) or "(none yet)"
            system = (
                "You extract durable, long-term facts about the USER from one chat turn. "
                "Return ONLY a JSON array of short fact strings worth remembering across "
                "sessions (name, preferences, projects, relationships, stable traits). "
                "Exclude transient/one-off details, questions, and anything already known. "
                "If there is nothing new, return []."
            )
            user = (
                f"Already known facts:\n{existing_block}\n\n"
                f"User said: {transcript}\n"
                f"Assistant replied: {reply}\n\n"
                "New durable facts (JSON array of strings):"
            )
            response = await self.llm.chat(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ]
            )
            facts = _parse_fact_list(getattr(response, "text", "") or "")
            added = False
            for fact in facts:
                if self.store.upsert_memory(fact) is not None:
                    added = True
            if added:
                self.store.prune_memories(max_count=self.config.memory.max_facts)
        except Exception as exc:
            logger.error(f"memory extraction failed: {exc}")

    def _try_local_intent(self, transcript: str) -> str | None:
        if not self.config.intent.local_router_enabled:
            return None

        match = self.local_intent_router.route(transcript)
        if match is None:
            return None

        threshold = self.config.intent.local_router_confidence_threshold
        if match.confidence < threshold:
            if self.on_pipeline_event:
                self.on_pipeline_event(
                    "intent",
                    "local_missed",
                    {
                        "intent": match.intent,
                        "confidence": match.confidence,
                        "threshold": threshold,
                    },
                )
            return None

        if match.tool_name and not self._local_intent_tool_available(match.tool_name):
            if self.on_pipeline_event:
                self.on_pipeline_event(
                    "intent",
                    "local_unavailable",
                    {
                        "intent": match.intent,
                        "confidence": match.confidence,
                        "tool": match.tool_name,
                    },
                )
            return None

        if self.on_pipeline_event:
            self.on_pipeline_event(
                "intent",
                "local_matched",
                {
                    "intent": match.intent,
                    "confidence": match.confidence,
                    "tool": match.tool_name,
                },
            )

        reply = self._execute_local_intent(match)
        if self.on_assistant_text:
            self.on_assistant_text(reply)
        return reply

    def _local_intent_tool_available(self, tool_name: str) -> bool:
        if self.config.tools.enabled is not None and tool_name not in self.config.tools.enabled:
            return False
        return self.registry.get(tool_name) is not None

    def _execute_local_intent(self, match: LocalIntentMatch) -> str:
        if match.tool_name is None:
            return (match.reply or "").strip()

        result = self._run_tool(
            {
                "id": f"local_intent:{match.intent}",
                "type": "function",
                "function": {
                    "name": match.tool_name,
                    "arguments": dict(match.arguments),
                },
            }
        )
        # Use our smart generator to transform raw tool outputs to premium conversational responses
        return self._generate_conversational_reply(match.intent, match.arguments, result.strip())

    def _generate_conversational_reply(self, intent: str, arguments: dict[str, Any], result: str) -> str:
        # If the tool execution failed or returned custom guidance, return the raw result
        if result.startswith("Failed") or result.startswith("I cannot") or "failed" in result.lower():
            return result

        # Since our user is Indonesian, we default to Indonesian for a warm personal touch
        if intent == "system.set_volume":
            level = arguments.get("level", 50)
            return f"Siap, volume sekarang sudah diatur ke {level}%, Rafi! 🔉"
            
        elif intent == "system.get_volume":
            import re
            match = re.search(r"\d+", result)
            level = match.group(0) if match else "50"
            return f"Volume sistem saat ini berada di {level}%, Rafi. 🔊"
            
        elif intent == "system.set_muted":
            muted = arguments.get("muted", False)
            if muted:
                return "Suara sistem sudah dimatikan ya, Rafi. 🔕"
            return "Suara sistem sudah dinyalakan kembali, Rafi. 🔊"
                
        elif intent == "system.set_dark_mode":
            enabled = arguments.get("enabled", False)
            if enabled:
                return "Mode gelap sudah aktif, Rafi. 🌚"
            return "Mode terang sudah aktif, Rafi. ☀️"
                
        elif intent == "system.set_dnd":
            enabled = arguments.get("enabled", False)
            if enabled:
                return "Do Not Disturb sudah aktif. Kamu nggak bakal diganggu notifikasi dulu, Rafi. 😎🔕"
            return "Do Not Disturb sudah dimatikan, Rafi. Notifikasi siap masuk lagi! 😊"
                
        elif intent == "system.set_brightness":
            level = arguments.get("level", 50)
            return f"Siap, kecerahan layar sudah diatur ke {level}%, Rafi! ☀️"
            
        elif intent == "system.get_brightness":
            import re
            match = re.search(r"\d+", result)
            level = match.group(0) if match else "50"
            return f"Kecerahan layar saat ini berada di {level}%, Rafi. ☀️"

        return result

    def _run_tool(self, tool_call: dict[str, Any]) -> str:
        name = tool_call.get("function", {}).get("name", "")
        if self.on_pipeline_event:
            self.on_pipeline_event("tool", "started", {"name": name})
        try:
            result = self.registry.execute_call(tool_call)
        except Exception as exc:
            result = f"Tool '{name}' failed: {exc}"
        if self.on_pipeline_event:
            self.on_pipeline_event("tool", "completed", {"name": name, "result": result})
        if self.on_tool_executed:
            self.on_tool_executed(name, result)
        return result

    def _clean_markdown_for_tts(self, text: str) -> str:
        import re
        if not text:
            return ""
        
        # Process lines: remove list and numbering markers, ensure ending punctuation for natural pauses
        lines = []
        for line in text.splitlines():
            cleaned_line = line.strip()
            cleaned_line = re.sub(r'^[-*+]\s+', '', cleaned_line)
            cleaned_line = re.sub(r'^\d+\.\s+', '', cleaned_line)
            if cleaned_line:
                if not cleaned_line[-1] in ".!?,;:":
                    cleaned_line += "."
                lines.append(cleaned_line)
                
        text = " ".join(lines)
        
        # Strip markdown symbols
        text = re.sub(r'\*+', '', text)
        text = re.sub(r'_+', '', text)
        text = re.sub(r'`+', '', text)
        text = re.sub(r'#+\s+', '', text)
        
        # Strip double spaces and correct spaces before punctuation
        text = re.sub(r'\s+', ' ', text)
        text = re.sub(r'\s+([.!?,;:])', r'\1', text)
        
        return text.strip()

    async def _speak(self, text: str) -> None:
        import time
        start_tts = time.time()
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            pass

        self.state_machine.tts_ready()
        if self.on_pipeline_event:
            self.on_pipeline_event("tts", "started", {})

        stop_event = threading.Event()
        self._playback_stop_event = stop_event
        self._barge_in_requested = False
        self._barge_in_handled = False

        try:
            if text:
                clean_text = self._clean_markdown_for_tts(text)
                audio = await self.tts.synthesize(clean_text)
                if audio:
                    self._output_audio_bytes = audio
                    if self._play is not None:
                        await asyncio.to_thread(self._play_audio_blocking, audio, stop_event)
            interrupted = stop_event.is_set()
        finally:
            if self._playback_stop_event is stop_event:
                self._playback_stop_event = None

        if interrupted:
            self._finish_barge_in()
            return

        if self.on_pipeline_event:
            self.on_pipeline_event("tts", "completed", {})
        if self.state_machine.state is State.SPEAKING:
            self.state_machine.audio_done()

        tts_duration = time.time() - start_tts
        if self.debug_logger is not None and self._current_turn_id is not None:
            self._current_latency_metrics["tts_ms"] = int(tts_duration * 1000)

        if self.conversation_mode_active:
            self.start_auto_listening()

    def _play_audio_blocking(self, audio: bytes, stop_event: threading.Event) -> None:
        if self._play is None:
            return
        try:
            self._play(
                audio,
                on_audio_level=self.on_audio_level,
                stop_event=stop_event,
            )
        except TypeError:
            try:
                self._play(audio, on_audio_level=self.on_audio_level)
            except TypeError:
                self._play(audio)

    def request_barge_in(self) -> bool:
        if self.state_machine.state is not State.SPEAKING and self._playback_stop_event is None:
            return False

        self._barge_in_requested = True
        if self._playback_stop_event is not None:
            self._playback_stop_event.set()

        loop = self._loop
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(self._finish_barge_in)
        else:
            self._finish_barge_in()
        return True

    def _finish_barge_in(self) -> None:
        if self._barge_in_handled:
            return
        self._barge_in_handled = True

        if self.on_pipeline_event:
            self.on_pipeline_event("tts", "interrupted", {})

        if self.state_machine.state is State.SPEAKING:
            self.state_machine.audio_done()

        if self.state_machine.state is State.IDLE and self.recorder is not None:
            if self.conversation_mode_active:
                self.start_auto_listening()
            else:
                self.start_listening()

    def start_auto_listening(self) -> None:
        if self.recorder is None:
            return
        import time
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._auto_listening = True
        self._conversation_mode_active = True
        self._speech_detected = False
        self._last_speech_time = 0.0
        self._auto_listen_start_real_time = time.time()
        
        success = self.start_listening(is_auto=True)
        if not success:
            self._auto_listening = False
            self._conversation_mode_active = False
            return

        if self.config.vad.enabled and self.vad_manager.is_available:
            self.vad_manager.reset()
            self.vad_state_machine.reset()
            if self._loop is not None:
                print("Listening (conversation)...")
                self._vad_task = self._loop.create_task(self._run_vad_loop())

    def _handle_audio_level(self, level: float) -> None:
        if self.on_audio_level:
            self.on_audio_level(level)
        if self._auto_listening:
            if self.config.vad.enabled and self.vad_manager.is_available:
                pass
            else:
                self._check_auto_listening_status(level)

    def _check_auto_listening_status(self, level: float) -> None:
        import time
        now = time.time()

        if level > 0.03:
            if not self._speech_detected:
                self._speech_detected = True
            self._last_speech_time = now

        if self._speech_detected:
            if now - self._last_speech_time >= 1.5:
                self._auto_listening = False
                if self._loop:
                    asyncio.run_coroutine_threadsafe(self._auto_respond(), self._loop)
        else:
            if now - self._auto_listen_start_real_time >= 5.0:
                self._auto_listening = False
                if self._loop:
                    asyncio.run_coroutine_threadsafe(self._auto_timeout(), self._loop)

    async def _auto_respond(self) -> None:
        try:
            await self.stop_and_respond()
        except Exception as exc:
            self._report_auto_recoverable_error("auto_response_failed", exc)

    async def _auto_timeout(self, *, speech_detected: bool = False) -> None:
        try:
            if self.recorder and self.recorder.is_recording:
                self.recorder.stop_recording()
            self.state_machine.audio_done()
            # In continuous conversation mode a silent gap should not end the
            # session — re-arm and keep listening until the user toggles off.
            if self.conversation_mode_active:
                print("Listening again..." if speech_detected else "Still listening...")
                self.start_auto_listening()
        except Exception as exc:
            self._report_auto_recoverable_error("auto_timeout_failed", exc)

    def _cancel_vad_task(self) -> None:
        if self._vad_task is not None:
            try:
                current = asyncio.current_task()
            except RuntimeError:
                current = None
            if self._vad_task is not current:
                self._vad_task.cancel()
            self._vad_task = None

    async def _run_vad_loop(self) -> None:
        from verse.audio.vad import VADState, VAD_WINDOW_SAMPLES, VAD_FRAME_MS
        from collections import deque
        import time
        import numpy as np

        last_send_time = 0.0
        prev_state = VADState.WAITING_FOR_SPEECH
        # Rolling buffer so VAD always sees exactly-256-sample frames regardless
        # of the device block size (e.g. 48kHz mic resampled to 16kHz rarely
        # delivers exact 256-sample callbacks). Without this every frame would be
        # dropped and the turn never endpoints.
        sample_buffer = np.empty(0, dtype=np.float32)
        max_probability = 0.0
        max_rms_level = 0.0
        rms_fallback_active = False
        rms_fallback_armed = False
        rms_speech_ms = 0
        rms_silence_ms = 0
        rms_voiced_ms = 0
        rms_chunks: list[np.ndarray] = []
        rms_pre_roll: deque[np.ndarray] = deque(
            maxlen=max(1, self.config.vad.pre_roll_ms // VAD_FRAME_MS)
        )

        try:
            while self._auto_listening and self.recorder and self.recorder.is_recording:
                try:
                    chunk = await self.recorder.read_chunk()
                except RuntimeError:
                    break
                except asyncio.CancelledError:
                    break

                flat = np.asarray(chunk, dtype=np.float32).reshape(-1)
                if flat.size == 0:
                    continue
                sample_buffer = np.concatenate([sample_buffer, flat])

                terminal_state: VADState | None = None
                terminal_chunks: list[np.ndarray] | None = None

                while len(sample_buffer) >= VAD_WINDOW_SAMPLES:
                    frame = sample_buffer[:VAD_WINDOW_SAMPLES]
                    sample_buffer = sample_buffer[VAD_WINDOW_SAMPLES:]
                    rms_level = min(
                        1.0,
                        max(0.0, float(np.sqrt(np.mean(np.square(frame)))) * 5.0),
                    )
                    max_rms_level = max(max_rms_level, rms_level)

                    prob = self.vad_manager.predict(frame)
                    max_probability = max(max_probability, prob)
                    state, utterance_chunks = self.vad_state_machine.process_frame(frame, prob)

                    if self.debug_logger is not None and self._current_turn_id is not None:
                        self._current_vad_timeline.append({
                            "timestamp": time.time(),
                            "probability": float(prob),
                            "state": state.value,
                            "rms": float(rms_level)
                        })

                    if state != prev_state:
                        if state == VADState.SPEECH_ACTIVE and prev_state == VADState.WAITING_FOR_SPEECH:
                            print("Heard you, listening...")
                            rms_fallback_active = False
                            if self.on_pipeline_event:
                                self.on_pipeline_event("vad", "speech_started", {})
                        elif state == VADState.ENDED:
                            duration_ms = len(utterance_chunks or []) * VAD_FRAME_MS
                            stop_reason = "max_utterance" if duration_ms >= self.config.vad.max_utterance_ms else "silence"
                            if self.on_pipeline_event:
                                self.on_pipeline_event("vad", "speech_ended", {"stop_reason": stop_reason})
                        prev_state = state

                    now = time.time()
                    if now - last_send_time >= 0.12:
                        last_send_time = now
                        if self.on_vad_state:
                            self.on_vad_state(state.value, prob)
                        if self.on_pipeline_event:
                            self.on_pipeline_event(
                                "vad",
                                "debug",
                                {
                                    "state": state.value,
                                    "probability": prob,
                                    "rms_level": rms_level,
                                    "rms_fallback_active": rms_fallback_active,
                                    "elapsed_ms": self.vad_state_machine.elapsed_ms,
                                },
                            )

                    if state is VADState.ENDED:
                        terminal_state = state
                        terminal_chunks = utterance_chunks
                        break
                    elif state is VADState.TIMEOUT and not rms_fallback_active:
                        terminal_state = state
                        break

                    if (
                        self.config.vad.rms_fallback_enabled
                        and state is VADState.WAITING_FOR_SPEECH
                        and not rms_fallback_active
                    ):
                        rms_pre_roll.append(frame.copy())
                        if rms_level >= self.config.vad.rms_start_level:
                            rms_speech_ms += VAD_FRAME_MS
                        else:
                            rms_speech_ms = 0

                        if rms_speech_ms >= self.config.vad.speech_start_ms:
                            rms_fallback_active = True
                            rms_fallback_armed = True
                            rms_silence_ms = 0
                            rms_voiced_ms = rms_speech_ms
                            rms_chunks = list(rms_pre_roll)
                            print("Heard you, listening...")
                            if self.on_pipeline_event:
                                self.on_pipeline_event(
                                    "vad",
                                    "rms_speech_started",
                                    {"rms_level": rms_level, "probability": prob},
                                )
                    elif rms_fallback_active:
                        rms_chunks.append(frame.copy())
                        if rms_level < self.config.vad.rms_end_level:
                            rms_silence_ms += VAD_FRAME_MS
                        else:
                            rms_silence_ms = 0
                            rms_voiced_ms += VAD_FRAME_MS

                        rms_duration_ms = len(rms_chunks) * VAD_FRAME_MS
                        if (
                            rms_silence_ms >= self.config.vad.end_silence_ms
                            or rms_duration_ms >= self.config.vad.max_utterance_ms
                        ):
                            stop_reason = (
                                "max_utterance"
                                if rms_duration_ms >= self.config.vad.max_utterance_ms
                                else "silence"
                            )
                            if rms_voiced_ms >= self.config.vad.min_utterance_ms:
                                if self.on_pipeline_event:
                                    self.on_pipeline_event(
                                        "vad",
                                        "rms_speech_ended",
                                        {
                                            "stop_reason": stop_reason,
                                            "duration_ms": rms_duration_ms,
                                            "voiced_ms": rms_voiced_ms,
                                            "max_rms_level": max_rms_level,
                                            "max_probability": max_probability,
                                        },
                                    )
                                terminal_state = VADState.ENDED
                                terminal_chunks = list(rms_chunks)
                                break

                            if self.on_pipeline_event:
                                self.on_pipeline_event(
                                    "vad",
                                    "rms_speech_discarded",
                                    {
                                        "duration_ms": rms_duration_ms,
                                        "voiced_ms": rms_voiced_ms,
                                        "max_rms_level": max_rms_level,
                                        "max_probability": max_probability,
                                    },
                                )
                            rms_fallback_active = False
                            rms_speech_ms = 0
                            rms_silence_ms = 0
                            rms_voiced_ms = 0
                            rms_chunks = []
                            rms_pre_roll.clear()

                if terminal_state is VADState.ENDED:
                    self._auto_listening = False
                    self._cancel_vad_task()
                    print("Processing...")
                    await self._auto_respond_with_utterance(terminal_chunks)
                    break
                elif terminal_state is VADState.TIMEOUT:
                    self._auto_listening = False
                    self._cancel_vad_task()
                    if self.on_pipeline_event:
                        self.on_pipeline_event(
                            "vad",
                            "timeout",
                            {
                                "elapsed_ms": self.vad_state_machine.elapsed_ms,
                                "max_probability": max_probability,
                                "max_rms_level": max_rms_level,
                                "rms_fallback_armed": rms_fallback_armed,
                            },
                        )
                    logger.info(
                        "VAD timeout: elapsed_ms=%s max_probability=%.3f max_rms_level=%.3f rms_fallback_armed=%s",
                        self.vad_state_machine.elapsed_ms,
                        max_probability,
                        max_rms_level,
                        rms_fallback_armed,
                    )
                    await self._auto_timeout(speech_detected=rms_fallback_armed)
                    break
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self._report_auto_recoverable_error("vad_loop_failed", exc)

    async def _auto_respond_with_utterance(self, utterance_chunks: list[np.ndarray] | None) -> None:
        try:
            if self.recorder and self.recorder.is_recording:
                _ = self.recorder.stop_recording()

            import numpy as np
            if utterance_chunks:
                samples = np.concatenate(utterance_chunks, axis=0)
            else:
                samples = np.empty((0, 1), dtype=np.float32)

            from verse.audio.capture import samples_to_wav_bytes
            audio = samples_to_wav_bytes(samples, 16000)

            if _is_audio_too_short(audio):
                self.state_machine.audio_done()
                if self.conversation_mode_active:
                    self.start_auto_listening()
                return

            self.state_machine.hotkey_released()
            await self.handle_audio(audio)
        except Exception as exc:
            self._report_auto_recoverable_error("auto_utterance_failed", exc)

    def _report_auto_recoverable_error(self, code: str, exc: Exception) -> None:
        message = str(exc) or exc.__class__.__name__
        logger.exception("%s: %s", code, message)
        if self.state_machine.state is State.ERROR:
            return
        if self.on_pipeline_event:
            self.on_pipeline_event(
                "error",
                "recoverable_error",
                {"code": code, "message": message},
            )
        self.state_machine.fail(message)

        if self.debug_logger is not None and self._current_turn_id is not None:
            import traceback
            self.debug_logger.log_error(
                self._current_turn_id,
                error_type=f"auto_recoverable:{code}",
                message=message,
                traceback=traceback.format_exc(),
            )
            self._write_current_turn_data()

    def deactivate_conversation(self) -> None:
        self._conversation_mode_active = False
        self._auto_listening = False
        self._cancel_vad_task()
        if self.recorder and self.recorder.is_recording:
            try:
                self.recorder.stop_recording()
            except Exception:
                pass
        
        # Only force IDLE if we are actively listening (or in an error state).
        # If the backend is currently THINKING or SPEAKING, let the turn complete naturally
        # so that window blur (e.g. from launching a browser) does not abort the response.
        if self.state_machine.state in (State.LISTENING, State.ERROR):
            self.state_machine.force_idle()

    def _on_state_changed(self, event: StateChangedEvent) -> None:
        if event.state == State.IDLE:
            try:
                from verse.tools.builtin.browser import browser_close
                browser_close()
            except Exception as exc:
                logger.error(f"Failed to close browser on IDLE transition: {exc}")


def _is_audio_too_short(audio: bytes) -> bool:
    try:
        import io
        import soundfile as sf
        with sf.SoundFile(io.BytesIO(audio)) as f:
            duration = len(f) / f.samplerate
            return duration < 0.1
    except Exception:
        return True


def build_orchestrator(config: AppConfig | None = None, debug_logger: DebugSessionLogger | None = None) -> Orchestrator:
    from verse.audio.capture import AudioRecorder
    from verse.audio.playback import play_audio
    from verse.llm.deepseek import DeepSeekAdapter
    from verse.stt.groq import GroqWhisperAdapter
    from verse.tools.registry import build_default_registry
    from verse.tts.macos_say import MacOSSayAdapter
    from verse.tts.edge_tts import EdgeTTSAdapter
    from verse.tts.google import GoogleTTSAdapter

    config = config or AppConfig()
    registry = build_default_registry(config.tools.enabled)

    if config.tts.provider == "edge-tts":
        tts = EdgeTTSAdapter(config.tts)
    elif config.tts.provider == "google":
        tts = GoogleTTSAdapter(config.tts)
    else:
        tts = MacOSSayAdapter(config.tts)

    store = None
    if config.memory.enabled:
        try:
            # Shared singleton so the `remember` tool and the orchestrator read/write
            # the same store instance.
            from verse.persistence.db import default_store
            store = default_store()
        except Exception as exc:
            logger.error(f"Failed to init ConversationStore: {exc}")

    return Orchestrator(
        stt=GroqWhisperAdapter(),
        llm=DeepSeekAdapter(config.llm),
        tts=tts,
        registry=registry,
        state_machine=StateMachine(),
        config=config,
        recorder=AudioRecorder(),
        play=play_audio,
        debug_logger=debug_logger,
        store=store,
    )
