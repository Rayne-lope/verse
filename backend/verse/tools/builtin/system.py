from __future__ import annotations

import subprocess
from datetime import datetime


def open_app(app_name: str) -> str:
    name = app_name.strip()
    if not name:
        raise ValueError("app_name cannot be empty")
    subprocess.run(["open", "-a", name], check=True)
    return f"Opened {name}."


def get_time() -> str:
    now = datetime.now().astimezone()
    return now.strftime("It is %A, %d %B %Y, %H:%M.")
