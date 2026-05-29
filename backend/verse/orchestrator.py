from __future__ import annotations

import asyncio
from typing import Any, Callable

from verse.config import AppConfig
from verse.llm.base import LLMAdapter
from verse.state import StateMachine
from verse.stt.base import STTAdapter
from verse.tools.registry import ToolRegistry
from verse.tts.base import TTSAdapter

DEFAULT_SYSTEM_PROMPT = (
    "You are Verse, a concise voice assistant for macOS. "
    "Reply in the same language the user speaks. "
    "Keep answers short and natural since they will be spoken aloud. "
    "Use the available tools to control music, open apps, search the web, "
    "or check the time when the user asks for those actions."
)

PlaybackFn = Callable[[bytes], None]


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

        self._auto_listening = False
        self._speech_detected = False
        self._last_speech_time = 0.0
        self._auto_listen_start_real_time = 0.0
        self._loop = None


    def start_listening(self, is_auto: bool = False) -> bool:
        if self.recorder is None:
            raise RuntimeError("Orchestrator has no recorder configured")
        # Ignore presses while busy or during the error-reset window.
        if self.recorder.is_recording or not self.state_machine.is_idle:
            return False
        if not is_auto:
            self._auto_listening = False
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
        audio = self.recorder.stop_recording()
        self.state_machine.hotkey_released()
        return await self.handle_audio(audio, history=history)

    async def handle_audio(
        self, audio: bytes, *, history: list[dict[str, Any]] | None = None
    ) -> str:
        import time

        try:
            start_stt = time.time()
            transcript = await self._transcribe(audio)
            print(f"[Debug] STT took: {time.time() - start_stt:.2f}s")

            start_llm = time.time()
            reply = await self._respond(transcript, history or [])
            print(f"[Debug] LLM took: {time.time() - start_llm:.2f}s")

            start_tts = time.time()
            await self._speak(reply)
            print(f"[Debug] TTS took: {time.time() - start_tts:.2f}s")

            return reply
        except Exception as exc:  # surface failure to UI/state machine
            self.state_machine.fail(str(exc))
            raise

    async def _transcribe(self, audio: bytes) -> str:
        language = self.config.stt.language
        transcript = await self.stt.transcribe(audio, language=language)
        transcript = transcript.strip()
        if self.on_transcript:
            self.on_transcript(transcript)
        return transcript

    async def _respond(self, transcript: str, history: list[dict[str, Any]]) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            *history,
            {"role": "user", "content": transcript},
        ]
        definitions = self.registry.list_definitions(self.config.tools.enabled)
        tools = definitions or None

        reply = ""
        for _ in range(self.max_tool_iterations):
            response = await self.llm.chat(messages, tools=tools)
            if not response.tool_calls:
                reply = response.text.strip()
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response.text or None,
                    "tool_calls": response.tool_calls,
                }
            )
            for tool_call in response.tool_calls:
                result = self._run_tool(tool_call)
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

        if self.on_assistant_text:
            self.on_assistant_text(reply)
        return reply

    def _run_tool(self, tool_call: dict[str, Any]) -> str:
        name = tool_call.get("function", {}).get("name", "")
        try:
            result = self.registry.execute_call(tool_call)
        except Exception as exc:
            result = f"Tool '{name}' failed: {exc}"
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
        self.state_machine.tts_ready()
        if text:
            clean_text = self._clean_markdown_for_tts(text)
            audio = await self.tts.synthesize(clean_text)
            if audio and self._play is not None:
                try:
                    self._play(audio, on_audio_level=self.on_audio_level)
                except TypeError:
                    self._play(audio)
        self.state_machine.audio_done()
        if self.config.hotkey.conversation_mode:
            self.start_auto_listening()

    def start_auto_listening(self) -> None:
        if self.recorder is None:
            return
        import time
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
        self._auto_listening = True
        self._speech_detected = False
        self._last_speech_time = 0.0
        self._auto_listen_start_real_time = time.time()
        
        success = self.start_listening(is_auto=True)
        if not success:
            self._auto_listening = False

    def _handle_audio_level(self, level: float) -> None:
        if self.on_audio_level:
            self.on_audio_level(level)
        if self._auto_listening:
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
        except Exception:
            pass

    async def _auto_timeout(self) -> None:
        try:
            if self.recorder and self.recorder.is_recording:
                self.recorder.stop_recording()
            self.state_machine.audio_done()
        except Exception:
            pass


def build_orchestrator(config: AppConfig | None = None) -> Orchestrator:
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

    return Orchestrator(
        stt=GroqWhisperAdapter(),
        llm=DeepSeekAdapter(config.llm),
        tts=tts,
        registry=registry,
        state_machine=StateMachine(),
        config=config,
        recorder=AudioRecorder(),
        play=lambda audio: play_audio(audio),
    )
