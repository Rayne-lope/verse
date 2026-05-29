from __future__ import annotations

import datetime
import subprocess


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
                set start_t to time string of (start date of anEvt)
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
