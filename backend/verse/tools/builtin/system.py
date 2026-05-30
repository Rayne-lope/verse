from __future__ import annotations

import subprocess
from datetime import datetime


def open_app(app_name: str) -> str:
    name = app_name.strip()
    if not name:
        raise ValueError("app_name cannot be empty")
    
    aliases = {
        "brave": "Brave Browser",
        "brave browser": "Brave Browser",
        "chrome": "Google Chrome",
        "google chrome": "Google Chrome",
        "safari": "Safari",
        "vscode": "Visual Studio Code",
        "vs code": "Visual Studio Code",
        "visual studio code": "Visual Studio Code",
        "code": "Visual Studio Code",
        "spotify": "Spotify",
    }
    
    actual_name = aliases.get(name.lower(), name)
    subprocess.run(["open", "-a", actual_name], check=True)
    return f"Opened {actual_name}."


def get_time() -> str:
    now = datetime.now().astimezone()
    return now.strftime("It is %A, %d %B %Y, %H:%M.")
