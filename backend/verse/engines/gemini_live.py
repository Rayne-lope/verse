from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

import numpy as np
import sounddevice as sd

from verse.config import AppConfig
from verse.orchestrator import DEFAULT_SYSTEM_PROMPT
from verse.state import State, StateMachine
from verse.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_AUDIO_MIME = "audio/pcm;rate=16000"
_MIC_SAMPLERATE = 16_000
_MIC_BLOCKSIZE = 512       # 32 ms @ 16 kHz
_RECONNECT_MAX = 30.0


class GeminiLiveEngine:
    """
    Drop-in Orchestrator replacement that streams audio to/from Gemini Live API.

    Exposes the same callback attributes (on_transcript, on_assistant_text,
    on_audio_level, on_pipeline_event, on_tool_executed, on_vad_state) and the
    same hotkey-drive methods (start_listening, stop_and_respond) as Orchestrator,
    so main.py wiring is unchanged.
    """

    # Callbacks — same attribute names as Orchestrator
    on_transcript: Callable[[str, bool], None] | None       # (text, partial)
    on_assistant_text: Callable[[str], None] | None
    on_audio_level: Callable[[float], None] | None
    on_pipeline_event: Callable[[str, str, dict[str, Any]], None] | None
    on_tool_executed: Callable[[str, str], None] | None
    on_vad_state: Callable[[str, float], None] | None       # unused; kept for compat

    def __init__(
        self,
        config: AppConfig,
        registry: ToolRegistry,
        state_machine: StateMachine,
    ) -> None:
        self._config = config
        self._registry = registry
        self._state_machine = state_machine

        self.on_transcript = None
        self.on_assistant_text = None
        self.on_audio_level = None
        self.on_pipeline_event = None
        self.on_tool_executed = None
        self.on_vad_state = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._session = None
        self._session_ready: asyncio.Event | None = None
        self._closed = False
        self._backoff = 1.0

        # Background tasks
        self._session_task: asyncio.Task | None = None

        # Mic capture
        self._mic_stream: sd.InputStream | None = None
        self._streaming = False
        self._audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=60)

        # Playback
        self._player = None

        # Per-turn state
        self._speaking_started = False
        self._input_transcript = ""
        self._output_transcript = ""

    @property
    def state_machine(self) -> StateMachine:
        return self._state_machine

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Initialise the engine. Validates the API key, creates the Gemini client,
        and starts the persistent reconnecting session loop.
        Raises RuntimeError immediately if the key is missing (triggers fallback).
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

    async def close(self) -> None:
        """Shut down gracefully."""
        self._closed = True
        self._streaming = False
        self._stop_mic()

        if self._session_task and not self._session_task.done():
            self._session_task.cancel()
            try:
                await self._session_task
            except asyncio.CancelledError:
                pass

        if self._player:
            self._player.close()

    # ------------------------------------------------------------------
    # Hotkey interface — matches Orchestrator
    # ------------------------------------------------------------------

    def start_listening(self) -> bool:
        """
        Open mic and start streaming audio to Gemini.
        Called from the hotkey-press handler (sync, main thread).
        """
        if not self._state_machine.is_idle:
            return False

        self._state_machine.hotkey_pressed()   # IDLE → LISTENING
        self._streaming = True
        self._speaking_started = False
        self._input_transcript = ""
        self._output_transcript = ""

        self._mic_stream = sd.InputStream(
            samplerate=_MIC_SAMPLERATE,
            channels=1,
            dtype="float32",
            blocksize=_MIC_BLOCKSIZE,
            callback=self._audio_cb,
        )
        self._mic_stream.start()

        if self._loop and not self._config.hotkey.conversation_mode:
            asyncio.run_coroutine_threadsafe(
                self._signal_activity_start(), self._loop
            )

        self._emit("gemini", "listening_start", {})
        return True

    async def stop_and_respond(self) -> None:
        """
        End the user's audio turn and wait for Gemini to respond.
        Called from the hotkey-release handler (async, event loop thread).
        """
        if not self._streaming:
            return

        self._streaming = False
        self._stop_mic()

        # Drain any remaining queue chunks before signalling end of turn
        await asyncio.sleep(0.12)

        if self._session and not self._config.hotkey.conversation_mode:
            try:
                from google.genai import types
                await self._session.send_realtime_input(
                    activity_end=types.ActivityEnd()
                )
            except Exception as exc:
                logger.warning("activity_end send failed: %s", exc)

        self._state_machine.hotkey_released()  # LISTENING → THINKING

    def request_barge_in(self) -> None:
        """Interrupt current assistant speech. Called from WS interrupt message."""
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._do_barge_in(), self._loop)

    async def _do_barge_in(self) -> None:
        if self._player:
            await self._player.clear()

        if self._state_machine.state is State.SPEAKING:
            self._state_machine.audio_done()   # SPEAKING → IDLE

        # Ask Gemini to stop its current output
        if self._session:
            try:
                from google.genai import types
                await self._session.send_realtime_input(
                    activity_start=types.ActivityStart()
                )
            except Exception as exc:
                logger.warning("barge-in activity_start failed: %s", exc)

        self._emit("gemini", "interrupted", {})
        self.start_listening()

    # ------------------------------------------------------------------
    # Persistent session loop (reconnects on error)
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
                    self._emit("gemini", "connected", {})
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
                logger.warning(
                    "Gemini Live error: %s — reconnecting in %.1fs", exc, self._backoff
                )
                self._emit("gemini", "reconnecting", {"message": str(exc)})
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, _RECONNECT_MAX)

        self._session = None
        if self._session_ready is not None:
            self._session_ready.clear()

    # ------------------------------------------------------------------
    # Audio send loop (runs concurrently with receive loop)
    # ------------------------------------------------------------------

    async def _send_loop(self, session) -> None:
        """Drain _audio_queue and forward PCM chunks to Gemini."""
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

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------

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
                                self._state_machine.tts_ready()   # THINKING → SPEAKING
                            except Exception:
                                pass
                            self._emit("gemini", "speaking_start", {})
                        if self._player:
                            await self._player.enqueue(inline.data)

                    text = getattr(part, "text", None)
                    if text and self.on_assistant_text:
                        self._output_transcript += text
                        self.on_assistant_text(self._output_transcript)

            # User speech transcript (streaming)
            in_tr = getattr(sc, "input_transcription", None)
            if in_tr is not None:
                delta = getattr(in_tr, "text", None) or ""
                if delta:
                    self._input_transcript += delta
                    if self.on_transcript:
                        self.on_transcript(self._input_transcript, True)

            # Output transcript (streamed text of what Gemini says)
            out_tr = getattr(sc, "output_transcription", None)
            if out_tr is not None:
                delta = getattr(out_tr, "text", None) or ""
                if delta and self.on_assistant_text:
                    self._output_transcript += delta
                    self.on_assistant_text(self._output_transcript)

            # Server-initiated barge-in
            if getattr(sc, "interrupted", False):
                self._emit("gemini", "interrupted", {})
                self._speaking_started = False
                if self._player:
                    await self._player.clear()

            # Turn complete — drain remaining audio, then go idle
            if getattr(sc, "turn_complete", False):
                # Send final transcript
                if self._input_transcript and self.on_transcript:
                    self.on_transcript(self._input_transcript, False)
                self._input_transcript = ""
                self._output_transcript = ""
                self._speaking_started = False
                self._emit("gemini", "turn_complete", {})
                if self._player:
                    self._player.signal_end()
                asyncio.create_task(self._finish_turn())

        # Tool calls
        tool_call = getattr(response, "tool_call", None)
        if tool_call is not None:
            await self._handle_tool_calls(tool_call, session)

    async def _finish_turn(self) -> None:
        """Wait for audio to drain, transition to IDLE, optionally auto-listen."""
        if self._player:
            await self._player.wait_drained()
        try:
            self._state_machine.audio_done()   # SPEAKING → IDLE
        except Exception:
            pass
        if self._config.hotkey.conversation_mode and not self._closed:
            self.start_listening()

    # ------------------------------------------------------------------
    # Tool calling
    # ------------------------------------------------------------------

    async def _handle_tool_calls(self, tool_call, session) -> None:
        from google.genai import types

        responses = []
        for fc in tool_call.function_calls:
            name = fc.name
            self._emit("tool", "started", {"name": name})
            try:
                result = self._registry.execute_call(
                    {"function": {"name": name, "arguments": fc.args}}
                )
            except Exception as exc:
                result = f"Tool '{name}' failed: {exc}"
            self._emit("tool", "completed", {"name": name, "result": result})
            if self.on_tool_executed:
                self.on_tool_executed(name, result)
            responses.append(
                types.FunctionResponse(id=fc.id, name=name, response={"output": result})
            )

        try:
            await session.send_tool_response(function_responses=responses)
        except Exception as exc:
            logger.warning("Tool response send failed: %s", exc)

    # ------------------------------------------------------------------
    # Audio capture (sounddevice callback — C audio thread)
    # ------------------------------------------------------------------

    def _audio_cb(
        self,
        indata: np.ndarray,
        frames: int,
        time_info,
        status: sd.CallbackFlags,
    ) -> None:
        if not self._streaming or self._loop is None:
            return

        pcm = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        level = min(1.0, float(np.sqrt(np.mean(indata ** 2))) * 5.0)

        if self.on_audio_level:
            self._loop.call_soon_threadsafe(
                lambda lvl=level: self.on_audio_level(lvl) if self.on_audio_level else None
            )
        self._loop.call_soon_threadsafe(self._try_enqueue, pcm)

    def _try_enqueue(self, pcm: bytes) -> None:
        """Safely enqueue from event-loop thread. Drops chunk if queue is full."""
        try:
            self._audio_queue.put_nowait(pcm)
        except asyncio.QueueFull:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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

    def _stop_mic(self) -> None:
        if self._mic_stream is not None:
            try:
                self._mic_stream.stop()
                self._mic_stream.close()
            except Exception:
                pass
            self._mic_stream = None

    def _on_playback_level(self, level: float) -> None:
        if self.on_audio_level:
            self.on_audio_level(level)

    def _emit(self, stage: str, event: str, meta: dict[str, Any]) -> None:
        if self.on_pipeline_event:
            self.on_pipeline_event(stage, event, meta)

    # ------------------------------------------------------------------
    # Config builders
    # ------------------------------------------------------------------

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

        # Transcription (may not exist in older SDK versions)
        try:
            config_kwargs["input_audio_transcription"] = types.AudioTranscriptionConfig()
            config_kwargs["output_audio_transcription"] = types.AudioTranscriptionConfig()
        except AttributeError:
            pass

        # Activity detection config (push-to-talk vs conversation mode)
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
        """Convert OpenAI-format ToolRegistry definitions to google.genai types."""
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
