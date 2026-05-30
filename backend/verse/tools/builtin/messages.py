from __future__ import annotations

from verse.tools.builtin.contacts import lookup_contact
from verse.tools.builtin.osa import AppleScriptError, osa_quote, run_applescript


def send_message(recipient: str, text: str) -> str:
    """Send an iMessage. `recipient` may be a phone number, email, or a contact
    name (resolved via Contacts). Confirm with the user before calling this."""
    recipient = (recipient or "").strip()
    text = (text or "").strip()
    if not recipient:
        return "Recipient cannot be empty."
    if not text:
        return "Message text cannot be empty."

    handle = lookup_contact(recipient)
    if handle is None:
        return f"Couldn't find a contact or handle for '{recipient}'."

    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{osa_quote(handle)}" of targetService
        send "{osa_quote(text)}" to targetBuddy
    end tell
    '''
    try:
        run_applescript(script)
    except AppleScriptError as exc:
        return f"Failed to send message to {recipient}: {exc}"
    return f"Sent message to {recipient}: {text}"
