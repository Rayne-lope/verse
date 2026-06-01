from __future__ import annotations

from enum import Enum
import re


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


def fast_intent_classifier(transcript: str) -> tuple[IntentCategory, float, bool]:
    """
    Classifies a transcript into an IntentCategory, confidence score, and
    whether this action requires user confirmation.
    """
    text = transcript.lower().strip()
    if not text:
        return IntentCategory.UNKNOWN, 0.0, False

    # Normalize text to extract keywords easily
    normalized = re.sub(r"[^\w\s]", " ", text)
    normalized = re.sub(r"\s+", " ", normalized).strip()

    # 1. Check for LOCAL_SYSTEM intents: time, volume, mute, brightness, dark mode, dnd, cancel
    system_keywords = (
        "jam berapa", "time is it", "tanggal", "cancel", "batal", "stop", "sudah",
        "volume", "suara", "mute", "unmute", "senyap", "hening", "brightness",
        "kecerahan", "layar", "dark mode", "light mode", "gelap", "terang", "dnd",
        "jangan ganggu", "do not disturb"
    )
    if any(k in normalized for k in system_keywords):
        return IntentCategory.LOCAL_SYSTEM, 0.95, False

    # 2. Check for MUSIC intents
    music_keywords = ("music", "musik", "lagu", "spotify", "putar", "mainkan", "pause", "resume", "jeda")
    if any(k in normalized for k in music_keywords):
        return IntentCategory.MUSIC, 0.92, False

    # Web-content actions take precedence over plain app launch. Phrases like
    # "buka wikipedia dan rangkum" or "buka brave dan cari mobil listrik" combine
    # an app verb with a web action — they must route to BROWSER (read/search/click
    # the page), not APP (which only exposes open_app/close_app to the LLM).
    web_action_keywords = (
        "cari", "search", "rangkum", "summarize", "ringkas", "baca", "read",
        "informasi", "info tentang", "berita", "fakta", "wikipedia", "wiki",
        "artikel", "klik", "click", "scroll", "isi form", "ketik di", "halaman",
    )
    # Guard: do not treat notes/calendar/reminder phrasing as a web action, so
    # "baca catatan" stays NOTES and "cari acara di kalender" stays CALENDAR.
    non_web_context = any(k in normalized for k in (
        "catat", "catatan", "note", "kalender", "calendar", "jadwal", "acara",
        "agenda", "reminder", "pengingat", "ingatkan",
    ))
    has_web_action = (not non_web_context) and any(k in normalized for k in web_action_keywords)

    # 3. Check for APP intents (avoiding browser navigation)
    app_keywords = ("open app", "buka aplikasi", "buka", "launch", "close app", "tutup aplikasi", "tutup")
    app_names = ("spotify", "vs code", "vscode", "visual studio code", "code", "brave", "chrome", "safari", "notes", "calendar", "reminders", "mail")
    if not has_web_action and (any(k in normalized for k in app_keywords) or any(app in normalized for app in app_names)):
        if not any(w in normalized for w in ("website", "http", "www", "url", "com", "org", "net", "id")):
            if any(action in normalized for action in ("buka", "tutup", "open", "close", "launch", "quit", "exit")):
                return IntentCategory.APP, 0.95, False

    # 4. Check for BROWSER / WEB SEARCH intents
    browser_keywords = ("google", "website", "navigate", "url", "cari di web", "search web", "browse", "kunjungi", "pergi ke")
    if has_web_action or any(k in normalized for k in browser_keywords) or any(tld in normalized.split() for tld in ("com", "org", "net", "id")):
        return IntentCategory.BROWSER, 0.90, False

    # 5. Check for CALENDAR intents
    calendar_keywords = ("calendar", "kalender", "jadwal", "meeting", "acara", "event", "janji")
    if any(k in normalized for k in calendar_keywords):
        requires_conf = any(action in normalized for action in ("buat", "create", "tambah", "add", "jadwalkan", "schedule"))
        return IntentCategory.CALENDAR, 0.88, requires_conf

    # 6. Check for NOTES intents
    notes_keywords = ("catat", "catatan", "tulis", "note")
    if any(k in normalized for k in notes_keywords):
        return IntentCategory.NOTES, 0.92, False

    # 7. Check for MEMORY intents
    memory_keywords = ("remember", "ingat", "memori")
    if any(k in normalized for k in memory_keywords):
        return IntentCategory.MEMORY, 0.95, False

    # 8. Check for MESSAGE / SMS / iMessage (which requires confirmation)
    msg_keywords = ("pesan", "kirim pesan", "message", "send message", "imessage", "sms")
    if any(k in normalized for k in msg_keywords):
        return IntentCategory.UNKNOWN, 0.95, True

    # 9. Check for Chat intents
    chat_keywords = ("halo", "hai", "apa kabar", "hello", "hi", "how are you", "siapa kamu", "who are you")
    if any(normalized == k or normalized.startswith(k + " ") for k in chat_keywords):
        return IntentCategory.CHAT, 0.95, False

    return IntentCategory.UNKNOWN, 0.5, False
