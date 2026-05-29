from __future__ import annotations

import subprocess


def read_reminders() -> str:
    """Read incomplete reminders from macOS Reminders app."""
    script = """
    set reminderList to {}
    tell application "Reminders"
        repeat with aList in lists
            repeat with aReminder in (reminders of aList whose completed is false)
                copy (name of aReminder & " (list: " & name of aList & ")") to end of reminderList
            end repeat
        end repeat
    end tell
    return reminderList
    """
    try:
        res = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        output = res.stdout.strip()
        if not output:
            return "No incomplete reminders found."
        return "Your incomplete reminders:\n" + "\n".join(
            f"- {rem.strip()}" for rem in output.split(",")
        )
    except subprocess.CalledProcessError as exc:
        return f"Failed to retrieve reminders: Reminders app permission might be required. {exc.stderr.strip()}"
    except Exception as exc:
        return f"Failed to retrieve reminders: {exc}"


def add_reminder(title: str, body: str = "") -> str:
    """Add a new reminder to the default list in macOS Reminders app."""
    if not title.strip():
        return "Reminder title cannot be empty."

    # Escape quotes for AppleScript
    safe_title = title.replace('"', '\\"')
    safe_body = body.replace('"', '\\"')

    script = f"""
    tell application "Reminders"
        set defaultList to default list
        make new reminder at defaultList with properties {{name:"{safe_title}", body:"{safe_body}"}}
    end tell
    """
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return f"Successfully added reminder '{title}' to your default list."
    except subprocess.CalledProcessError as exc:
        return f"Failed to add reminder: Reminders app permission might be required. {exc.stderr.strip()}"
    except Exception as exc:
        return f"Failed to add reminder: {exc}"
