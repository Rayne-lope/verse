from __future__ import annotations

from verse.tools.builtin.osa import AppleScriptError, osa_quote, run_applescript


def _looks_like_handle(value: str) -> bool:
    """True if the value is already a phone number or email (no lookup needed)."""
    value = value.strip()
    if "@" in value:
        return True
    digits = [c for c in value if c.isdigit()]
    return len(digits) >= 6


def lookup_contact(name: str) -> str | None:
    """Resolve a contact name to a messaging handle (mobile phone or email).
    Returns the handle string, or None if not found. Handles are returned as-is."""
    name = (name or "").strip()
    if not name:
        return None
    if _looks_like_handle(name):
        return name

    script = f'''
    set out to ""
    tell application "Contacts"
        set people_found to (every person whose name contains "{osa_quote(name)}")
        if (count of people_found) > 0 then
            set p to item 1 of people_found
            if (count of phones of p) > 0 then
                set out to value of item 1 of phones of p
            else if (count of emails of p) > 0 then
                set out to value of item 1 of emails of p
            end if
        end if
    end tell
    return out
    '''
    try:
        handle = run_applescript(script)
    except AppleScriptError:
        return None
    return handle or None


def find_contact(name: str) -> str:
    """Tool wrapper: look up a contact's messaging handle by name."""
    handle = lookup_contact(name)
    if handle is None:
        return f"No contact found matching '{name}'."
    return f"{name}: {handle}"
