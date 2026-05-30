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


def get_volume() -> str:
    """Get the current macOS output volume level (0-100)."""
    from verse.tools.builtin.osa import run_applescript
    vol = run_applescript("output volume of (get volume settings)")
    return f"System volume is {vol}%."


def set_volume(level: int) -> str:
    """Set the macOS output volume level (0-100)."""
    from verse.tools.builtin.osa import run_applescript
    target = max(0, min(100, int(level)))
    run_applescript(f"set volume output volume {target}")
    return f"System volume set to {target}%."


def is_muted() -> str:
    """Check if the system volume is muted."""
    from verse.tools.builtin.osa import run_applescript
    muted = run_applescript("output muted of (get volume settings)")
    if muted == "true":
        return "System volume is currently muted."
    return "System volume is not muted."


def set_muted(muted: bool) -> str:
    """Mute or unmute the system volume."""
    from verse.tools.builtin.osa import run_applescript
    opt = "with" if muted else "without"
    run_applescript(f"set volume {opt} output muted")
    status = "muted" if muted else "unmuted"
    return f"System volume is now {status}."


def is_dark_mode() -> str:
    """Check if macOS dark appearance mode is enabled."""
    from verse.tools.builtin.osa import run_applescript
    res = run_applescript(
        'tell application "System Events" to tell appearance preferences to get dark mode'
    )
    if res == "true":
        return "Dark Mode is currently enabled."
    return "Dark Mode is disabled (Light Mode is enabled)."


def set_dark_mode(enabled: bool) -> str:
    """Enable or disable macOS dark appearance mode."""
    from verse.tools.builtin.osa import run_applescript
    val = "true" if enabled else "false"
    run_applescript(
        f'tell application "System Events" to tell appearance preferences to set dark mode to {val}'
    )
    mode = "Dark Mode" if enabled else "Light Mode"
    return f"Changed system appearance to {mode}."


def set_dnd(enabled: bool) -> str:
    """Enable or disable macOS Focus Mode (Do Not Disturb) via Shortcuts app."""
    from verse.tools.builtin.shortcuts import run_shortcut, list_shortcuts
    
    # Check if a Focus toggle shortcut exists or fall back to 'Toggle DND'
    shortcuts_str = list_shortcuts()
    
    # Parse shortcut names from the list
    names = []
    for line in shortcuts_str.splitlines():
        line = line.strip()
        if line.startswith("- "):
            names.append(line[2:].strip())
        elif line and not line.startswith("Your shortcuts:"):
            names.append(line)
            
    # Find case-insensitive match
    shortcut_name = None
    for name in names:
        lower_name = name.lower()
        if "toggle dnd" in lower_name:
            shortcut_name = name
            break
            
    if not shortcut_name:
        for name in names:
            lower_name = name.lower()
            if "dnd" in lower_name or "do not disturb" in lower_name or "focus" in lower_name:
                shortcut_name = name
                break
        
    if not shortcut_name:
        # Graceful fallback: instruct the user on how to set it up
        status = "enable" if enabled else "disable"
        return (
            f"I cannot {status} Do Not Disturb directly because macOS requires a custom shortcut. "
            "To enable this, please open your macOS Shortcuts app and create a new shortcut "
            "named 'Toggle DND' containing the single action 'Set Focus (Do Not Disturb)'. "
            "Once created, I will be able to toggle it for you perfectly!"
        )
        
    input_val = "On" if enabled else "Off"
    run_shortcut(shortcut_name, text_input=input_val)
    status = "enabled" if enabled else "disabled"
    return f"System Do Not Disturb is now {status}."


def get_brightness() -> str:
    """Get the current macOS screen brightness level (0-100)."""
    import ctypes
    try:
        cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        ds = ctypes.CDLL('/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices')
        display_id = cg.CGMainDisplayID()
        brightness = ctypes.c_float()
        ret = ds.DisplayServicesGetLinearBrightness(display_id, ctypes.byref(brightness))
        if ret == 0:
            level = int(round(brightness.value * 100))
            return f"Screen brightness is {level}%."
        return "Failed to read screen brightness from display services."
    except Exception as exc:
        return f"Failed to read screen brightness: {exc}"


def set_brightness(level: int) -> str:
    """Set the macOS screen brightness level (0-100)."""
    import ctypes
    try:
        target_pct = max(0, min(100, int(level)))
        target_val = float(target_pct) / 100.0
        cg = ctypes.CDLL('/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics')
        ds = ctypes.CDLL('/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices')
        display_id = cg.CGMainDisplayID()
        ds.DisplayServicesSetLinearBrightness.argtypes = [ctypes.c_uint32, ctypes.c_float]
        ret = ds.DisplayServicesSetLinearBrightness(display_id, target_val)
        if ret == 0:
            return f"Screen brightness set to {target_pct}%."
        return "Failed to set screen brightness in display services."
    except Exception as exc:
        return f"Failed to set screen brightness: {exc}"
