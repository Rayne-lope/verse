from __future__ import annotations

import datetime
import subprocess

from verse.tools.builtin.osa import AppleScriptError, osa_quote, run_applescript


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


def add_reminder(
    title: str,
    body: str = "",
    due: str | None = None,
    list_name: str | None = None,
) -> str:
    """Add a reminder. Optionally set a due date/time ('YYYY-MM-DD HH:MM' or
    'YYYY-MM-DD') and a target list (defaults to the default list)."""
    if not title.strip():
        return "Reminder title cannot be empty."

    props = [f'name:"{osa_quote(title)}"']
    if body and body.strip():
        props.append(f'body:"{osa_quote(body)}"')

    due_block = ""
    if due and due.strip():
        parsed = _parse_due(due.strip())
        if parsed is None:
            return f"Invalid due date '{due}' (use 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM')."
        due_block = f"""
        set due_d to current date
        set year of due_d to {parsed.year}
        set month of due_d to {parsed.month}
        set day of due_d to {parsed.day}
        set hours of due_d to {parsed.hour}
        set minutes of due_d to {parsed.minute}
        set seconds of due_d to 0
        """
        props.append("due date:due_d")

    target_list = (
        f'list "{osa_quote(list_name)}"' if list_name and list_name.strip()
        else "default list"
    )
    props_str = ", ".join(props)
    script = f"""
    tell application "Reminders"
        {due_block}
        make new reminder at {target_list} with properties {{{props_str}}}
    end tell
    """
    try:
        run_applescript(script)
    except AppleScriptError as exc:
        return f"Failed to add reminder: {exc}"
    where = f"'{list_name}'" if list_name and list_name.strip() else "your default list"
    when = f" (due {due.strip()})" if due and due.strip() else ""
    return f"Added reminder '{title}' to {where}{when}."


def complete_reminder(title: str) -> str:
    """Mark the first matching incomplete reminder (by name) as completed."""
    if not title.strip():
        return "Reminder title cannot be empty."
    script = f"""
    tell application "Reminders"
        set matches to (reminders whose name is "{osa_quote(title)}" and completed is false)
        if (count of matches) is 0 then
            return "none"
        end if
        set completed of (item 1 of matches) to true
        return "done"
    end tell
    """
    try:
        result = run_applescript(script)
    except AppleScriptError as exc:
        return f"Failed to complete reminder: {exc}"
    if result == "none":
        return f"No incomplete reminder named '{title}' was found."
    return f"Marked reminder '{title}' as completed."


def _parse_due(value: str) -> datetime.datetime | None:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
