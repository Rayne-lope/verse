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
    }

    names = enabled if enabled is not None else list(catalog)
    registry = ToolRegistry()
    for name in names:
        tool = catalog.get(name)
        if tool is not None:
            registry.register(tool)
    return registry
