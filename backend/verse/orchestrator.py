from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any, Callable, AsyncIterator

from verse.config import AppConfig
from verse.intent import LocalIntentMatch, LocalIntentRouter, IntentCategory, fast_intent_classifier, TurnContext
from verse.tts import TextSegmenter
from verse.tools import ToolSelector
from verse.audio.streaming_player import StreamingPlayer
from verse.latency import LatencyTracker
from verse.llm.base import LLMAdapter, LLMStreamEvent
from verse.state import State, StateMachine, StateChangedEvent
from verse.stt.base import STTAdapter, STTEvent
from verse.tools.registry import ToolRegistry
from verse.tts.base import TTSAdapter, RealtimeTTSAdapter
from verse.persistence.debug_logger import DebugSessionLogger

DEFAULT_SYSTEM_PROMPT = (
    "You are Verse, a concise voice assistant for macOS. "
    "Reply in the same language the user speaks. "
    "Keep answers short and natural since they will be spoken aloud. "
    "Use the available tools to control music, open apps, search the web, "
    "or check the time when the user asks for those actions. "
    "Available tools are authoritative: if a tool exists, you can use it. "
    "When the user asks to browse, open a web page, read a page, search in a browser, click/type/fill forms/scroll, or summarize web content, "
    "you MUST use browser tools instead of claiming you cannot browse or read web pages. "
    "Use browser_status when you need to diagnose the active browser page or last browser action. "
    "For natural browser clicks or form filling, prefer browser_click_best_match, browser_click_text, browser_click_role, and browser_fill_form. "
    "Tool results are authoritative: report failed, ambiguous, login_required, blocked, or not_found browser results plainly. "
    "Never claim a browser click, fill, submit, or send succeeded unless the browser tool result says it succeeded. "
    "When the user asks to use WhatsApp in Brave or a browser, use WhatsApp Web/browser tools, not iMessage. "
    "Never say a WhatsApp message was sent unless whatsapp_send_message completed successfully in the current flow. "
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


BROWSER_TURN_DIRECTIVE = (
    "Browser turn directive: Verse has Playwright browser tools. For this user request, "
    "call browser_navigate, browser_read_current, browser_status, browser_inspect, browser_click, "
    "browser_click_text, browser_click_role, browser_click_best_match, browser_input, "
    "browser_fill_form, browser_scroll, or browser_go_back before giving the final answer. "
    "For natural click/fill requests, prefer intent/form tools over raw CSS selectors. "
    "Failed or ambiguous tool output must be reported plainly, not converted into success. "
    "Do not say you cannot browse, read pages, click, type, fill forms, or summarize web content."
)

WHATSAPP_TURN_DIRECTIVE = (
    "WhatsApp Web directive: use whatsapp_open, whatsapp_find_chat, "
    "whatsapp_draft_message, or whatsapp_send_message for WhatsApp in Brave/browser. "
    "These tools operate WhatsApp Web in the active Playwright browser, not iMessage. "
    "Only send when the user explicitly asks to send/reply and both recipient and text "
    "are known. If a tool fails or login is required, say that plainly."
)

BROWSER_RETRY_DIRECTIVE = (
    "The previous assistant response incorrectly refused browser capability. "
    "Retry the original user request now. You have browser tools available and must call "
    "one before answering."
)


def _is_test_artifact_message(content: str) -> bool:
    return content.strip() == "Mocked LLM reply"


def _looks_like_browser_refusal(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", text.lower()).strip()
    if not normalized:
        return False

    refusal_markers = (
        "tidak punya kemampuan",
        "tidak bisa",
        "nggak bisa",
        "gak bisa",
        "ga bisa",
        "tidak dapat",
        "hanya bisa",
        "cuma bisa",
        "cannot",
        "can't",
        "unable to",
        "not able to",
    )
    browser_terms = (
        "browser",
        "brave",
        "web",
        "website",
        "internet",
        "halaman",
        "artikel",
        "tautan",
        "link",
        "membuka",
        "buka",
        "menavigasi",
        "navigasi",
        "membaca",
        "baca",
        "merangkum",
        "rangkum",
        "klik",
        "click",
        "ketik",
        "type",
        "browse",
        "read",
        "summarize",
    )
    return any(marker in normalized for marker in refusal_markers) and any(
        term in normalized for term in browser_terms
    )


def _normalize_turn_text(text: str) -> str:
    normalized = text.lower().replace("web.whatsapp.com", "web whatsapp com")
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _looks_like_whatsapp_web_turn(text: str) -> bool:
    normalized = _normalize_turn_text(text)
    return any(
        marker in normalized
        for marker in ("whatsapp", "whats app", "web whatsapp", "web whatsapp com")
    )


def _looks_like_browser_hosted_app_text(text: str) -> bool:
    normalized = _normalize_turn_text(text)
    if _looks_like_whatsapp_web_turn(normalized):
        return True
    browser_surface_terms = (
        "di brave", "lewat brave", "pakai brave", "dengan brave",
        "di browser", "lewat browser", "pakai browser", "di chrome", "di safari",
    )
    action_terms = (
        "buka", "open", "buat", "balasan", "balas", "reply", "kirim", "send",
        "pesan", "message", "chat", "ketik", "type", "klik", "click", "navigasi",
    )
    return any(term in normalized for term in browser_surface_terms) and any(
        term in normalized for term in action_terms
    )


def _looks_like_whatsapp_send_claim(text: str) -> bool:
    normalized = _normalize_turn_text(text)
    if not normalized:
        return False
    send_claims = (
        "aku kirim", "saya kirim", "kirim sekarang", "aku sudah kirim",
        "saya sudah kirim", "sudah aku kirim", "sudah saya kirim", "terkirim",
        "sent", "message sent", "pesan terkirim",
    )
    send_terms = ("whatsapp", "pesan", "message", "chat")
    return any(claim in normalized for claim in send_claims) and any(
        term in normalized for term in send_terms
    )


def _clean_whatsapp_fragment(value: str) -> str:
    value = re.sub(r"[^\w\s.'-]", " ", value, flags=re.UNICODE)
    value = re.sub(
        r"\b(?:di|lewat|via|pakai|dengan)\s+(?:web\s+)?whatsapp\b.*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:di|lewat|via|pakai|dengan)\s+(?:brave|browser|chrome|safari)\b.*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"\b(?:aku|saya|dong|ya|nih|tolong)\b", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip(" .'-")


def _clean_whatsapp_message_fragment(value: str) -> str:
    value = re.sub(r"[^\w\s.'!?,-]", " ", value, flags=re.UNICODE)
    value = re.sub(
        r"\b(?:di|lewat|via|pakai|dengan)\s+(?:web\s+)?whatsapp\b.*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"\b(?:di|lewat|via|pakai|dengan)\s+(?:brave|browser|chrome|safari)\b.*$",
        " ",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", value).strip(" .'-")


def _extract_whatsapp_contact(transcript: str) -> str:
    text = re.sub(r"\s+", " ", transcript).strip()
    patterns = (
        r"(?:balasan|balas|bales|reply)\s+(?:ke|kepada|untuk)?\s*(?P<contact>.+?)(?:\s+(?:di|lewat|via|pakai)\s+(?:web\s+)?whatsapp|\s+(?:bilang|katakan|berisi|dengan|isi|pesan(?:nya)?|text|teks)\b|$)",
        r"(?:whatsapp|pesan|message|chat)\s+(?:ke|kepada|untuk)\s+(?P<contact>.+?)(?:\s+(?:di|lewat|via|pakai)\s+(?:web\s+)?whatsapp|\s+(?:di|lewat|via|pakai)\s+(?:brave|browser|chrome|safari)|\s+(?:bilang|katakan|berisi|dengan|isi|pesan(?:nya)?|text|teks)\b|$)",
        r"(?:ke|kepada|untuk)\s+(?P<contact>.+?)(?:\s+(?:di|lewat|via|pakai)\s+(?:web\s+)?whatsapp|\s+(?:bilang|katakan|berisi|dengan|isi|pesan(?:nya)?|text|teks)\b|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            contact = _clean_whatsapp_fragment(match.group("contact"))
            if contact:
                return contact
    return ""


def _extract_whatsapp_message_text(transcript: str) -> str:
    text = re.sub(r"\s+", " ", transcript).strip()
    patterns = (
        r"(?:bilang|katakan)\s+(?P<text>.+)$",
        r"(?:berisi|isinya|isi pesan(?:nya)?|pesan(?:nya)?|text(?:nya)?|teks(?:nya)?|dengan(?: pesan)?)\s+(?P<text>.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            message = _clean_whatsapp_message_fragment(match.group("text"))
            if message:
                return message
    return ""


def _has_whatsapp_send_intent(transcript: str) -> bool:
    normalized = _normalize_turn_text(transcript)
    return any(k in normalized for k in ("kirim", "send", "balas", "bales", "reply", "balasan"))


def _is_whatsapp_open_request(transcript: str) -> bool:
    normalized = _normalize_turn_text(transcript)
    return _looks_like_whatsapp_web_turn(normalized) and any(k in normalized for k in ("buka", "open", "launch"))


def _is_whatsapp_status_query(transcript: str) -> bool:
    normalized = _normalize_turn_text(transcript)
    return any(
        marker in normalized
        for marker in (
            "mana", "gak kekirim", "ga kekirim", "nggak kekirim", "belum kekirim",
            "kok belum", "sudah terkirim", "udah terkirim", "terkirim belum",
        )
    )


def _whatsapp_send_succeeded(result: str) -> bool:
    return result.strip().lower().startswith("sent whatsapp message")


def _sanitize_history_for_context(
    history: list[dict[str, Any]],
    category: IntentCategory,
    transcript: str = "",
) -> list[dict[str, Any]]:
    context_is_browserish = category == IntentCategory.BROWSER or _looks_like_browser_hosted_app_text(transcript)
    cleaned: list[dict[str, Any]] = []
    for message in history:
        content = message.get("content")
        if isinstance(content, str) and _is_test_artifact_message(content):
            continue
        if (
            context_is_browserish
            and message.get("role") == "assistant"
            and isinstance(content, str)
            and _looks_like_browser_refusal(content)
        ):
            continue
        if (
            context_is_browserish
            and message.get("role") == "assistant"
            and isinstance(content, str)
            and _looks_like_whatsapp_send_claim(content)
        ):
            continue
        cleaned.append(message)
    return cleaned


def _browser_retry_message(transcript: str) -> dict[str, str]:
    return {
        "role": "user",
        "content": f"{BROWSER_RETRY_DIRECTIVE}\n\nOriginal user request: {transcript}",
    }


def _synthesize_browser_tool_call(
    transcript: str,
    messages: list[dict[str, Any]] | None = None,
    available_tools: list[str] | None = None,
) -> dict[str, Any]:
    import urllib.parse

    available = set(available_tools or [])
    if _looks_like_whatsapp_web_turn(transcript):
        if not available or "whatsapp_open" in available:
            return _make_synthetic_tool_call("whatsapp_open", {})
        return _make_synthetic_tool_call("browser_navigate", {"url": "https://web.whatsapp.com/"})

    url_match = re.search(
        r"(https?://[^\s]+|www\.[^\s]+|[\w.-]+\.(?:com|org|net|id|edu|gov|io)(?:/[^\s]*)?)",
        transcript,
        flags=re.IGNORECASE,
    )
    if url_match:
        url = url_match.group(1).rstrip(".,;:)")
        return _make_synthetic_tool_call("browser_navigate", {"url": url})

    topic = _extract_browser_topic(transcript)
    lower = transcript.lower()
    context_lower = " ".join(
        str(message.get("content", ""))
        for message in (messages or [])
        if message.get("role") == "user"
    ).lower()
    wants_wikipedia = "wikipedia" in lower or "wiki" in lower or (
        topic and ("wikipedia" in context_lower or "wiki" in context_lower)
    )
    if wants_wikipedia:
        if topic:
            slug = urllib.parse.quote(topic.title().replace(" ", "_"))
            return _make_synthetic_tool_call(
                "browser_navigate",
                {"url": f"https://id.wikipedia.org/wiki/{slug}"},
            )
        return _make_synthetic_tool_call("browser_read_current", {})

    if topic:
        query = urllib.parse.quote(topic)
    else:
        query = urllib.parse.quote(transcript.strip())
    if query:
        return _make_synthetic_tool_call(
            "browser_navigate",
            {"url": f"https://www.google.com/search?q={query}"},
        )
    return _make_synthetic_tool_call("browser_read_current", {})


def _make_synthetic_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"browser_recovery:{name}",
        "type": "function",
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        },
    }


def _tool_names_from_definitions(tools: list[dict[str, Any]] | None) -> list[str]:
    if not tools:
        return []
    names: list[str] = []
    for tool in tools:
        name = tool.get("function", {}).get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def _should_suppress_pre_tool_speech(
    transcript: str,
    category: IntentCategory,
    tools: list[dict[str, Any]] | None,
) -> bool:
    tool_names = _tool_names_from_definitions(tools)
    if not tool_names:
        return False
    has_action_tools = any(
        name.startswith("browser_") or name.startswith("whatsapp_")
        for name in tool_names
    )
    return has_action_tools and (
        category == IntentCategory.BROWSER
        or _looks_like_browser_hosted_app_text(transcript)
    )


BROWSER_ACTION_TOOL_NAMES = {
    "browser_click",
    "browser_input",
    "browser_click_text",
    "browser_click_role",
    "browser_click_best_match",
    "browser_fill_form",
    "whatsapp_find_chat",
    "whatsapp_draft_message",
    "whatsapp_send_message",
}


def _parse_tool_call_arguments(tool_call: dict[str, Any]) -> dict[str, Any]:
    raw = tool_call.get("function", {}).get("arguments")
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _truthy_argument(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return bool(value)


def _has_explicit_browser_submit_intent(transcript: str) -> bool:
    normalized = _normalize_turn_text(transcript)
    return any(
        marker in normalized
        for marker in (
            "submit", "send form", "kirim form", "kirim", "login",
            "masuk", "continue", "lanjut", "daftar", "register",
            "klik kirim", "klik login", "tekan kirim", "tekan login",
        )
    )


def _blocked_browser_tool_result(tool_call: dict[str, Any], transcript: str) -> str:
    name = tool_call.get("function", {}).get("name", "")
    args = _parse_tool_call_arguments(tool_call)
    if name == "browser_fill_form" and _truthy_argument(args.get("submit")):
        if not _has_explicit_browser_submit_intent(transcript):
            return (
                "Blocked browser_fill_form: submit=true requires an explicit user "
                "request in the current task."
            )
    if name == "whatsapp_send_message" and not _has_whatsapp_send_intent(transcript):
        return (
            "Blocked whatsapp_send_message: sending requires an explicit WhatsApp "
            "send/reply request in the current task."
        )
    return ""


def _looks_like_browser_action_success_claim(text: str) -> bool:
    normalized = _normalize_turn_text(text)
    if not normalized:
        return False
    success_terms = (
        "berhasil", "sudah", "done", "success", "clicked", "filled",
        "sent", "terkirim", "aku klik", "aku isi", "aku kirim",
        "form", "submit", "terisi",
    )
    return any(term in normalized for term in success_terms)


def _failed_browser_action_result(messages: list[dict[str, Any]]) -> str:
    tool_names_by_id: dict[str, str] = {}
    for message in messages:
        for tool_call in message.get("tool_calls") or []:
            tool_id = tool_call.get("id")
            name = tool_call.get("function", {}).get("name")
            if tool_id and name:
                tool_names_by_id[str(tool_id)] = str(name)

    for message in reversed(messages):
        if message.get("role") != "tool":
            continue
        tool_id = str(message.get("tool_call_id") or "")
        name = tool_names_by_id.get(tool_id, "")
        if name not in BROWSER_ACTION_TOOL_NAMES:
            continue
        content = str(message.get("content") or "").strip()
        lowered = content.lower()
        if (
            content.startswith("Failed")
            or content.startswith("Blocked")
            or content.startswith("Tool '")
            or "ambiguous" in lowered
            or "no confident" in lowered
            or "no matching" in lowered
            or "not found" in lowered
            or "login is required" in lowered
            or "could not confirm" in lowered
            or "could not verify" in lowered
            or "cannot verify" in lowered
            or "did not change" in lowered
        ):
            return content
    return ""


def _extract_browser_topic(transcript: str) -> str:
    text = re.sub(r"[^\w\s]", " ", transcript, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    patterns = (
        r"(?:tentang|about) (?P<topic>.+?)(?: (?:di|dari|from) wiki(?:pedia)?| terus| lalu| kemudian| habis itu| abis itu| dan|$)",
        r"(?:artikel|halaman) (?:tentang )?(?P<topic>.+?)(?: terus| lalu| kemudian| habis itu| abis itu| dan|$)",
        r"(?:wikipedia(?: indonesia)?(?: halaman)?(?: tentang)? )(?P<topic>.+?)(?: terus| lalu| kemudian| habis itu| abis itu| dan|$)",
        r"(?:cari|search|google) (?:info |informasi )?(?:tentang )?(?P<topic>.+?)(?: terus| lalu| kemudian| habis itu| abis itu| dan|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_browser_topic(match.group("topic"))
    return ""


def _clean_browser_topic(topic: str) -> str:
    topic = re.sub(r"\b(di|dari|from|wiki|wikipedia|artikel|halaman)\b", " ", topic, flags=re.IGNORECASE)
    topic = re.sub(
        r"\b(rangkum|ringkas|summarize|beritahu|kasih|beri|fakta|menarik|nih|ya|dong)\b",
        " ",
        topic,
        flags=re.IGNORECASE,
    )
    topic = re.sub(r"\b(dua|tiga|empat|lima|\d+)\b", " ", topic, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", topic).strip()


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


CANNED_ACKNOWLEDGEMENTS = {
    "web_search": "Bentar, aku cari dulu.",
    "browser_navigate": "Bentar, aku buka halamannya dulu.",
    "browser_read_current": "Bentar, aku baca halaman ini dulu.",
    "browser_status": "Bentar, aku cek status browser dulu.",
    "browser_inspect": "Bentar, aku cek elemen halamannya dulu.",
    "browser_click": "Bentar, aku klik dulu.",
    "browser_click_text": "Bentar, aku klik dulu.",
    "browser_click_role": "Bentar, aku klik dulu.",
    "browser_click_best_match": "Bentar, aku cari elemen yang cocok dulu.",
    "browser_input": "Bentar, aku isi dulu.",
    "browser_fill_form": "Bentar, aku isi form-nya dulu.",
    "get_weather": "Bentar, aku cek cuaca dulu.",
    "read_calendar": "Bentar, aku cek kalender dulu.",
    "create_event": "Bentar, aku buat acaranya dulu.",
    "send_message": "Bentar, aku kirim pesannya dulu.",
    "whatsapp_open": "Bentar, aku buka WhatsApp Web dulu.",
    "whatsapp_find_chat": "Bentar, aku cari chat WhatsApp-nya dulu.",
    "whatsapp_draft_message": "Bentar, aku ketik dulu di WhatsApp.",
    "whatsapp_send_message": "Bentar, aku kirim lewat WhatsApp dulu.",
    "run_shortcut": "Bentar, aku jalankan shortcut dulu.",
    "add_reminder": "Bentar, aku tambahkan pengingat dulu.",
    "complete_reminder": "Bentar, aku selesaikan pengingat dulu.",
}

# Intents safe to execute from stable partial transcripts (low-risk, reversible).
# Only these intents can trigger early execution before endpointing.
SAFE_LOCAL_INTENTS: frozenset[str] = frozenset({
    "system.set_volume",
    "system.get_volume",
    "system.set_muted",
    "music.pause",
    "music.resume",
    "music.play",
    "system.get_time",
    "system.get_brightness",
})

# Minimum stability (0.0–1.0) before a partial transcript is trusted for early execution.
EARLY_INTENT_STABILITY_THRESHOLD = 0.70


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
        on_user_partial_transcript: Callable[[str, float | None], None] | None = None,
        on_user_final_transcript: Callable[[str], None] | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_tool_iterations: int | None = None,
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
        self.on_user_partial_transcript = on_user_partial_transcript
        self.on_user_final_transcript = on_user_final_transcript
        self.system_prompt = system_prompt
        self.max_tool_iterations = (
            max_tool_iterations
            if max_tool_iterations is not None
            else self.config.voice.max_tool_iterations
        )
        self.local_intent_router = LocalIntentRouter()
        self.tool_selector = ToolSelector(self.config.tools.enabled or self.registry.names())
        self._current_turn: TurnContext | None = None

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

        # --- Streaming STT state ----------------------------------------
        self._streaming_stt_active = False
        self._streaming_stt_task: asyncio.Task | None = None
        self._streaming_audio_buffer = bytearray()
        self._streaming_last_send_time = 0.0
        self._early_intent_executed = False
        self._last_partial_text = ""  # partial transcript that triggered early intent
        self._streaming_partial_interval_ms = 1000  # ms between partial STT calls

        self._current_turn_id: int | None = None
        self._current_vad_timeline: list[dict[str, Any]] = []
        self._current_pipeline_events: list[dict[str, Any]] = []
        self._current_latency_metrics: dict[str, Any] = {}
        self._latency_tracker: LatencyTracker | None = None
        self._last_latency_summary: dict[str, Any] | None = None
        self._pending_whatsapp_task: dict[str, Any] | None = None
        self._last_whatsapp_result: dict[str, Any] | None = None
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

    def _is_active_turn(self, turn: TurnContext | None) -> bool:
        return (
            turn is not None
            and self._current_turn is turn
            and not turn.is_cancelled()
        )

    def _emit_pipeline_event_for_turn(
        self,
        turn: TurnContext | None,
        stage: str,
        event: str,
        metadata: dict[str, Any],
    ) -> None:
        if turn is not None and not self._is_active_turn(turn):
            return
        if self.on_pipeline_event:
            self.on_pipeline_event(stage, event, metadata)

    def _emit_transcript_for_turn(self, turn: TurnContext | None, transcript: str) -> None:
        if turn is not None and not self._is_active_turn(turn):
            return
        if self.on_transcript:
            self.on_transcript(transcript)

    def _emit_assistant_text_for_turn(self, turn: TurnContext | None, text: str) -> None:
        if turn is not None and not self._is_active_turn(turn):
            return
        if self.on_assistant_text:
            self.on_assistant_text(text)

    def _emit_user_partial_for_turn(
        self,
        turn: TurnContext | None,
        text: str,
        stability: float | None,
    ) -> None:
        if turn is not None and not self._is_active_turn(turn):
            return
        if self.on_user_partial_transcript:
            self.on_user_partial_transcript(text, stability)

    def _emit_user_final_for_turn(self, turn: TurnContext | None, text: str) -> None:
        if turn is not None and not self._is_active_turn(turn):
            return
        if self.on_user_final_transcript:
            self.on_user_final_transcript(text)

    def _emit_tool_executed_for_turn(
        self,
        turn: TurnContext | None,
        name: str,
        result: str,
    ) -> None:
        if turn is not None and not self._is_active_turn(turn):
            return
        if self.on_tool_executed:
            self.on_tool_executed(name, result)

    def _emit_audio_level_for_turn(self, turn: TurnContext | None, level: float) -> None:
        if turn is not None and not self._is_active_turn(turn):
            return
        if self.on_audio_level:
            self.on_audio_level(level)

    def _transition_for_turn(
        self,
        turn: TurnContext | None,
        action: Callable[[], Any],
    ) -> Any | None:
        if turn is not None and not self._is_active_turn(turn):
            return None
        return action()

    def _start_latency_tracker(self, turn_id: int | str | None) -> None:
        if turn_id is None:
            import time
            turn_id = f"turn-{time.time_ns()}"
        self._latency_tracker = LatencyTracker(str(turn_id))
        self._latency_tracker.set_metadata(
            provider={
                "stt": self.config.stt.provider,
                "llm": self.config.llm.provider,
                "tts": self.config.tts.provider,
            }
        )

    def _latency_mark(self, event_name: str, **data: Any) -> None:
        if self._latency_tracker is not None:
            self._latency_tracker.mark(event_name, **data)

    def _latency_metadata(self, **data: Any) -> None:
        if self._latency_tracker is not None:
            self._latency_tracker.set_metadata(**data)

    def _emit_latency_summary(self, turn_id: int | None) -> None:
        if self._latency_tracker is None:
            return
        summary = self._latency_tracker.summary()
        self._last_latency_summary = summary
        try:
            logger.info("latency_summary %s", json.dumps(summary, sort_keys=True))
        except TypeError:
            logger.info("latency_summary %s", summary)
        if self.debug_logger is not None and turn_id is not None:
            self.debug_logger.log_latency_summary(turn_id, summary)
        self._latency_tracker = None

    def _write_current_turn_data(self) -> None:
        if self.debug_logger is None or self._current_turn_id is None:
            self._emit_latency_summary(None)
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

        self._emit_latency_summary(turn_id)
            
        self._current_turn_id = None

    def start_listening(self, is_auto: bool = False) -> bool:
        if self.recorder is None:
            raise RuntimeError("Orchestrator has no recorder configured")
        # Ignore presses while busy or during the error-reset window.
        if self.recorder.is_recording or not self.state_machine.is_idle:
            if (
                not self.recorder.is_recording
                and not is_auto
                and self.state_machine.state in (State.THINKING, State.PREPARING_AUDIO, State.SPEAKING)
            ):
                return self.request_barge_in()
            return False
        if not is_auto:
            # Explicit PTT press → one-shot turn, no auto-continue.
            self._auto_listening = False
            self._conversation_mode_active = False

        if self.debug_logger is not None:
            if self._current_turn_id is not None:
                self._latency_mark("turn_done", auto_next_turn=True)
                self._write_current_turn_data()
            self._current_turn_id = self.debug_logger.new_turn()
            self._current_vad_timeline = []
            self._current_pipeline_events = []
            self._current_latency_metrics = {}
            self._input_audio_bytes = None
            self._output_audio_bytes = None
            self._llm_messages = []
            self._llm_response = {}

        # Reset streaming STT state for the new turn
        self._current_turn = None
        self._streaming_stt_active = False
        self._early_intent_executed = False
        self._last_partial_text = ""
        if self._streaming_stt_task is not None:
            self._streaming_stt_task.cancel()
            self._streaming_stt_task = None

        self._start_latency_tracker(self._current_turn_id)
        self._latency_mark("hotkey_down", auto=is_auto)
        self.state_machine.hotkey_pressed()
        self._latency_mark("record_start")
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
        self._latency_mark("audio_wav_ready", bytes=len(audio))
        self._latency_metadata(audio_ms=_audio_duration_ms(audio))
        
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
        if self._latency_tracker is None:
            self._start_latency_tracker(self._current_turn_id)
            self._latency_mark("audio_wav_ready", bytes=len(audio), source="direct")
            self._latency_metadata(audio_ms=_audio_duration_ms(audio))

        turn_id = self._current_turn_id
        self._current_turn = TurnContext(id=turn_id or "turn_default")
        self._input_audio_bytes = audio

        try:
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                pass
            start_stt = time.time()
            self._latency_mark("stt_start")
            transcript = await self._transcribe(audio)
            if not self._is_active_turn(self._current_turn):
                return ""
            self._latency_mark("stt_final", chars=len(transcript))
            self._latency_metadata(transcript_chars=len(transcript))
            stt_duration = time.time() - start_stt
            print(f"[Debug] STT took: {stt_duration:.2f}s")
            if not transcript.strip():
                print("Transcript is empty, returning to listening state.")
                self.state_machine.force_idle()
                if self.conversation_mode_active:
                    self.start_auto_listening()
                return ""

            if self.debug_logger is not None and self._current_turn_id == turn_id and turn_id is not None:
                self._current_latency_metrics["stt_ms"] = int(stt_duration * 1000)

            start_llm = time.time()
            reply = await self._respond_and_speak_streaming(transcript, history or [])
            if not self._is_active_turn(self._current_turn):
                return reply
            llm_duration = time.time() - start_llm
            print(f"[Debug] Response took: {llm_duration:.2f}s")

            if self.debug_logger is not None and self._current_turn_id == turn_id and turn_id is not None:
                self._current_latency_metrics["llm_ms"] = int(llm_duration * 1000)
            if self._current_turn_id == turn_id:
                self._latency_mark("turn_done")
                self._write_current_turn_data()
            elif turn_id is None:
                self._latency_mark("turn_done")
                self._write_current_turn_data()

            return reply
        except Exception as exc:  # surface failure to UI/state machine
            self._latency_mark("turn_done", error=exc.__class__.__name__)
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
            elif turn_id is None:
                self._write_current_turn_data()
            raise

    async def _transcribe(self, audio: bytes) -> str:
        turn = self._current_turn
        language = self.config.stt.language
        self._emit_pipeline_event_for_turn(turn, "stt", "started", {})
        transcript = await self.stt.transcribe(audio, language=language)
        transcript = transcript.strip()
        self._emit_pipeline_event_for_turn(turn, "stt", "completed", {"text": transcript})
        self._emit_transcript_for_turn(turn, transcript)
        return transcript

    def _build_llm_context(
        self,
        transcript: str,
        history: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]] | None, IntentCategory]:
        category, _, _ = fast_intent_classifier(transcript)
        base_history = history if history else self._conversation_history
        context_text = " ".join(
            [transcript]
            + [
                str(message.get("content", ""))
                for message in base_history
                if message.get("role") == "user"
            ]
        )
        base_history = _sanitize_history_for_context(base_history, category, context_text)
        system_prompt = self._compose_system_prompt()
        browser_context = category == IntentCategory.BROWSER or _looks_like_browser_hosted_app_text(context_text)
        if browser_context:
            system_prompt = f"{system_prompt}\n\n{BROWSER_TURN_DIRECTIVE}"
        if _looks_like_whatsapp_web_turn(context_text):
            system_prompt = f"{system_prompt}\n\n{WHATSAPP_TURN_DIRECTIVE}"
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *base_history,
            {"role": "user", "content": transcript},
        ]
        selected_tools = self.tool_selector.select(transcript, category)
        definitions = self.registry.list_definitions(selected_tools)
        return messages, definitions or None, category

    async def _respond_and_speak_streaming(
        self,
        transcript: str,
        history: list[dict[str, Any]],
    ) -> str:
        turn = self._current_turn or TurnContext(id=self._current_turn_id or "turn_default")
        self._current_turn = turn

        whatsapp_reply = await self._try_whatsapp_task_flow(transcript, turn)
        if whatsapp_reply is not None:
            self._llm_messages = [{"role": "user", "content": transcript}]
            self._llm_response = {"text": whatsapp_reply}
            self._remember_turn(transcript, whatsapp_reply)
            if not self._is_active_turn(turn):
                return whatsapp_reply
            self._emit_assistant_text_for_turn(turn, whatsapp_reply)
            await self.speak_text_immediately(turn, whatsapp_reply)
            if self.conversation_mode_active:
                self.start_auto_listening()
            return whatsapp_reply

        self._latency_mark("local_intent_start")
        local_reply = self._try_local_intent(transcript)
        self._latency_mark("local_intent_done", matched=local_reply is not None)

        if local_reply is not None:
            self._llm_messages = [{"role": "user", "content": transcript}]
            self._llm_response = {"text": local_reply}
            self._remember_turn(transcript, local_reply)
            if not self._is_active_turn(turn):
                return local_reply
            await self.speak_text_immediately(turn, local_reply)
            if self.conversation_mode_active:
                self.start_auto_listening()
            return local_reply

        messages, tools, category = self._build_llm_context(transcript, history)
        reply = ""
        total_tool_ms = 0.0
        tool_count = 0
        llm_started = False
        llm_first_token_seen = False
        browser_retry_attempted = False
        browser_fallback_used = False
        browser_context = category == IntentCategory.BROWSER or _looks_like_browser_hosted_app_text(transcript)
        suppress_pre_tool_text = _should_suppress_pre_tool_speech(transcript, category, tools)

        for _ in range(self.max_tool_iterations):
            if not llm_started:
                self._latency_mark("llm_request_start")
                llm_started = True

            result = await self._stream_llm_once(
                turn,
                messages,
                tools,
                llm_first_token_seen=llm_first_token_seen,
                suppress_pre_tool_text=suppress_pre_tool_text,
            )
            llm_first_token_seen = llm_first_token_seen or result["first_token_seen"]
            speech_task = result["speech_task"]
            tool_calls = result["tool_calls"]
            text = result["text"].strip()

            if not self._is_active_turn(turn):
                if speech_task is not None:
                    try:
                        await speech_task
                    except asyncio.CancelledError:
                        pass
                return text

            if not tool_calls:
                if (
                    browser_context
                    and tools
                    and _looks_like_browser_refusal(text)
                ):
                    if speech_task is not None:
                        try:
                            playback = turn.playback
                            if playback is not None:
                                await playback.clear()
                        except Exception:
                            pass
                        if not speech_task.done():
                            speech_task.cancel()
                        try:
                            await speech_task
                        except asyncio.CancelledError:
                            pass

                    if not browser_retry_attempted:
                        browser_retry_attempted = True
                        self._emit_pipeline_event_for_turn(
                            turn,
                            "browser",
                            "refusal_retry",
                            {"transcript": transcript},
                        )
                        messages.append({"role": "assistant", "content": text})
                        messages.append(_browser_retry_message(transcript))
                        continue

                    if not browser_fallback_used:
                        browser_fallback_used = True
                        tool_call = _synthesize_browser_tool_call(
                            transcript,
                            messages,
                            _tool_names_from_definitions(tools),
                        )
                        messages.append(
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [tool_call],
                            }
                        )
                        tool_result, tool_duration = await self._run_tool_for_turn(turn, tool_call)
                        if not self._is_active_turn(turn):
                            return text
                        total_tool_ms += tool_duration
                        tool_count += 1
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.get("id"),
                                "content": tool_result,
                            }
                        )
                        continue

                if browser_context and _looks_like_whatsapp_send_claim(text) and tool_count == 0:
                    reply = await self._recover_or_block_whatsapp_claim(transcript, turn)
                    self._llm_response = {"text": reply, "tool_calls": []}
                    self._latency_mark("llm_done", chars=len(reply), tool_calls=tool_count)
                    if speech_task is not None:
                        try:
                            if turn.playback is not None:
                                await turn.playback.clear()
                        except Exception:
                            pass
                        if not speech_task.done():
                            speech_task.cancel()
                        try:
                            await speech_task
                        except asyncio.CancelledError:
                            pass
                    elif reply and self._is_active_turn(turn):
                        self._emit_assistant_text_for_turn(turn, reply)
                        await self.speak_text_immediately(turn, reply)
                    break

                failed_action = _failed_browser_action_result(messages)
                if (
                    browser_context
                    and failed_action
                    and _looks_like_browser_action_success_claim(text)
                ):
                    reply = f"Aku belum bisa menyelesaikan aksi browser-nya: {failed_action}"
                    self._llm_response = {"text": reply, "tool_calls": []}
                    self._latency_mark("llm_done", chars=len(reply), tool_calls=tool_count)
                    if speech_task is not None:
                        try:
                            if turn.playback is not None:
                                await turn.playback.clear()
                        except Exception:
                            pass
                        if not speech_task.done():
                            speech_task.cancel()
                        try:
                            await speech_task
                        except asyncio.CancelledError:
                            pass
                    elif reply and self._is_active_turn(turn):
                        self._emit_assistant_text_for_turn(turn, reply)
                        await self.speak_text_immediately(turn, reply)
                    break

                reply = text
                self._llm_response = {"text": reply, "tool_calls": []}
                self._latency_mark("llm_done", chars=len(reply), tool_calls=tool_count)
                if speech_task is not None:
                    try:
                        await speech_task
                    except asyncio.CancelledError:
                        pass
                elif reply and self._is_active_turn(turn):
                    self._emit_assistant_text_for_turn(turn, reply)
                    await self.speak_text_immediately(turn, reply)
                break

            if speech_task is not None:
                try:
                    await speech_task
                except asyncio.CancelledError:
                    pass
            if not self._is_active_turn(turn):
                return text

            messages.append(
                {
                    "role": "assistant",
                    "content": text or None,
                    "tool_calls": tool_calls,
                }
            )
            for tool_call in tool_calls:
                name = tool_call.get("function", {}).get("name", "")
                blocked_result = _blocked_browser_tool_result(tool_call, transcript)
                if blocked_result:
                    self._emit_tool_executed_for_turn(turn, name, blocked_result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id"),
                            "content": blocked_result,
                        }
                    )
                    continue

                if name in CANNED_ACKNOWLEDGEMENTS and self._current_turn is not None:
                    if not getattr(self._current_turn, "canned_ack_spoken", False):
                        self._current_turn.canned_ack_spoken = True
                        ack_text = CANNED_ACKNOWLEDGEMENTS[name]
                        await self.speak_text_immediately(self._current_turn, ack_text)
                        self.state_machine.force_thinking()

                tool_result, tool_duration = await self._run_tool_for_turn(turn, tool_call)
                if not self._is_active_turn(turn):
                    return text
                total_tool_ms += tool_duration
                tool_count += 1

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "content": tool_result,
                    }
                )
        else:
            result = await self._stream_llm_once(
                turn,
                messages,
                None,
                llm_first_token_seen=llm_first_token_seen,
            )
            llm_first_token_seen = llm_first_token_seen or result["first_token_seen"]
            reply = result["text"].strip()
            if self._is_active_turn(turn):
                self._llm_response = {"text": reply, "tool_calls": []}
                self._latency_mark("llm_done", chars=len(reply), tool_calls=tool_count)
            if result["speech_task"] is not None:
                try:
                    await result["speech_task"]
                except asyncio.CancelledError:
                    pass

        self._llm_messages = messages
        self._latency_metadata(tool_count=tool_count)
        if self.debug_logger is not None and self._current_turn_id is not None:
            previous = int(self._current_latency_metrics.get("tool_ms", 0) or 0)
            self._current_latency_metrics["tool_ms"] = previous + int(total_tool_ms * 1000)

        if self._is_active_turn(turn):
            self._remember_turn(transcript, reply)
        if self._is_active_turn(turn) and self.conversation_mode_active:
            self.start_auto_listening()
        return reply

    async def _stream_llm_once(
        self,
        turn: TurnContext,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        *,
        llm_first_token_seen: bool,
        suppress_pre_tool_text: bool = False,
    ) -> dict[str, Any]:
        sentinel = object()
        text_queue: asyncio.Queue[str | object] = asyncio.Queue()
        first_text = asyncio.Event()
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        first_token_marked = False
        meaningful_text_seen = False
        tool_started_before_text = False
        tool_started_after_text = False

        async def queued_text_stream() -> AsyncIterator[str]:
            while True:
                item = await text_queue.get()
                if item is sentinel:
                    break
                yield str(item)

        async def interrupt_stream_for_tool() -> None:
            playback = turn.playback
            if playback is None:
                return
            try:
                await playback.clear()
            except Exception:
                pass

        async def produce() -> None:
            nonlocal first_token_marked
            nonlocal meaningful_text_seen
            nonlocal tool_started_before_text
            nonlocal tool_started_after_text

            try:
                async for event in self._llm_stream_events(messages, tools):
                    if not self._is_active_turn(turn):
                        break

                    if event.type == "text_delta":
                        if not event.text or tool_started_before_text or tool_started_after_text:
                            continue

                        text_parts.append(event.text)
                        if not suppress_pre_tool_text:
                            self._emit_assistant_text_for_turn(turn, "".join(text_parts))

                        if event.text.strip():
                            meaningful_text_seen = True
                            if not llm_first_token_seen and not first_token_marked:
                                self._latency_mark("llm_first_token")
                                first_token_marked = True
                            if not suppress_pre_tool_text:
                                first_text.set()

                        if self._is_active_turn(turn) and not suppress_pre_tool_text:
                            await text_queue.put(event.text)
                        continue

                    if event.type in ("tool_call_delta", "tool_call_done"):
                        if suppress_pre_tool_text:
                            text_parts.clear()
                        if meaningful_text_seen:
                            tool_started_after_text = True
                            if event.type == "tool_call_done" and event.tool_call:
                                tool_calls.append(event.tool_call)
                                await interrupt_stream_for_tool()
                                break
                            continue

                        tool_started_before_text = True
                        if event.type == "tool_call_done" and event.tool_call:
                            tool_calls.append(event.tool_call)
                        continue

                    if event.type == "error":
                        raw = event.raw
                        if isinstance(raw, BaseException):
                            raise raw
                        raise RuntimeError(event.text or "LLM stream failed")

                    if event.type == "done":
                        break
            finally:
                await text_queue.put(sentinel)

        producer_task = asyncio.create_task(produce())
        turn.llm_task = producer_task
        first_text_task = asyncio.create_task(first_text.wait())
        speech_task: asyncio.Task[None] | None = None

        try:
            done, _ = await asyncio.wait(
                {producer_task, first_text_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if first_text.is_set() and self._is_active_turn(turn):
                speech_task = asyncio.create_task(self.speak_streaming(turn, queued_text_stream()))
                turn.tts_task = speech_task

            if first_text_task not in done and not first_text_task.done():
                first_text_task.cancel()
                try:
                    await first_text_task
                except asyncio.CancelledError:
                    pass

            try:
                await producer_task
            except asyncio.CancelledError:
                pass
        finally:
            if turn.llm_task is producer_task:
                turn.llm_task = None

        return {
            "text": "".join(text_parts),
            "tool_calls": tool_calls,
            "first_token_seen": first_token_marked,
            "speech_task": speech_task,
        }

    async def _llm_stream_events(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        stream_chat = None
        if isinstance(self.llm, LLMAdapter) or getattr(type(self.llm), "stream_chat", None) is not None:
            stream_chat = getattr(self.llm, "stream_chat", None)

        if stream_chat is not None:
            stream = stream_chat(messages, tools=tools)
            if hasattr(stream, "__aiter__"):
                async for event in stream:
                    yield event
                return

        response = await self.llm.chat(messages, tools=tools)
        if response.tool_calls:
            for tool_call in response.tool_calls:
                yield LLMStreamEvent(
                    type="tool_call_done",
                    tool_call=tool_call,
                    raw=getattr(response, "raw", None),
                )
        elif response.text:
            yield LLMStreamEvent(
                type="text_delta",
                text=response.text,
                raw=getattr(response, "raw", None),
            )
        yield LLMStreamEvent(type="done", raw=getattr(response, "raw", None))

    async def _respond(self, transcript: str, history: list[dict[str, Any]]) -> str:
        whatsapp_reply = await self._try_whatsapp_task_flow(transcript)
        if whatsapp_reply is not None:
            self._llm_messages = [{"role": "user", "content": transcript}]
            self._llm_response = {"text": whatsapp_reply}
            self._remember_turn(transcript, whatsapp_reply)
            if self.on_assistant_text:
                self.on_assistant_text(whatsapp_reply)
            return whatsapp_reply

        self._latency_mark("local_intent_start")
        local_reply = self._try_local_intent(transcript)
        self._latency_mark("local_intent_done", matched=local_reply is not None)
        if local_reply is not None:
            self._llm_messages = [{"role": "user", "content": transcript}]
            self._llm_response = {"text": local_reply}
            self._remember_turn(transcript, local_reply)
            return local_reply

        messages, tools, category = self._build_llm_context(transcript, history)

        reply = ""
        total_tool_ms = 0.0
        tool_count = 0
        llm_started = False
        llm_first_token_seen = False
        browser_retry_attempted = False
        browser_fallback_used = False
        browser_context = category == IntentCategory.BROWSER or _looks_like_browser_hosted_app_text(transcript)
        for _ in range(self.max_tool_iterations):
            if not llm_started:
                self._latency_mark("llm_request_start")
                llm_started = True
            response = await self.llm.chat(messages, tools=tools)
            if response.text and not llm_first_token_seen:
                self._latency_mark("llm_first_token")
                llm_first_token_seen = True
            if not response.tool_calls:
                if (
                    browser_context
                    and tools
                    and _looks_like_browser_refusal(response.text)
                ):
                    if not browser_retry_attempted:
                        browser_retry_attempted = True
                        if self.on_pipeline_event:
                            self.on_pipeline_event(
                                "browser",
                                "refusal_retry",
                                {"transcript": transcript},
                            )
                        messages.append({"role": "assistant", "content": response.text.strip()})
                        messages.append(_browser_retry_message(transcript))
                        continue

                    if not browser_fallback_used:
                        browser_fallback_used = True
                        tool_call = _synthesize_browser_tool_call(
                            transcript,
                            messages,
                            _tool_names_from_definitions(tools),
                        )
                        messages.append(
                            {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [tool_call],
                            }
                        )
                        import time
                        start_tool = time.time()
                        result = self._run_tool(tool_call)
                        tool_duration = time.time() - start_tool
                        total_tool_ms += tool_duration
                        tool_count += 1
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.get("id"),
                                "content": result,
                            }
                        )
                        continue

                if browser_context and _looks_like_whatsapp_send_claim(response.text) and tool_count == 0:
                    reply = await self._recover_or_block_whatsapp_claim(transcript)
                    self._llm_response = {
                        "text": reply,
                        "tool_calls": []
                    }
                    self._latency_mark("llm_done", chars=len(reply), tool_calls=tool_count)
                    break

                failed_action = _failed_browser_action_result(messages)
                if (
                    browser_context
                    and failed_action
                    and _looks_like_browser_action_success_claim(response.text)
                ):
                    reply = f"Aku belum bisa menyelesaikan aksi browser-nya: {failed_action}"
                    self._llm_response = {
                        "text": reply,
                        "tool_calls": []
                    }
                    self._latency_mark("llm_done", chars=len(reply), tool_calls=tool_count)
                    break

                reply = response.text.strip()
                self._llm_response = {
                    "text": reply,
                    "tool_calls": []
                }
                self._latency_mark("llm_done", chars=len(reply), tool_calls=tool_count)
                break

            messages.append(
                {
                    "role": "assistant",
                    "content": response.text or None,
                    "tool_calls": response.tool_calls,
                }
            )
            for tool_call in response.tool_calls:
                name = tool_call.get("function", {}).get("name", "")
                blocked_result = _blocked_browser_tool_result(tool_call, transcript)
                if blocked_result:
                    if self.on_tool_executed:
                        self.on_tool_executed(name, blocked_result)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.get("id"),
                            "content": blocked_result,
                        }
                    )
                    continue

                if name in CANNED_ACKNOWLEDGEMENTS and self._current_turn is not None:
                    if not getattr(self._current_turn, "canned_ack_spoken", False):
                        self._current_turn.canned_ack_spoken = True
                        ack_text = CANNED_ACKNOWLEDGEMENTS[name]
                        await self.speak_text_immediately(self._current_turn, ack_text)
                        self.state_machine.force_thinking()

                import time
                start_tool = time.time()
                result = self._run_tool(tool_call)
                tool_duration = time.time() - start_tool
                total_tool_ms += tool_duration
                tool_count += 1

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
            if response.text and not llm_first_token_seen:
                self._latency_mark("llm_first_token")
                llm_first_token_seen = True
            reply = response.text.strip()
            self._llm_response = {
                "text": reply,
                "tool_calls": []
            }
            self._latency_mark("llm_done", chars=len(reply), tool_calls=tool_count)

        self._llm_messages = messages
        self._latency_metadata(tool_count=tool_count)
        if self.debug_logger is not None and self._current_turn_id is not None:
            previous = int(self._current_latency_metrics.get("tool_ms", 0) or 0)
            self._current_latency_metrics["tool_ms"] = previous + int(total_tool_ms * 1000)

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

    async def _execute_flow_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        turn: TurnContext | None = None,
    ) -> tuple[dict[str, Any], str, float]:
        import time

        tool_call = _make_synthetic_tool_call(name, arguments or {})
        if turn is not None:
            result, duration = await self._run_tool_for_turn(turn, tool_call)
        else:
            start = time.time()
            result = self._run_tool(tool_call)
            duration = time.time() - start

        if name.startswith("whatsapp_"):
            self._last_whatsapp_result = {
                "tool": name,
                "arguments": arguments or {},
                "result": result,
                "sent": name == "whatsapp_send_message" and _whatsapp_send_succeeded(result),
            }
        if self.debug_logger is not None and self._current_turn_id is not None:
            previous = int(self._current_latency_metrics.get("tool_ms", 0) or 0)
            self._current_latency_metrics["tool_ms"] = previous + int(duration * 1000)
        return tool_call, result, duration

    def _pending_whatsapp_message_text(self, transcript: str) -> str:
        if self._pending_whatsapp_task is None:
            return ""
        if _is_whatsapp_status_query(transcript) or _is_whatsapp_open_request(transcript):
            return ""

        explicit = _extract_whatsapp_message_text(transcript)
        if explicit:
            return explicit

        category, _, _ = fast_intent_classifier(transcript)
        if category not in (IntentCategory.UNKNOWN, IntentCategory.CHAT):
            return ""

        candidate = _clean_whatsapp_message_fragment(transcript)
        if not candidate or len(candidate.split()) > 24:
            return ""
        return candidate

    def _reply_for_whatsapp_tool(self, tool_name: str, result: str, contact: str | None = None) -> str:
        lower = result.lower()
        target = contact or "kontak itu"
        if result.startswith("Failed") or result.startswith("Blocked") or result.startswith("Tool '"):
            return f"Aku belum bisa menyelesaikan aksi WhatsApp-nya: {result}"

        if tool_name == "whatsapp_open":
            if "login is required" in lower:
                return "WhatsApp Web sudah terbuka, tapi perlu login dulu. Scan QR code-nya dulu ya."
            if "ready" in lower:
                return "WhatsApp Web sudah terbuka dan siap."
            return "WhatsApp Web sudah aku buka, tapi aku belum bisa memastikan status login-nya."

        if "login is required" in lower:
            return "WhatsApp Web perlu login dulu. Scan QR code-nya, lalu aku bisa lanjut."

        if tool_name == "whatsapp_find_chat":
            return f"Chat WhatsApp dengan {target} sudah aku buka."
        if tool_name == "whatsapp_draft_message":
            return f"Pesan ke {target} sudah aku ketik sebagai draft. Belum aku kirim."
        if tool_name == "whatsapp_send_message":
            if _whatsapp_send_succeeded(result):
                return f"Sudah, pesan WhatsApp ke {target} aku kirim."
            return f"Aku belum bisa memastikan pesan ke {target} terkirim: {result}"
        return result

    async def _send_pending_whatsapp_task(self, turn: TurnContext | None = None) -> str:
        pending = self._pending_whatsapp_task or {}
        contact = str(pending.get("contact") or "").strip()
        text = str(pending.get("text") or "").strip()
        if not contact or not text:
            return "Aku belum punya kontak dan isi pesan WhatsApp yang lengkap."

        _, result, _ = await self._execute_flow_tool(
            "whatsapp_send_message",
            {"contact": contact, "text": text},
            turn,
        )
        if _whatsapp_send_succeeded(result):
            self._pending_whatsapp_task = None
        else:
            self._pending_whatsapp_task = {
                "channel": "whatsapp",
                "contact": contact,
                "text": text,
                "send_requested": True,
            }
        return self._reply_for_whatsapp_tool("whatsapp_send_message", result, contact)

    async def _recover_or_block_whatsapp_claim(
        self,
        transcript: str,
        turn: TurnContext | None = None,
    ) -> str:
        if self._pending_whatsapp_task and self._pending_whatsapp_task.get("text"):
            return await self._send_pending_whatsapp_task(turn)
        if _looks_like_whatsapp_web_turn(transcript):
            contact = _extract_whatsapp_contact(transcript)
            text = _extract_whatsapp_message_text(transcript)
            if contact and text and _has_whatsapp_send_intent(transcript):
                self._pending_whatsapp_task = {
                    "channel": "whatsapp",
                    "contact": contact,
                    "text": text,
                    "send_requested": True,
                }
                return await self._send_pending_whatsapp_task(turn)
        return "Aku belum menjalankan tool WhatsApp, jadi aku belum bisa bilang pesannya terkirim."

    async def _try_whatsapp_task_flow(
        self,
        transcript: str,
        turn: TurnContext | None = None,
    ) -> str | None:
        whatsappish = _looks_like_whatsapp_web_turn(transcript)
        pending_text = self._pending_whatsapp_message_text(transcript)
        has_pending = self._pending_whatsapp_task is not None
        has_last = self._last_whatsapp_result is not None
        status_query = _is_whatsapp_status_query(transcript) and (has_pending or has_last)

        if not whatsappish and not pending_text and not status_query:
            return None

        if status_query:
            last = self._last_whatsapp_result or {}
            if last.get("sent"):
                args = last.get("arguments") or {}
                contact = str(args.get("contact") or "kontak itu")
                return f"Terakhir, tool WhatsApp berhasil mengirim pesan ke {contact}."
            if self._pending_whatsapp_task and self._pending_whatsapp_task.get("text"):
                return await self._send_pending_whatsapp_task(turn)
            return "Aku belum punya pesan WhatsApp lengkap yang bisa aku kirim ulang."

        contact = _extract_whatsapp_contact(transcript)
        message_text = _extract_whatsapp_message_text(transcript)
        send_requested = _has_whatsapp_send_intent(transcript)

        if not whatsappish and pending_text and self._pending_whatsapp_task is not None:
            pending = self._pending_whatsapp_task
            contact = str(pending.get("contact") or "").strip()
            message_text = pending_text
            send_requested = bool(pending.get("send_requested"))

        if whatsappish and _is_whatsapp_open_request(transcript) and not contact:
            _, result, _ = await self._execute_flow_tool("whatsapp_open", {}, turn)
            return self._reply_for_whatsapp_tool("whatsapp_open", result)

        if contact and not message_text:
            self._pending_whatsapp_task = {
                "channel": "whatsapp",
                "contact": contact,
                "text": "",
                "send_requested": send_requested,
            }
            _, result, _ = await self._execute_flow_tool("whatsapp_open", {}, turn)
            if "login is required" in result.lower():
                return f"WhatsApp Web perlu login dulu. Setelah scan QR, pesan ke {contact} mau bilang apa?"
            return f"Siap, WhatsApp Web aku buka. Pesan ke {contact} mau bilang apa?"

        if contact and message_text:
            self._pending_whatsapp_task = {
                "channel": "whatsapp",
                "contact": contact,
                "text": message_text,
                "send_requested": send_requested,
            }
            if send_requested:
                return await self._send_pending_whatsapp_task(turn)

            _, result, _ = await self._execute_flow_tool(
                "whatsapp_draft_message",
                {"contact": contact, "text": message_text},
                turn,
            )
            return self._reply_for_whatsapp_tool("whatsapp_draft_message", result, contact)

        return None

    def _try_local_intent(self, transcript: str) -> str | None:
        turn = self._current_turn
        if not self.config.intent.local_router_enabled:
            return None

        # 1. Classification prior to routing
        category, _, requires_confirmation = fast_intent_classifier(transcript)

        # 2. Search local matched intents
        match = self.local_intent_router.route(transcript)
        if match is None:
            return None

        # 3. Dynamic thresholds based on action risk
        if "volume" in match.intent:
            threshold = 0.65
        elif "reminder" in match.intent or "calendar" in match.intent or "event" in match.intent:
            threshold = 0.85
        else:
            threshold = self.config.intent.local_router_confidence_threshold

        # Flag actions requiring confirmation by routing them to the LLM path instead of local
        if requires_confirmation or match.intent == "message.send" or "delete" in match.intent:
            return None

        if match.confidence < threshold:
            self._emit_pipeline_event_for_turn(
                turn,
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
            self._emit_pipeline_event_for_turn(
                turn,
                "intent",
                "local_unavailable",
                {
                    "intent": match.intent,
                    "confidence": match.confidence,
                    "tool": match.tool_name,
                },
            )
            return None

        self._emit_pipeline_event_for_turn(
            turn,
            "intent",
            "local_matched",
            {
                "intent": match.intent,
                "confidence": match.confidence,
                "tool": match.tool_name,
                "category": category.value,
            },
        )

        reply = self._execute_local_intent(match)
        self._emit_assistant_text_for_turn(turn, reply)
        return reply

    # --- Streaming STT partial transcript handling ---------------------------

    def _try_local_intent_from_partial(
        self, transcript: str, stability: float
    ) -> str | None:
        """Check whether a partial transcript is stable enough to trigger early
        local intent execution before endpointing completes.

        Only fires once per turn (guarded by _early_intent_executed) and only
        for intents in SAFE_LOCAL_INTENTS with stability >= threshold.
        """
        if self._early_intent_executed:
            return None
        if stability < EARLY_INTENT_STABILITY_THRESHOLD:
            return None
        if len(transcript.strip()) < 3:
            return None
        if not self.config.intent.local_router_enabled:
            return None

        # Classify the partial transcript
        category, confidence, requires_confirmation = fast_intent_classifier(
            transcript
        )
        if requires_confirmation:
            return None

        # Route to local patterns
        match = self.local_intent_router.route(transcript)
        if match is None:
            return None

        # Only allow safe, low-risk intents to fire early
        if match.intent not in SAFE_LOCAL_INTENTS:
            return None

        # Apply intent-specific threshold
        if "volume" in match.intent:
            threshold = 0.65
        elif "reminder" in match.intent or "calendar" in match.intent:
            threshold = 0.85
        else:
            threshold = self.config.intent.local_router_confidence_threshold

        if match.confidence < threshold:
            return None

        if match.tool_name and not self._local_intent_tool_available(match.tool_name):
            return None

        # Mark as executed so we don't fire again for this turn
        self._early_intent_executed = True
        self._last_partial_text = transcript

        self._emit_pipeline_event_for_turn(
            self._current_turn,
            "intent",
            "early_local_matched",
            {
                "intent": match.intent,
                "confidence": match.confidence,
                "stability": stability,
                "partial": transcript,
            },
        )

        reply = self._execute_local_intent(match)
        self._emit_assistant_text_for_turn(self._current_turn, reply)
        return reply

    async def _run_streaming_stt_task(self) -> None:
        """Background task that reads audio chunks from the recorder and sends
        them to the streaming STT adapter every _streaming_partial_interval_ms.

        Emits partial transcript events via on_user_partial_transcript and
        checks for early local intent from stable partials.

        This task is spawned from _run_vad_loop and cancelled when VAD endpoints.
        """
        import numpy as np

        buffer = bytearray()
        last_send_time = 0.0
        interval_s = self._streaming_partial_interval_ms / 1000.0
        prev_partial_text = ""
        prev_stable_since = 0.0
        import time as time_module

        async def send_partial() -> tuple[str, float] | None:
            nonlocal last_send_time, prev_partial_text, prev_stable_since
            if len(buffer) < 8000:  # ~0.5s of audio at 16kHz
                return None
            audio_bytes = bytes(buffer)
            try:
                result = await self.stt.transcribe(audio_bytes, language=None)
            except Exception:
                return None
            text = result.strip()
            if not text:
                return None

            now = time_module.time()
            # Compute a rough stability: 0.5 + 0.5 * (1 - time_delta / 3.0)
            # Clamped to [0.5, 1.0]. Stability grows as the transcript stays
            # the same across consecutive calls.
            if text == prev_partial_text:
                elapsed = now - prev_stable_since
                stability = min(1.0, 0.5 + 0.5 * min(elapsed / 1.5, 1.0))
            else:
                stability = 0.5
                prev_partial_text = text
                prev_stable_since = now

            last_send_time = now
            return (text, stability)

        try:
            while self._streaming_stt_active and self.recorder and self.recorder.is_recording:
                try:
                    chunk = await asyncio.wait_for(
                        self.recorder.read_chunk(), timeout=2.0
                    )
                except asyncio.TimeoutError:
                    continue
                except RuntimeError:
                    # Recording stopped — exit gracefully
                    break

                # Convert float32 samples to int16 PCM bytes and accumulate
                flat = np.asarray(chunk, dtype=np.float32).reshape(-1)
                int16_data = (np.clip(flat, -1.0, 1.0) * 32767).astype(
                    np.int16
                )
                buffer.extend(int16_data.tobytes())

                # Check if it's time to send a partial
                now = time_module.time()
                if now - last_send_time >= interval_s:
                    result = await send_partial()
                    if result is not None:
                        text, stability = result
                        self._emit_user_partial_for_turn(self._current_turn, text, stability)

                        # Check for early local intent from stable partial
                        early_reply = self._try_local_intent_from_partial(
                            text, stability
                        )
                        if early_reply is not None:
                            self._streaming_stt_active = False
                            break

        except asyncio.CancelledError:
            return
        except Exception:
            pass

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
        lower_result = result.lower()
        if (
            result.startswith("Failed")
            or result.startswith("I cannot")
            or "failed" in lower_result
            or "not found" in lower_result
            or "does not exist" in lower_result
        ):
            return result

        if intent == "system.set_volume":
            level = arguments.get("level", 50)
            return f"Siap, volume aku set ke {level}%."
            
        elif intent == "system.get_volume":
            import re
            match = re.search(r"\d+", result)
            level = match.group(0) if match else "50"
            return f"Volume sekarang {level}%."
            
        elif intent == "system.set_muted":
            muted = arguments.get("muted", False)
            if muted:
                return "Siap, suara aku mute."
            return "Siap, suara aku nyalakan lagi."
                
        elif intent == "system.set_dark_mode":
            enabled = arguments.get("enabled", False)
            if enabled:
                return "Siap, mode gelap aktif."
            return "Siap, mode terang aktif."
                
        elif intent == "system.set_dnd":
            enabled = arguments.get("enabled", False)
            if enabled:
                return "Siap, Do Not Disturb aktif."
            return "Siap, Do Not Disturb aku matikan."
                
        elif intent == "system.set_brightness":
            level = arguments.get("level", 50)
            return f"Siap, kecerahan aku set ke {level}%."
            
        elif intent == "system.get_brightness":
            import re
            match = re.search(r"\d+", result)
            level = match.group(0) if match else "50"
            return f"Kecerahan layar sekarang {level}%."

        elif intent == "system.open_app":
            app_name = arguments.get("app_name", "aplikasi")
            return f"Siap, aku buka {app_name}."

        elif intent == "system.close_app":
            app_name = arguments.get("app_name", "aplikasi")
            return f"Siap, aku tutup {app_name}."

        elif intent == "music.pause":
            return "Oke, musik aku pause."

        elif intent == "music.resume":
            return "Oke, musik aku lanjutkan."

        elif intent == "music.play":
            query = arguments.get("query")
            if query:
                return f"Oke, aku putar {query}."
            return "Oke, musik aku lanjutkan."

        elif intent == "browser.navigate":
            url = arguments.get("url", "halaman itu")
            return f"Siap, aku buka {url}."

        elif intent == "browser.search":
            url = arguments.get("url", "")
            return "Siap, aku cari di Google." if "google.com/search" in url else "Siap, aku buka pencarian."

        elif intent == "web.search":
            query = arguments.get("query", "")
            return f"Siap, aku cari {query}." if query else "Siap, aku cari."

        elif intent == "notes.open":
            return "Siap, aku buka Notes."

        elif intent == "notes.take":
            return "Siap, aku catat."

        elif intent == "memory.remember":
            return "Siap, aku ingat."

        return result

    def _run_tool(self, tool_call: dict[str, Any]) -> str:
        name = tool_call.get("function", {}).get("name", "")
        self._latency_mark("tool_start", name=name)
        if self.on_pipeline_event:
            self.on_pipeline_event("tool", "started", {"name": name})
        try:
            result = self.registry.execute_call(tool_call)
        except Exception as exc:
            result = f"Tool '{name}' failed: {exc}"
        self._latency_mark("tool_done", name=name, ok=not result.startswith(f"Tool '{name}' failed:"))
        if self.on_pipeline_event:
            self.on_pipeline_event("tool", "completed", {"name": name, "result": result})
        if self.on_tool_executed:
            self.on_tool_executed(name, result)
        return result

    async def _run_tool_for_turn(
        self,
        turn: TurnContext,
        tool_call: dict[str, Any],
    ) -> tuple[str, float]:
        import time

        if not self._is_active_turn(turn):
            return "", 0.0

        name = tool_call.get("function", {}).get("name", "")
        self._latency_mark("tool_start", name=name)
        self._emit_pipeline_event_for_turn(turn, "tool", "started", {"name": name})
        start = time.time()

        async def execute() -> str:
            try:
                return await asyncio.to_thread(self.registry.execute_call, tool_call)
            except Exception as exc:
                return f"Tool '{name}' failed: {exc}"

        task = asyncio.create_task(execute())
        turn.tool_tasks.add(task)
        try:
            result = await task
        except asyncio.CancelledError:
            return "", time.time() - start
        finally:
            turn.tool_tasks.discard(task)

        duration = time.time() - start
        if not self._is_active_turn(turn):
            return result, duration

        self._latency_mark("tool_done", name=name, ok=not result.startswith(f"Tool '{name}' failed:"))
        self._emit_pipeline_event_for_turn(
            turn,
            "tool",
            "completed",
            {"name": name, "result": result},
        )
        self._emit_tool_executed_for_turn(turn, name, result)
        return result, duration

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

    async def speak_text_immediately(
        self,
        turn: TurnContext,
        text: str,
    ) -> None:
        if not self._is_active_turn(turn):
            return
        current_task = asyncio.current_task()
        if current_task is not None:
            turn.tts_task = current_task

        self._barge_in_requested = False
        self._barge_in_handled = False

        try:
            if not isinstance(self.tts, RealtimeTTSAdapter) or not hasattr(self.tts, "stream_pcm"):
                # Fallback to non-realtime play
                clean_text = self._clean_markdown_for_tts(text)
                if not clean_text:
                    return

                if self.state_machine.state == State.THINKING:
                    self._transition_for_turn(turn, self.state_machine.tts_ready)
                self._emit_pipeline_event_for_turn(turn, "tts", "started", {})

                self._latency_mark("tts_request_start", chars=len(clean_text))
                audio = await self.tts.synthesize(clean_text)
                interrupted = False
                if audio and self._is_active_turn(turn):
                    self._latency_mark("tts_first_audio", bytes=len(audio))
                    self._output_audio_bytes = audio
                    if self._play is not None:
                        if self.state_machine.state == State.PREPARING_AUDIO:
                            self._transition_for_turn(turn, self.state_machine.playback_started)
                        self._latency_mark("playback_start")
                        stop_event = threading.Event()
                        self._playback_stop_event = stop_event
                        turn.playback_stop_event = stop_event
                        try:
                            await asyncio.to_thread(self._play_audio_blocking, audio, stop_event, turn)
                        finally:
                            if self._playback_stop_event is stop_event:
                                self._playback_stop_event = None
                            if turn.playback_stop_event is stop_event:
                                turn.playback_stop_event = None
                        interrupted = stop_event.is_set()
                        self._latency_mark("playback_done", interrupted=interrupted)

                if interrupted:
                    self._finish_barge_in()
                    return

                self._emit_pipeline_event_for_turn(turn, "tts", "completed", {})
                if self.state_machine.state in (State.PREPARING_AUDIO, State.SPEAKING):
                    self._transition_for_turn(turn, self.state_machine.audio_done)
                return
        finally:
            if current_task is not None and turn.tts_task is current_task:
                turn.tts_task = None

        if current_task is not None:
            turn.tts_task = current_task
        player = StreamingPlayer(on_audio_level=lambda level: self._emit_audio_level_for_turn(turn, level))
        turn.playback = player

        if self.state_machine.state == State.THINKING:
            self._transition_for_turn(turn, self.state_machine.tts_ready)

        self._emit_pipeline_event_for_turn(turn, "tts", "started", {})

        stop_event = threading.Event()
        self._playback_stop_event = stop_event
        turn.playback_stop_event = stop_event

        playback_started = False

        try:
            clean_text = self._clean_markdown_for_tts(text)
            self._latency_mark("tts_request_start", chars=len(clean_text))
            async for pcm_chunk in self.tts.stream_pcm(clean_text):
                if not self._is_active_turn(turn) or stop_event.is_set():
                    break
                
                if self._output_audio_bytes is None:
                    self._latency_mark("tts_first_audio", bytes=len(pcm_chunk))

                if self._is_active_turn(turn):
                    await player.enqueue(pcm_chunk)
                
                if self._output_audio_bytes is None:
                    self._output_audio_bytes = pcm_chunk
                else:
                    self._output_audio_bytes += pcm_chunk

                if not playback_started:
                    playback_started = True
                    if self.state_machine.state == State.PREPARING_AUDIO:
                        self._transition_for_turn(turn, self.state_machine.playback_started)
                    self._latency_mark("playback_start")

            if self._is_active_turn(turn) and not stop_event.is_set():
                player.signal_end()
                await player.wait_drained()

        except Exception as exc:
            logger.exception("Error in speak_text_immediately")
            raise
        finally:
            if self._playback_stop_event is stop_event:
                self._playback_stop_event = None
            if turn.playback_stop_event is stop_event:
                turn.playback_stop_event = None
            player.close()
            if turn.playback is player:
                turn.playback = None
            if current_task is not None and turn.tts_task is current_task:
                turn.tts_task = None

            if not self._is_active_turn(turn) or stop_event.is_set():
                self._finish_barge_in()
            else:
                self._emit_pipeline_event_for_turn(turn, "tts", "completed", {})
                if self.state_machine.state in (State.PREPARING_AUDIO, State.SPEAKING):
                    self._transition_for_turn(turn, self.state_machine.audio_done)

    async def speak_streaming(
        self,
        turn: TurnContext,
        text_stream: AsyncIterator[str],
    ) -> None:
        if not self._is_active_turn(turn):
            return
        current_task = asyncio.current_task()
        if current_task is not None:
            turn.tts_task = current_task

        self._barge_in_requested = False
        self._barge_in_handled = False

        try:
            if not isinstance(self.tts, RealtimeTTSAdapter) or not hasattr(self.tts, "stream_pcm"):
                # Fallback to non-realtime play
                full_text = ""
                async for delta in text_stream:
                    if not self._is_active_turn(turn):
                        break
                    full_text += delta
                clean_text = self._clean_markdown_for_tts(full_text)
                if clean_text and self._is_active_turn(turn):
                    if self.state_machine.state == State.THINKING:
                        self._transition_for_turn(turn, self.state_machine.tts_ready)
                    self._emit_pipeline_event_for_turn(turn, "tts", "started", {})

                    self._latency_mark("tts_request_start", chars=len(clean_text))
                    audio = await self.tts.synthesize(clean_text)
                    interrupted = False
                    if audio and self._is_active_turn(turn):
                        self._latency_mark("tts_first_audio", bytes=len(audio))
                        self._output_audio_bytes = audio
                        if self._play is not None:
                            if self.state_machine.state == State.PREPARING_AUDIO:
                                self._transition_for_turn(turn, self.state_machine.playback_started)
                            self._latency_mark("playback_start")
                            stop_event = threading.Event()
                            self._playback_stop_event = stop_event
                            turn.playback_stop_event = stop_event
                            try:
                                await asyncio.to_thread(self._play_audio_blocking, audio, stop_event, turn)
                            finally:
                                if self._playback_stop_event is stop_event:
                                    self._playback_stop_event = None
                                if turn.playback_stop_event is stop_event:
                                    turn.playback_stop_event = None
                            interrupted = stop_event.is_set()
                            self._latency_mark("playback_done", interrupted=interrupted)

                    if interrupted:
                        self._finish_barge_in()
                        return

                    self._emit_pipeline_event_for_turn(turn, "tts", "completed", {})
                    if self.state_machine.state in (State.PREPARING_AUDIO, State.SPEAKING):
                        self._transition_for_turn(turn, self.state_machine.audio_done)
                return
        finally:
            if current_task is not None and turn.tts_task is current_task:
                turn.tts_task = None

        if current_task is not None:
            turn.tts_task = current_task
        player = StreamingPlayer(on_audio_level=lambda level: self._emit_audio_level_for_turn(turn, level))
        turn.playback = player

        if self.state_machine.state == State.THINKING:
            self._transition_for_turn(turn, self.state_machine.tts_ready)

        self._emit_pipeline_event_for_turn(turn, "tts", "started", {})

        stop_event = threading.Event()
        self._playback_stop_event = stop_event
        turn.playback_stop_event = stop_event

        segmenter = TextSegmenter()
        playback_started = False
        tts_request_started = False

        try:
            async for delta in text_stream:
                if not self._is_active_turn(turn) or stop_event.is_set():
                    break

                for segment in segmenter.push(delta):
                    if not self._is_active_turn(turn) or stop_event.is_set():
                        break
                    if not segment.strip():
                        continue

                    clean_segment = self._clean_markdown_for_tts(segment)
                    if not clean_segment.strip():
                        continue

                    if not tts_request_started:
                        self._latency_mark("tts_request_start", chars=len(clean_segment))
                        tts_request_started = True

                    async for pcm_chunk in self.tts.stream_pcm(clean_segment):
                        if not self._is_active_turn(turn) or stop_event.is_set():
                            break
                        
                        if self._output_audio_bytes is None:
                            self._latency_mark("tts_first_audio", bytes=len(pcm_chunk))

                        if self._is_active_turn(turn):
                            await player.enqueue(pcm_chunk)
                        
                        if self._output_audio_bytes is None:
                            self._output_audio_bytes = pcm_chunk
                        else:
                            self._output_audio_bytes += pcm_chunk

                        if not playback_started:
                            playback_started = True
                            if self.state_machine.state == State.PREPARING_AUDIO:
                                self._transition_for_turn(turn, self.state_machine.playback_started)
                            self._latency_mark("playback_start")

            # Flush any remaining segments
            if self._is_active_turn(turn) and not stop_event.is_set():
                for segment in segmenter.flush():
                    if not self._is_active_turn(turn) or stop_event.is_set():
                        break
                    if not segment.strip():
                        continue

                    clean_segment = self._clean_markdown_for_tts(segment)
                    if not clean_segment.strip():
                        continue

                    if not tts_request_started:
                        self._latency_mark("tts_request_start", chars=len(clean_segment))
                        tts_request_started = True

                    async for pcm_chunk in self.tts.stream_pcm(clean_segment):
                        if not self._is_active_turn(turn) or stop_event.is_set():
                            break
                        
                        if self._output_audio_bytes is None:
                            self._latency_mark("tts_first_audio", bytes=len(pcm_chunk))

                        if self._is_active_turn(turn):
                            await player.enqueue(pcm_chunk)
                        
                        if self._output_audio_bytes is None:
                            self._output_audio_bytes = pcm_chunk
                        else:
                            self._output_audio_bytes += pcm_chunk

                        if not playback_started:
                            playback_started = True
                            if self.state_machine.state == State.PREPARING_AUDIO:
                                self._transition_for_turn(turn, self.state_machine.playback_started)
                            self._latency_mark("playback_start")

            if self._is_active_turn(turn) and not stop_event.is_set():
                player.signal_end()
                await player.wait_drained()

        except Exception as exc:
            logger.exception("Error in speak_streaming")
            raise
        finally:
            if self._playback_stop_event is stop_event:
                self._playback_stop_event = None
            if turn.playback_stop_event is stop_event:
                turn.playback_stop_event = None
            player.close()
            if turn.playback is player:
                turn.playback = None
            if current_task is not None and turn.tts_task is current_task:
                turn.tts_task = None

            if not self._is_active_turn(turn) or stop_event.is_set():
                self._finish_barge_in()
            else:
                self._emit_pipeline_event_for_turn(turn, "tts", "completed", {})
                if self.state_machine.state in (State.PREPARING_AUDIO, State.SPEAKING):
                    self._transition_for_turn(turn, self.state_machine.audio_done)

    async def _speak(self, text: str) -> None:
        if self._current_turn is None:
            self._current_turn = TurnContext(id=self._current_turn_id or "turn_default")
        
        async def text_stream():
            yield text

        await self.speak_streaming(self._current_turn, text_stream())
        if self.conversation_mode_active:
            self.start_auto_listening()

    def _play_audio_blocking(
        self,
        audio: bytes,
        stop_event: threading.Event,
        turn: TurnContext | None = None,
    ) -> None:
        if self._play is None:
            return
        on_audio_level = (
            (lambda level: self._emit_audio_level_for_turn(turn, level))
            if turn is not None
            else self.on_audio_level
        )
        try:
            self._play(
                audio,
                on_audio_level=on_audio_level,
                stop_event=stop_event,
            )
        except TypeError:
            try:
                self._play(audio, on_audio_level=on_audio_level)
            except TypeError:
                self._play(audio)

    def request_barge_in(self) -> bool:
        cancellable_state = self.state_machine.state in (
            State.THINKING,
            State.PREPARING_AUDIO,
            State.SPEAKING,
        )
        if not cancellable_state and self._playback_stop_event is None and self._current_turn is None:
            return False

        return self.cancel_current_turn("barge_in")

    def cancel_current_turn(self, reason: str = "cancelled") -> bool:
        turn = self._current_turn
        if (
            turn is None
            and self._playback_stop_event is None
            and self.state_machine.state not in (State.THINKING, State.PREPARING_AUDIO, State.SPEAKING)
        ):
            return False

        if reason == "barge_in":
            self._latency_mark("barge_in_detected")
        self._latency_mark("cancel_start")
        self._latency_mark("turn_cancelled", reason=reason)
        self._latency_metadata(cancelled=True)
        self._barge_in_requested = True

        if self._playback_stop_event is not None:
            self._playback_stop_event.set()

        if turn is not None:
            turn.cancel(reason)

        if self.state_machine.state in (State.THINKING, State.PREPARING_AUDIO, State.SPEAKING):
            self.state_machine.force_idle()

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
        self._latency_mark("cancel_done")

        if self.on_pipeline_event:
            self.on_pipeline_event("tts", "interrupted", {})

        if self.state_machine.state in (State.PREPARING_AUDIO, State.SPEAKING):
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
            if now - self._last_speech_time >= self.config.vad.end_silence_ms / 1000:
                self._auto_listening = False
                if self._loop:
                    asyncio.run_coroutine_threadsafe(self._auto_respond(), self._loop)
        else:
            if now - self._auto_listen_start_real_time >= self.config.vad.followup_timeout_s:
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

        # Activate streaming STT and spawn the background task if configured
        partial_mode = getattr(self.config.stt, "partial_mode", "off")
        if partial_mode != "off":
            loop = asyncio.get_running_loop()
            self._streaming_stt_active = True
            self._streaming_stt_task = loop.create_task(self._run_streaming_stt_task())

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
                            self._latency_mark("vad_speech_start", detector="silero")
                            if self.on_pipeline_event:
                                self.on_pipeline_event("vad", "speech_started", {})
                        elif state == VADState.ENDED:
                            duration_ms = len(utterance_chunks or []) * VAD_FRAME_MS
                            stop_reason = "max_utterance" if duration_ms >= self.config.vad.max_utterance_ms else "silence"
                            self._latency_mark(
                                "vad_speech_end",
                                detector="silero",
                                stop_reason=stop_reason,
                                duration_ms=duration_ms,
                            )
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
                            self._latency_mark(
                                "vad_speech_start",
                                detector="rms",
                                rms_level=rms_level,
                                probability=prob,
                            )
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
                                self._latency_mark(
                                    "vad_speech_end",
                                    detector="rms",
                                    stop_reason=stop_reason,
                                    duration_ms=rms_duration_ms,
                                    voiced_ms=rms_voiced_ms,
                                )
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
                    # Cancel and await the streaming STT task before stopping the recorder
                    if self._streaming_stt_task is not None:
                        self._streaming_stt_active = False
                        self._streaming_stt_task.cancel()
                        try:
                            await self._streaming_stt_task
                        except asyncio.CancelledError:
                            pass
                        self._streaming_stt_task = None
                    self._cancel_vad_task()
                    print("Processing...")
                    await self._auto_respond_with_utterance(terminal_chunks)
                    break
                elif terminal_state is VADState.TIMEOUT:
                    self._auto_listening = False
                    if self._streaming_stt_task is not None:
                        self._streaming_stt_active = False
                        self._streaming_stt_task.cancel()
                        try:
                            await self._streaming_stt_task
                        except asyncio.CancelledError:
                            pass
                        self._streaming_stt_task = None
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
            self._latency_mark("audio_wav_ready", bytes=len(audio), source="vad")
            self._latency_metadata(audio_ms=_audio_duration_ms(audio))

            if _is_audio_too_short(audio):
                self.state_machine.audio_done()
                if self.conversation_mode_active:
                    self.start_auto_listening()
                return

            self.state_machine.hotkey_released()

            # If early local intent was executed from a stable partial transcript,
            # skip the full STT call and emit the final transcript directly.
            if self._early_intent_executed:
                self._latency_mark("stt_skipped_early_intent")
                partial_text = getattr(self, "_last_partial_text", "") or ""
                if partial_text:
                    self._emit_user_final_for_turn(self._current_turn, partial_text)
                if self.on_pipeline_event:
                    self.on_pipeline_event("stt", "skipped_early_intent", {})
                # Early intent already spoke a canned reply; return to listening
                if self.conversation_mode_active:
                    self.start_auto_listening()
                return

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
        # If the backend is currently THINKING/PREPARING_AUDIO/SPEAKING, let the turn complete naturally
        # so that window blur (e.g. from launching a browser) does not abort the response.
        if self.state_machine.state in (State.LISTENING, State.ERROR):
            self.state_machine.force_idle()

    def _on_state_changed(self, event: StateChangedEvent) -> None:
        # Browser sessions stay open across follow-up turns. Users can close the
        # Playwright context explicitly with browser_close.
        return


def _audio_duration_ms(audio: bytes) -> int | None:
    try:
        import io
        import soundfile as sf
        with sf.SoundFile(io.BytesIO(audio)) as f:
            return round((len(f) / f.samplerate) * 1000)
    except Exception:
        return None


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
    from verse.llm.gemini import GeminiAdapter
    from verse.stt.groq import GroqWhisperAdapter
    from verse.tools.registry import build_default_registry
    from verse.tts.macos_say import MacOSSayAdapter
    from verse.tts.edge_tts import EdgeTTSAdapter
    from verse.tts.gemini import GeminiTTSAdapter
    from verse.tts.google import GoogleTTSAdapter

    config = config or AppConfig()
    registry = build_default_registry(config.tools.enabled)

    if config.tts.provider == "edge-tts":
        tts = EdgeTTSAdapter(config.tts)
    elif config.tts.provider == "google":
        tts = GoogleTTSAdapter(config.tts)
    elif config.tts.provider == "gemini":
        tts = GeminiTTSAdapter(config.tts)
    else:
        tts = MacOSSayAdapter(config.tts)

    if config.llm.provider == "gemini":
        llm = GeminiAdapter(config.llm)
    else:
        llm = DeepSeekAdapter(config.llm)

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
        llm=llm,
        tts=tts,
        registry=registry,
        state_machine=StateMachine(),
        config=config,
        recorder=AudioRecorder(),
        play=play_audio,
        debug_logger=debug_logger,
        store=store,
    )
