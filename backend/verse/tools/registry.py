from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

ToolHandler = Callable[..., str]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def list_definitions(
        self, enabled: list[str] | None = None
    ) -> list[dict[str, Any]]:
        if enabled is None:
            return [tool.definition() for tool in self._tools.values()]
        return [
            self._tools[name].definition()
            for name in enabled
            if name in self._tools
        ]

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> str:
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"Tool {name!r} is not registered")
        return tool.handler(**(arguments or {}))

    def execute_call(self, tool_call: dict[str, Any]) -> str:
        function = tool_call.get("function", {})
        name = function.get("name", "")
        raw_arguments = function.get("arguments")
        arguments = _parse_arguments(raw_arguments)
        return self.execute(name, arguments)


def _parse_arguments(raw_arguments: Any) -> dict[str, Any]:
    if raw_arguments is None or raw_arguments == "":
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    return json.loads(raw_arguments)


def build_default_registry(enabled: list[str] | None = None) -> ToolRegistry:
    from verse.tools.builtin import (
        beads,
        browser,
        calendar,
        contacts,
        memory,
        messages,
        notes,
        reminders,
        shortcuts,
        spotify,
        system,
        weather,
        web,
    )

    catalog: dict[str, Tool] = {
        # ── Beads / Workstation integration ──────────────────────────────────
        "get_workspace_context": Tool(
            name="get_workspace_context",
            description=(
                "Get the currently active project workspace (synced with Workstation app): "
                "project name, folder path, and a summary of issue counts by status. "
                "Call this first to understand which project the user is asking about."
            ),
            parameters={"type": "object", "properties": {}},
            handler=beads.get_workspace_context,
        ),
        "list_issues": Tool(
            name="list_issues",
            description=(
                "List issues in the active workspace. Optionally filter by status "
                "(open, in_progress, review, done) and/or type (task, bug, feature, epic)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["open", "in_progress", "review", "done"],
                        "description": "Filter by issue status.",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["task", "bug", "feature", "epic"],
                        "description": "Filter by issue type.",
                    },
                },
            },
            handler=beads.list_issues,
        ),
        "ready_issues": Tool(
            name="ready_issues",
            description=(
                "List issues that are ready to work on right now — all blockers resolved, "
                "status is open. Use this to recommend what to tackle next."
            ),
            parameters={"type": "object", "properties": {}},
            handler=beads.ready_issues,
        ),
        "show_issue": Tool(
            name="show_issue",
            description=(
                "Show the full details of a specific issue: description, status, priority, "
                "assignee, acceptance criteria, dependencies, and notes."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "The issue ID, e.g. 'verse-42'.",
                    }
                },
                "required": ["issue_id"],
            },
            handler=beads.show_issue,
        ),
        "search_issues": Tool(
            name="search_issues",
            description="Search issues by keyword across titles, descriptions, and notes.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search keyword or phrase.",
                    }
                },
                "required": ["query"],
            },
            handler=beads.search_issues,
        ),
        "create_issue": Tool(
            name="create_issue",
            description=(
                "Create a new issue in the active workspace. "
                "Use type='epic' for large initiatives, 'feature' for new capabilities, "
                "'task' for work items, 'bug' for defects. "
                "Priority: 0=critical, 1=high, 2=medium, 3=low, 4=backlog."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short summary of the issue (one line).",
                    },
                    "description": {
                        "type": "string",
                        "description": "Why this issue exists and what needs to be done.",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["task", "bug", "feature", "epic"],
                        "description": "Issue type (default: 'task').",
                    },
                    "priority": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 4,
                        "description": "Priority 0 (critical) to 4 (backlog). Default 2.",
                    },
                    "acceptance": {
                        "type": "string",
                        "description": "Optional acceptance criteria (what 'done' looks like).",
                    },
                    "notes": {
                        "type": "string",
                        "description": "Optional supplementary notes or context.",
                    },
                },
                "required": ["title", "description"],
            },
            handler=beads.create_issue,
        ),
        "add_dependency": Tool(
            name="add_dependency",
            description=(
                "Add a dependency between two issues: issue_id must be done AFTER depends_on_id. "
                "In other words, depends_on_id blocks issue_id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "The issue that depends on another (the child/blocked one).",
                    },
                    "depends_on_id": {
                        "type": "string",
                        "description": "The issue that must be completed first (the blocker).",
                    },
                },
                "required": ["issue_id", "depends_on_id"],
            },
            handler=beads.add_dependency,
        ),
        "close_issues": Tool(
            name="close_issues",
            description="Mark one or more issues as done.",
            parameters={
                "type": "object",
                "properties": {
                    "issue_ids": {
                        "type": "string",
                        "description": "Space-separated issue IDs, e.g. 'verse-12 verse-13'.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional reason or note for closing.",
                    },
                },
                "required": ["issue_ids"],
            },
            handler=beads.close_issues,
        ),
        "update_issue": Tool(
            name="update_issue",
            description=(
                "Update an existing issue: change its title, description, or notes, "
                "or mark it as in-progress (claim)."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "issue_id": {
                        "type": "string",
                        "description": "The issue ID to update.",
                    },
                    "title": {"type": "string", "description": "New title."},
                    "description": {"type": "string", "description": "New description."},
                    "notes": {"type": "string", "description": "Additional notes to set."},
                    "claim": {
                        "type": "boolean",
                        "description": "Set to true to mark the issue as in-progress.",
                    },
                },
                "required": ["issue_id"],
            },
            handler=beads.update_issue,
        ),
        # ── Music ─────────────────────────────────────────────────────────────
        "play_music": Tool(
            name="play_music",
            description=(
                "Play music on Spotify. Optionally search for a song, artist, "
                "playlist, or album first; otherwise resume the current track."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to play, e.g. 'jazz', 'Daft Punk', 'Lofi Chill'.",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["track", "playlist", "album", "artist"],
                        "description": "The type of Spotify content to play (default: 'track').",
                    }
                },
            },
            handler=spotify.play_music,
        ),
        "pause_music": Tool(
            name="pause_music",
            description="Pause Spotify playback.",
            parameters={"type": "object", "properties": {}},
            handler=spotify.pause_music,
        ),
        "set_spotify_volume": Tool(
            name="set_spotify_volume",
            description="Set Spotify's internal sound playback volume level.",
            parameters={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "The target volume level (0-100).",
                    }
                },
                "required": ["level"],
            },
            handler=spotify.set_spotify_volume,
        ),
        "get_spotify_volume": Tool(
            name="get_spotify_volume",
            description="Get the current internal volume level of Spotify (0-100).",
            parameters={"type": "object", "properties": {}},
            handler=spotify.get_spotify_volume,
        ),
        "skip_music": Tool(
            name="skip_music",
            description="Skip to the next or previous track on Spotify.",
            parameters={
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["next", "previous"],
                        "description": "The direction to skip, either 'next' or 'previous'.",
                    }
                },
                "required": ["direction"],
            },
            handler=spotify.skip_music,
        ),
        "get_now_playing": Tool(
            name="get_now_playing",
            description="Retrieve details about the song/track currently playing on Spotify.",
            parameters={"type": "object", "properties": {}},
            handler=spotify.get_now_playing,
        ),
        "remember": Tool(
            name="remember",
            description=(
                "Store a durable fact about the user for future conversations, e.g. "
                "when they say 'remember that ...' or share a lasting preference, "
                "name, or detail about themselves."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The fact to remember, as a short statement.",
                    }
                },
                "required": ["content"],
            },
            handler=memory.remember,
        ),
        "open_app": Tool(
            name="open_app",
            description="Open a macOS application by name, e.g. 'Safari', 'Notes'.",
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "The application name to open.",
                    }
                },
                "required": ["app_name"],
            },
            handler=system.open_app,
        ),
        "close_app": Tool(
            name="close_app",
            description="Quit a macOS application by name, e.g. 'Safari', 'Notes'.",
            parameters={
                "type": "object",
                "properties": {
                    "app_name": {
                        "type": "string",
                        "description": "The application name to quit.",
                    }
                },
                "required": ["app_name"],
            },
            handler=system.close_app,
        ),
        "get_time": Tool(
            name="get_time",
            description="Get the current local date and time.",
            parameters={"type": "object", "properties": {}},
            handler=system.get_time,
        ),
        "web_search": Tool(
            name="web_search",
            description="Search the web and return the top results.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query.",
                    }
                },
                "required": ["query"],
            },
            handler=web.web_search,
        ),
        "open_url": Tool(
            name="open_url",
            description="Open a URL in the default browser.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The full URL to open.",
                    }
                },
                "required": ["url"],
            },
            handler=web.open_url,
        ),
        "get_weather": Tool(
            name="get_weather",
            description="Get the current weather for a city name.",
            parameters={
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "The city name, e.g. 'Jakarta', 'New York'.",
                    }
                },
                "required": ["city"],
            },
            handler=weather.get_weather,
        ),
        "take_note": Tool(
            name="take_note",
            description="Save a quick note to a local file in ~/Verse/notes/.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The title of the note.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The markdown or text content of the note.",
                    },
                },
                "required": ["title", "content"],
            },
            handler=notes.take_note,
        ),
        "read_note": Tool(
            name="read_note",
            description="Read a saved note by title from ~/Verse/notes/.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The exact title of the note.",
                    }
                },
                "required": ["title"],
            },
            handler=notes.read_note,
        ),
        "list_notes": Tool(
            name="list_notes",
            description="List all saved notes in ~/Verse/notes/.",
            parameters={"type": "object", "properties": {}},
            handler=notes.list_notes,
        ),
        "read_calendar": Tool(
            name="read_calendar",
            description="Read macOS calendar events for a query like 'today', 'tomorrow', or 'YYYY-MM-DD'.",
            parameters={
                "type": "object",
                "properties": {
                    "date_query": {
                        "type": "string",
                        "description": "When to read the calendar for, e.g. 'today', 'tomorrow', or 'YYYY-MM-DD'.",
                    }
                },
            },
            handler=calendar.read_calendar,
        ),
        "read_reminders": Tool(
            name="read_reminders",
            description="Read incomplete reminders from macOS Reminders app.",
            parameters={"type": "object", "properties": {}},
            handler=reminders.read_reminders,
        ),
        "add_reminder": Tool(
            name="add_reminder",
            description="Add a reminder to macOS Reminders, with an optional due date/time and list.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The title of the reminder.",
                    },
                    "body": {
                        "type": "string",
                        "description": "Optional details or body description for the reminder.",
                    },
                    "due": {
                        "type": "string",
                        "description": "Optional due date/time, 'YYYY-MM-DD HH:MM' or 'YYYY-MM-DD'.",
                    },
                    "list_name": {
                        "type": "string",
                        "description": "Optional Reminders list name; defaults to the default list.",
                    },
                },
                "required": ["title"],
            },
            handler=reminders.add_reminder,
        ),
        "complete_reminder": Tool(
            name="complete_reminder",
            description="Mark a reminder as completed by its title.",
            parameters={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "The exact title of the reminder to complete.",
                    }
                },
                "required": ["title"],
            },
            handler=reminders.complete_reminder,
        ),
        "create_event": Tool(
            name="create_event",
            description=(
                "Create a macOS Calendar event. Date is 'today'/'tomorrow'/'YYYY-MM-DD', "
                "times are 'HH:MM'. Defaults to a 1-hour event on the first calendar."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title/summary."},
                    "date": {
                        "type": "string",
                        "description": "'today', 'tomorrow', or 'YYYY-MM-DD'.",
                    },
                    "start_time": {"type": "string", "description": "Start time 'HH:MM'."},
                    "end_time": {
                        "type": "string",
                        "description": "Optional end time 'HH:MM' (default +1 hour).",
                    },
                    "calendar_name": {
                        "type": "string",
                        "description": "Optional calendar name; defaults to the first calendar.",
                    },
                    "location": {"type": "string", "description": "Optional location."},
                    "notes": {"type": "string", "description": "Optional notes/description."},
                },
                "required": ["title", "date", "start_time"],
            },
            handler=calendar.create_event,
        ),
        "send_message": Tool(
            name="send_message",
            description=(
                "Send an iMessage to a contact name, phone number, or email. Always "
                "confirm the recipient and message with the user before sending."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "recipient": {
                        "type": "string",
                        "description": "Contact name, phone number, or email.",
                    },
                    "text": {"type": "string", "description": "The message body to send."},
                },
                "required": ["recipient", "text"],
            },
            handler=messages.send_message,
        ),
        "find_contact": Tool(
            name="find_contact",
            description="Look up a contact's phone number or email by name.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The contact name to look up."}
                },
                "required": ["name"],
            },
            handler=contacts.find_contact,
        ),
        "run_shortcut": Tool(
            name="run_shortcut",
            description=(
                "Run an Apple Shortcut by name (from the Shortcuts app), optionally "
                "passing text input. Use list_shortcuts to see available names."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The shortcut name to run."},
                    "text_input": {
                        "type": "string",
                        "description": "Optional text input to pass to the shortcut.",
                    },
                },
                "required": ["name"],
            },
            handler=shortcuts.run_shortcut,
        ),
        "list_shortcuts": Tool(
            name="list_shortcuts",
            description="List the user's Apple Shortcuts so they can be run by name.",
            parameters={"type": "object", "properties": {}},
            handler=shortcuts.list_shortcuts,
        ),
        "set_volume": Tool(
            name="set_volume",
            description="Set the macOS output volume level.",
            parameters={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "The volume level (0-100).",
                    }
                },
                "required": ["level"],
            },
            handler=system.set_volume,
        ),
        "get_volume": Tool(
            name="get_volume",
            description="Get the current macOS output volume level (0-100).",
            parameters={"type": "object", "properties": {}},
            handler=system.get_volume,
        ),
        "set_muted": Tool(
            name="set_muted",
            description="Mute or unmute the system volume.",
            parameters={
                "type": "object",
                "properties": {
                    "muted": {
                        "type": "boolean",
                        "description": "True to mute, False to unmute.",
                    }
                },
                "required": ["muted"],
            },
            handler=system.set_muted,
        ),
        "set_dark_mode": Tool(
            name="set_dark_mode",
            description="Enable or disable macOS Dark Mode appearance.",
            parameters={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "True for Dark Mode, False for Light Mode.",
                    }
                },
                "required": ["enabled"],
            },
            handler=system.set_dark_mode,
        ),
        "set_dnd": Tool(
            name="set_dnd",
            description="Enable or disable macOS Do Not Disturb (Focus Mode).",
            parameters={
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "True for Do Not Disturb enabled, False for disabled.",
                    }
                },
                "required": ["enabled"],
            },
            handler=system.set_dnd,
        ),
        "set_brightness": Tool(
            name="set_brightness",
            description="Set the macOS screen brightness level.",
            parameters={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "integer",
                        "description": "The brightness level (0-100).",
                    }
                },
                "required": ["level"],
            },
            handler=system.set_brightness,
        ),
        "get_brightness": Tool(
            name="get_brightness",
            description="Get the current macOS screen brightness level (0-100).",
            parameters={"type": "object", "properties": {}},
            handler=system.get_brightness,
        ),
        "browser_navigate": Tool(
            name="browser_navigate",
            description="Open a URL in the browser and read the page's visible text content.",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to navigate to, e.g. 'wikipedia.org' or 'google.com'.",
                    }
                },
                "required": ["url"],
            },
            handler=browser.browser_navigate,
        ),
        "browser_click": Tool(
            name="browser_click",
            description="Click an element (button, link, input) on the active page using a selector.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "The CSS selector or text value of the element to click, e.g. 'button.submit' or 'a.next'.",
                    }
                },
                "required": ["selector"],
            },
            handler=browser.browser_click,
        ),
        "browser_input": Tool(
            name="browser_input",
            description="Type text into an input field on the active page using a selector.",
            parameters={
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "The CSS selector of the input field, e.g. 'input#search'.",
                    },
                    "text": {
                        "type": "string",
                        "description": "The text content to enter into the field.",
                    }
                },
                "required": ["selector", "text"],
            },
            handler=browser.browser_input,
        ),
        "browser_close": Tool(
            name="browser_close",
            description="Close the active browser session to clean up system processes.",
            parameters={"type": "object", "properties": {}},
            handler=browser.browser_close,
        ),
        "browser_inspect": Tool(
            name="browser_inspect",
            description="Inspect the current page to assign visual numeric badges to all interactive elements and return a summary of elements.",
            parameters={"type": "object", "properties": {}},
            handler=browser.browser_inspect,
        ),
        "browser_scroll": Tool(
            name="browser_scroll",
            description="Scroll the current page in the specified direction ('up', 'down', 'top', 'bottom').",
            parameters={
                "type": "object",
                "properties": {
                    "direction": {
                        "type": "string",
                        "enum": ["up", "down", "top", "bottom"],
                        "description": "The direction to scroll.",
                    },
                    "amount": {
                        "type": "string",
                        "description": "Optional scroll amount: 'window', 'half', or a pixel number. Default is 'window'.",
                    },
                },
                "required": ["direction"],
            },
            handler=browser.browser_scroll,
        ),
        "browser_go_back": Tool(
            name="browser_go_back",
            description="Navigate back one step in the browser's history.",
            parameters={"type": "object", "properties": {}},
            handler=browser.browser_go_back,
        ),
    }

    names = enabled if enabled is not None else list(catalog)
    registry = ToolRegistry()
    for name in names:
        tool = catalog.get(name)
        if tool is not None:
            registry.register(tool)
    return registry
