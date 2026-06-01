from __future__ import annotations

from verse.intent.classifier import IntentCategory


class ToolSelector:
    """
    Selects a minimal subset of tools (0 to 5) from the registry based on
    the classified intent category and transcript keywords. This reduces
    the size of the LLM prompt and speeds up first-token response times.
    """

    def __init__(self, all_tools: list[str]) -> None:
        self.all_tools = all_tools

    def select(self, transcript: str, category: IntentCategory) -> list[str]:
        """
        Filters and returns at most 5 relevant tools for the given transcript and category.
        """
        text = transcript.lower().strip()
        selected: set[str] = set()

        # 1. Base tools on IntentCategory
        if category == IntentCategory.LOCAL_SYSTEM:
            selected.update([
                "set_volume", "get_volume", "set_muted",
                "set_dark_mode", "set_dnd", "set_brightness",
                "get_brightness", "get_time"
            ])
        elif category == IntentCategory.MUSIC:
            selected.update(["play_music", "pause_music"])
        elif category == IntentCategory.APP:
            selected.update(["open_app", "close_app"])
        elif category == IntentCategory.BROWSER:
            selected.update([
                "web_search", "open_url", "browser_navigate", "browser_inspect",
                "browser_click", "browser_input", "browser_scroll",
                "browser_go_back", "browser_close",
            ])
        elif category == IntentCategory.CALENDAR:
            selected.update(["read_calendar", "create_event"])
        elif category == IntentCategory.NOTES:
            selected.update(["take_note", "read_note", "list_notes"])
        elif category == IntentCategory.MEMORY:
            selected.update(["remember"])

        # 2. Add extra tools based on keyword scans
        if any(k in text for k in ("weather", "cuaca", "hujan", "suhu")):
            selected.add("get_weather")
        if any(k in text for k in ("shortcut", "singkasan")):
            selected.update(["run_shortcut", "list_shortcuts"])
        if any(k in text for k in ("reminder", "ingatkan", "pengingat", "tugas")):
            selected.update(["add_reminder", "read_reminders", "complete_reminder"])
        if any(k in text for k in ("contact", "kontak", "nomor", "telepon", "email")):
            selected.update(["find_contact", "send_message"])
        if any(k in text for k in ("message", "pesan", "chat", "sms")):
            selected.update(["send_message", "find_contact"])
        if any(k in text for k in ("note", "catat", "catatan", "tulis")):
            selected.update(["take_note", "read_note", "list_notes"])
        if any(k in text for k in ("calendar", "kalender", "jadwal", "meeting", "acara", "event")):
            selected.update(["read_calendar", "create_event"])
        if any(k in text for k in ("remember", "ingat", "memori")):
            selected.add("remember")
        if any(k in text for k in ("open", "launch", "buka", "tutup", "close", "quit", "jalankan")):
            selected.update(["open_app", "close_app"])
        if any(k in text for k in ("spotify", "music", "musik", "lagu", "putar", "jeda", "pause")):
            selected.update(["play_music", "pause_music"])
        if any(k in text for k in ("volume", "suara", "mute", "unmute")):
            selected.update(["set_volume", "get_volume", "set_muted"])
        if any(k in text for k in ("brightness", "kecerahan", "redup")):
            selected.update(["set_brightness", "get_brightness"])
        if any(k in text for k in ("browser", "chrome", "safari", "website", "cari di web", "google", "web")):
            selected.update([
                "web_search", "open_url", "browser_navigate", "browser_inspect",
                "browser_click", "browser_input", "browser_scroll",
                "browser_go_back", "browser_close",
            ])

        # Filter the selected set to tools that are actually enabled in the workspace
        enabled_selected = [t for t in self.all_tools if t in selected]

        # Cap the tool list to keep the LLM prompt small and first-token latency low.
        # Browser turns need their full toolset (navigate/inspect/click/input/scroll/
        # back/close) — inspect is mandatory for numeric-ID clicks — so they get a
        # higher cap than other categories.
        cap = 10 if category == IntentCategory.BROWSER else 5
        return enabled_selected[:cap]
