from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Callable

from verse.config import AppConfig
from verse.engines.base import VoiceEngine, VoiceEvent
from verse.orchestrator import DEFAULT_SYSTEM_PROMPT
from verse.state import State, StateMachine
from verse.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_AUDIO_MIME = "audio/pcm;rate=16000"
_MIC_SAMPLERATE = 16_000
_RECONNECT_MAX = 30.0


class LiveRealtimeEngine(VoiceEngine):
    """
    Persistent speech-to-speech voice engine using Gemini Live WebSocket API.
    Audio is sent via send_audio(pcm), and events are streamed out via events().
    Uses native server-side VAD and streaming audio/text responses.
    """

    # Callbacks — same compatibility attribute names as Orchestrator
    on_transcript: Callable[[str, bool], None] | None = None
    on_assistant_text: Callable[[str], None] | None = None
    on_audio_level: Callable[[float], None] | None = None
    on_pipeline_event: Callable[[str, str, dict[str, Any]], None] | None = None
    on_tool_executed: Callable[[str, str], None] | None = None
    on_vad_state: Callable[[str, float], None] | None = None
    on_user_partial_transcript: Callable[[str, float | None], None] | None = None
    on_user_final_transcript: Callable[[str], None] | None = None

    def __init__(
        self,
        config: AppConfig,
        registry: ToolRegistry,
        state_machine: StateMachine,
    ) -> None:
        self._config = config
        self._registry = registry
        self._state_machine = state_machine

        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._session = None
        self._session_ready: asyncio.Event | None = None
        self._closed = False
        self._backoff = 1.0

        # Background tasks
        self._session_task: asyncio.Task | None = None
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=60)
        self._event_queue: asyncio.Queue[VoiceEvent] = asyncio.Queue(maxsize=256)

        # Playback (can be managed by caller or internally; we keep internal player for fast local playback)
        self._player = None

        # Per-turn state
        self._speaking_started = False
        self._input_transcript = ""
        self._output_transcript = ""

    @property
    def state_machine(self) -> StateMachine:
        return self._state_machine

    # ------------------------------------------------------------------
    # VoiceEngine Interface Compliance
    # ------------------------------------------------------------------

    async def start_session(self) -> None:
        """
        Connect to Gemini Live. Raises RuntimeError if API key is missing.
        """
        import keyring
        from google import genai
        from verse.audio.streaming_player import StreamingPlayer

        api_key = keyring.get_password("verse", "gemini_api_key")
        if not api_key:
            raise RuntimeError(
                "Gemini API key not set — run: keyring set verse gemini_api_key <key>"
            )

        self._loop = asyncio.get_running_loop()
        self._session_ready = asyncio.Event()
        self._client = genai.Client(
            api_key=api_key,
            http_options={"api_version": "v1alpha"},
        )
        self._player = StreamingPlayer(on_audio_level=self._on_playback_level)
        self._session_task = asyncio.create_task(self._session_loop())

    async def send_audio(self, pcm: bytes) -> None:
        """Stream microphone audio PCM chunks directly into the API send loop queue."""
        if self._closed:
            return
        try:
            self._audio_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            pass

    async def events(self) -> AsyncIterator[VoiceEvent]:
        """Stream standard VoiceEvents out to the caller runtime."""
        while True:
            yield await self._event_queue.get()

    def _clear_audio_queue(self) -> None:
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    async def cancel_response(self) -> None:
        """Send barge-in interrupt block to the Gemini Live session."""
        self._clear_audio_queue()
        if self._player:
            await self._player.clear()

        if self._state_machine.state in (State.PREPARING_AUDIO, State.SPEAKING):
            try:
                self._state_machine.audio_done()
            except Exception:
                pass

        if self._session:
            try:
                from google.genai import types
                await self._session.send_realtime_input(
                    activity_start=types.ActivityStart()
                )
            except Exception as exc:
                logger.warning("Barge-in activity_start failed: %s", exc)

        self._enqueue_event("interrupted", {})

    async def close(self) -> None:
        """Close connections and tasks gracefully."""
        self._closed = True
        self._clear_audio_queue()
        if self._session_task and not self._session_task.done():
            self._session_task.cancel()
            try:
                await self._session_task
            except asyncio.CancelledError:
                pass

        if self._player:
            try:
                self._player.close()
            except Exception:
                pass
            self._player = None

    # ------------------------------------------------------------------
    # Compatibility Methods for main.py integration
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the persistent Live connection."""
        await self.start_session()

    def start_listening(self) -> bool:
        """
        Open session audio capture state.
        Called from the hotkey-press handler (sync, main thread).
        """
        if not self._state_machine.is_idle:
            return False

        self._clear_audio_queue()
        self._state_machine.hotkey_pressed()   # IDLE → LISTENING
        self._speaking_started = False
        self._input_transcript = ""
        self._output_transcript = ""

        # Trigger session start activity block
        if self._loop:
            asyncio.run_coroutine_threadsafe(
                self._signal_activity_start(), self._loop
            )

        self._enqueue_event("pipeline_event", {"stage": "gemini", "event": "listening_start", "metadata": {}})
        return True

    async def stop_and_respond(self, *, history: list[dict[str, Any]] | None = None) -> str:
        """
        End the user's turn.
        Called from the hotkey-release handler (async, event loop thread).
        """
        if self._session:
            try:
                from google.genai import types
                await self._session.send_realtime_input(
                    activity_end=types.ActivityEnd()
                )
            except Exception as exc:
                logger.warning("activity_end send failed: %s", exc)

        self._state_machine.hotkey_released()  # LISTENING → THINKING
        return ""

    def request_barge_in(self) -> None:
        """Interrupt active speak responses."""
        if self._loop:
            asyncio.run_coroutine_threadsafe(self.cancel_response(), self._loop)

    def start_auto_listening(self) -> None:
        """Enable conversation mode."""
        self.start_listening()

    def deactivate_conversation(self) -> None:
        """Disable conversation mode."""
        pass

    # ------------------------------------------------------------------
    # Persistent Session Loops
    # ------------------------------------------------------------------

    async def _session_loop(self) -> None:
        while not self._closed:
            try:
                config = self._make_live_config()
                async with self._client.aio.live.connect(
                    model=self._config.voice.gemini_live.model,
                    config=config,
                ) as session:
                    self._session = session
                    if self._session_ready is not None:
                        self._session_ready.set()
                    self._backoff = 1.0
                    self._enqueue_event("pipeline_event", {"stage": "gemini", "event": "connected", "metadata": {}})
                    logger.info("Gemini Live connected")

                    send_task = asyncio.create_task(self._send_loop(session))
                    try:
                        await self._receive_loop(session)
                    finally:
                        send_task.cancel()
                        try:
                            await send_task
                        except asyncio.CancelledError:
                            pass

            except asyncio.CancelledError:
                break
            except Exception as exc:
                if self._closed:
                    break
                self._session = None
                if self._session_ready is not None:
                    self._session_ready.clear()
                self._clear_audio_queue()
                logger.warning(
                    "Gemini Live error: %s — reconnecting in %.1fs", exc, self._backoff
                )
                self._enqueue_event("error", {"message": f"Gemini Live error: {exc}", "recoverable": True})
                self._enqueue_event("pipeline_event", {"stage": "gemini", "event": "reconnecting", "metadata": {"message": str(exc)}})
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _RECONNECT_MAX)

        self._session = None
        if self._session_ready is not None:
            self._session_ready.clear()

    async def _send_loop(self, session) -> None:
        """Forward PCM chunks to the Live API WebSocket."""
        while True:
            try:
                pcm = await asyncio.wait_for(self._audio_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                from google.genai import types
                await session.send_realtime_input(
                    audio=types.Blob(data=pcm, mime_type=_AUDIO_MIME)
                )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Audio chunk send failed: %s", exc)

    async def _receive_loop(self, session) -> None:
        async for response in session.receive():
            if self._closed:
                break
            await self._process_response(response, session)

    async def _process_response(self, response, session) -> None:
        sc = getattr(response, "server_content", None)
        if sc is not None:
            # Audio / text parts from the model
            model_turn = getattr(sc, "model_turn", None)
            if model_turn is not None:
                for part in model_turn.parts or []:
                    inline = getattr(part, "inline_data", None)
                    if inline is not None and inline.data:
                        if not self._speaking_started:
                            self._speaking_started = True
                            try:
                                self._state_machine.tts_ready()
                                self._state_machine.playback_started()
                            except Exception:
                                pass
                            self._enqueue_event("pipeline_event", {"stage": "gemini", "event": "speaking_start", "metadata": {}})
                        
                        # Local audio playback
                        if self._player:
                            await self._player.enqueue(inline.data)
                        
                        # Output audio voice event
                        self._enqueue_event("audio", {"pcm": inline.data})

                    text = getattr(part, "text", None)
                    if text:
                        self._output_transcript += text
                        self._enqueue_event("assistant_text", {"text": self._output_transcript})

            # User speech transcript (streaming)
            in_tr = getattr(sc, "input_transcription", None)
            if in_tr is not None:
                delta = getattr(in_tr, "text", None) or ""
                if delta:
                    self._input_transcript += delta
                    self._enqueue_event("transcript", {"text": self._input_transcript, "partial": True})

            # Output transcript (streamed text of what Gemini says)
            out_tr = getattr(sc, "output_transcription", None)
            if out_tr is not None:
                delta = getattr(out_tr, "text", None) or ""
                if delta:
                    self._output_transcript += delta
                    self._enqueue_event("assistant_text", {"text": self._output_transcript})

            # Server-initiated barge-in
            if getattr(sc, "interrupted", False):
                self._enqueue_event("interrupted", {})
                self._speaking_started = False
                if self._player:
                    await self._player.clear()

            # Turn complete — drain remaining audio, then go idle
            if getattr(sc, "turn_complete", False):
                # Send final transcript
                if self._input_transcript:
                    self._enqueue_event("transcript", {"text": self._input_transcript, "partial": False})
                self._input_transcript = ""
                self._output_transcript = ""
                self._speaking_started = False
                self._enqueue_event("turn_complete", {})
                if self._player:
                    self._player.signal_end()
                asyncio.create_task(self._finish_turn())

        # Tool calls
        tool_call = getattr(response, "tool_call", None)
        if tool_call is not None:
            await self._handle_tool_calls(tool_call, session)

    async def _finish_turn(self) -> None:
        if self._player:
            await self._player.wait_drained()
        try:
            self._state_machine.audio_done()
        except Exception:
            pass
        self._enqueue_event("pipeline_event", {"stage": "gemini", "event": "turn_complete", "metadata": {}})

    async def _handle_tool_calls(self, tool_call, session) -> None:
        from google.genai import types

        responses = []
        for fc in tool_call.function_calls:
            name = fc.name
            self._enqueue_event("pipeline_event", {"stage": "tool", "event": "started", "metadata": {"name": name}})
            try:
                result = self._registry.execute_call(
                    {"function": {"name": name, "arguments": fc.args}}
                )
            except Exception as exc:
                result = f"Tool '{name}' failed: {exc}"
            
            self._enqueue_event("pipeline_event", {"stage": "tool", "event": "completed", "metadata": {"name": name, "result": result}})
            self._enqueue_event("tool_call", {"name": name, "result": result})
            
            responses.append(
                types.FunctionResponse(id=fc.id, name=name, response={"output": result})
            )

        try:
            await session.send_tool_response(function_responses=responses)
        except Exception as exc:
            logger.warning("Tool response send failed: %s", exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _dispatch_callback(self, cb: Callable[..., None] | None, *args: Any) -> None:
        if cb is None:
            return
        try:
            in_loop_thread = (asyncio.get_running_loop() is self._loop)
        except RuntimeError:
            in_loop_thread = False

        if in_loop_thread:
            cb(*args)
        elif self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(cb, *args)
        else:
            cb(*args)

    def _enqueue_event(self, type_: str, payload: dict[str, Any]) -> None:
        if self._event_queue.full():
            if type_ in ("audio_level", "vad_state"):
                return  # Drop transient high-frequency events immediately

            # Try to make room by removing the oldest transient event from the queue
            removed = False
            for event_item in list(self._event_queue._queue):
                if event_item.type in ("audio_level", "vad_state"):
                    self._event_queue._queue.remove(event_item)
                    removed = True
                    break
            
            if not removed:
                # If no transient event can be dropped, we must drop this event to avoid QueueFull crash
                logger.error("Event queue completely full of critical events! Dropping: %s", type_)
                return

        event = VoiceEvent(type=type_, payload=payload)
        
        # Fire standard callbacks concurrently
        if type_ == "transcript":
            self._dispatch_callback(self.on_transcript, payload["text"], payload.get("partial", False))
            if payload.get("partial", False):
                self._dispatch_callback(self.on_user_partial_transcript, payload["text"], None)
            else:
                self._dispatch_callback(self.on_user_final_transcript, payload["text"])
        elif type_ == "assistant_text":
            self._dispatch_callback(self.on_assistant_text, payload["text"])
        elif type_ == "audio_level":
            self._dispatch_callback(self.on_audio_level, payload["level"])
        elif type_ == "tool_call":
            self._dispatch_callback(self.on_tool_executed, payload["name"], payload["result"])
        elif type_ == "pipeline_event":
            self._dispatch_callback(self.on_pipeline_event, payload["stage"], payload["event"], payload["metadata"])
        elif type_ == "vad_state":
            self._dispatch_callback(self.on_vad_state, payload["state"], payload["probability"])

        try:
            in_loop_thread = (asyncio.get_running_loop() is self._loop)
        except RuntimeError:
            in_loop_thread = False

        if in_loop_thread:
            self._event_queue.put_nowait(event)
        elif self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._event_queue.put_nowait, event)
        else:
            self._event_queue.put_nowait(event)

    def _on_playback_level(self, level: float) -> None:
        self._enqueue_event("audio_level", {"level": level})

    async def _signal_activity_start(self) -> None:
        if self._session_ready is not None:
            try:
                await asyncio.wait_for(self._session_ready.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                return
        if self._session:
            try:
                from google.genai import types
                await self._session.send_realtime_input(
                    activity_start=types.ActivityStart()
                )
            except Exception as exc:
                logger.warning("activity_start failed: %s", exc)

    def _make_live_config(self):
        from google.genai import types

        gl = self._config.voice.gemini_live
        conversation_mode = self._config.hotkey.conversation_mode
        tools = self._convert_tools()

        config_kwargs: dict[str, Any] = {
            "response_modalities": ["AUDIO", "TEXT"],
            "speech_config": types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=gl.voice_name
                    )
                )
            ),
            "system_instruction": types.Content(
                parts=[types.Part(text=DEFAULT_SYSTEM_PROMPT)]
            ),
        }

        if tools:
            config_kwargs["tools"] = tools

        try:
            config_kwargs["input_audio_transcription"] = types.AudioTranscriptionConfig()
            config_kwargs["output_audio_transcription"] = types.AudioTranscriptionConfig()
        except AttributeError:
            pass

        try:
            config_kwargs["realtime_input_config"] = types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    disabled=not conversation_mode
                )
            )
        except (AttributeError, TypeError):
            pass

        return types.LiveConnectConfig(**config_kwargs)

    def _convert_tools(self) -> list:
        from google.genai import types

        definitions = self._registry.list_definitions(self._config.tools.enabled)
        if not definitions:
            return []

        decls = []
        for defn in definitions:
            fn = defn.get("function", {})
            params = fn.get("parameters", {})
            decls.append(
                types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters=_schema_to_gemini(params),
                )
            )

        return [types.Tool(function_declarations=decls)]


# ------------------------------------------------------------------
# JSON Schema → google.genai Schema converter
# ------------------------------------------------------------------

def _schema_to_gemini(schema: dict) -> "types.Schema":
    from google.genai import types

    _TYPE = {
        "string": types.Type.STRING,
        "number": types.Type.NUMBER,
        "integer": types.Type.INTEGER,
        "boolean": types.Type.BOOLEAN,
        "object": types.Type.OBJECT,
        "array": types.Type.ARRAY,
    }
    gemini_type = _TYPE.get(schema.get("type", "string"), types.Type.STRING)

    props = {
        k: _schema_to_gemini(v)
        for k, v in schema.get("properties", {}).items()
    }

    items = _schema_to_gemini(schema["items"]) if "items" in schema else None

    return types.Schema(
        type=gemini_type,
        description=schema.get("description"),
        properties=props or None,
        required=schema.get("required"),
        items=items,
    )
