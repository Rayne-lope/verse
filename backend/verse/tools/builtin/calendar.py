from __future__ import annotations

import datetime
import subprocess

from verse.tools.builtin.osa import AppleScriptError, osa_quote, run_applescript


def _resolve_date(query: str) -> datetime.date:
    """Map 'today' / 'tomorrow' / 'YYYY-MM-DD' to a date (defaults to today)."""
    query = (query or "today").lower().strip()
    target = datetime.date.today()
    if query == "tomorrow":
        target += datetime.timedelta(days=1)
    elif query not in ("today", ""):
        try:
            target = datetime.datetime.strptime(query, "%Y-%m-%d").date()
        except ValueError:
            pass
    return target


def create_event(
    title: str,
    date: str = "today",
    start_time: str = "09:00",
    end_time: str | None = None,
    calendar_name: str | None = None,
    location: str = "",
    notes: str = "",
) -> str:
    """Create a Calendar event. `date` is today/tomorrow/YYYY-MM-DD, times are HH:MM.
    Defaults to a 1-hour event on the first calendar if none specified."""
    if not (title or "").strip():
        return "Event title cannot be empty."

    target = _resolve_date(date)
    try:
        sh, sm = (int(p) for p in start_time.strip().split(":", 1))
    except (ValueError, AttributeError):
        return f"Invalid start time '{start_time}' (use HH:MM)."

    start_dt = datetime.datetime(target.year, target.month, target.day, sh, sm)
    if end_time and end_time.strip():
        try:
            eh, em = (int(p) for p in end_time.strip().split(":", 1))
            end_dt = datetime.datetime(target.year, target.month, target.day, eh, em)
        except ValueError:
            return f"Invalid end time '{end_time}' (use HH:MM)."
    else:
        end_dt = start_dt + datetime.timedelta(hours=1)

    cal_selector = (
        f'calendar "{osa_quote(calendar_name)}"' if calendar_name and calendar_name.strip()
        else "calendar 1"
    )
    props = [f'summary:"{osa_quote(title)}"', "start date:start_d", "end date:end_d"]
    if location and location.strip():
        props.append(f'location:"{osa_quote(location)}"')
    if notes and notes.strip():
        props.append(f'description:"{osa_quote(notes)}"')
    props_str = ", ".join(props)

    script = f'''
    set start_d to current date
    set year of start_d to {start_dt.year}
    set month of start_d to {start_dt.month}
    set day of start_d to {start_dt.day}
    set hours of start_d to {start_dt.hour}
    set minutes of start_d to {start_dt.minute}
    set seconds of start_d to 0
    set end_d to current date
    set year of end_d to {end_dt.year}
    set month of end_d to {end_dt.month}
    set day of end_d to {end_dt.day}
    set hours of end_d to {end_dt.hour}
    set minutes of end_d to {end_dt.minute}
    set seconds of end_d to 0
    tell application "Calendar"
        tell {cal_selector}
            make new event at end of events with properties {{{props_str}}}
        end tell
    end tell
    '''
    try:
        run_applescript(script)
    except AppleScriptError as exc:
        return f"Failed to create event: {exc}"
    when = start_dt.strftime("%A, %B %d at %H:%M")
    return f"Created event '{title}' on {when}."


def read_calendar(date_query: str = "today") -> str:
    """Read macOS calendar events for a query, e.g., 'today', 'tomorrow', or 'YYYY-MM-DD'."""
    query = date_query.lower().strip()
    target_date = datetime.date.today()

    if query == "tomorrow":
        target_date += datetime.timedelta(days=1)
    elif query != "today":
        # Try to parse YYYY-MM-DD
        try:
            target_date = datetime.datetime.strptime(query, "%Y-%m-%d").date()
        except ValueError:
            # Fallback to today but log query
            pass

    year = target_date.year
    month = target_date.month
    day = target_date.day

    # AppleScript to fetch events starting on target_date and ending next day
    script = f"""
    set start_d to current date
    set year of start_d to {year}
    set month of start_d to {month}
    set day of start_d to {day}
    set hours of start_d to 0
    set minutes of start_d to 0
    set seconds of start_d to 0

    set end_d to start_d + (24 * 60 * 60)

    set eventList to {{}}
    tell application "Calendar"
        repeat with aCal in calendars
            repeat with anEvt in (events of aCal whose (start date is greater than or equal to start_d and start date is less than end_d) or (end date is greater than start_d and start date is less than start_d))
                set sd to start date of anEvt
                tell me to set start_t to time string of sd
                copy (summary of anEvt & " (" & start_t & ")") to end of eventList
            end repeat
        end repeat
    end tell
    return eventList
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
            return f"No calendar events scheduled for {target_date.strftime('%A, %B %d, %Y')}."
        return f"Calendar events for {target_date.strftime('%A, %B %d, %Y')}:\n" + "\n".join(
            f"- {evt.strip()}" for evt in output.split(",")
        )
    except subprocess.CalledProcessError as exc:
        return f"Failed to retrieve calendar: Calendar app permission might be required. {exc.stderr.strip()}"
    except Exception as exc:
        return f"Failed to retrieve calendar: {exc}"
