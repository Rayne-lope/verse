import datetime
import subprocess

from verse.tools.builtin import calendar, contacts, messages, osa, reminders, system


def _patch_osa(monkeypatch, stdout=""):
    """Patch osa.subprocess.run; record the AppleScript passed to osascript."""
    scripts = []

    def fake_run(argv, **kwargs):
        # argv == ["osascript", "-e", <script>]
        scripts.append(argv[2])
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(osa.subprocess, "run", fake_run)
    return scripts


# --- Calendar ----------------------------------------------------------------
def test_create_event_builds_script_with_escaped_fields(monkeypatch):
    scripts = _patch_osa(monkeypatch)
    result = calendar.create_event(
        title='Rapat "Q3"',
        date="2026-06-01",
        start_time="15:00",
        location="Zoom",
    )
    script = scripts[-1]
    assert 'summary:"Rapat \\"Q3\\""' in script
    assert "set year of start_d to 2026" in script
    assert "set hours of start_d to 15" in script
    assert "set hours of end_d to 16" in script  # default +1h
    assert 'location:"Zoom"' in script
    assert "Created event" in result


def test_create_event_rejects_bad_time(monkeypatch):
    _patch_osa(monkeypatch)
    assert "Invalid start time" in calendar.create_event("X", "today", "nope")


# --- Reminders ---------------------------------------------------------------
def test_add_reminder_with_due_and_list(monkeypatch):
    scripts = _patch_osa(monkeypatch)
    result = reminders.add_reminder(
        "Beli susu", due="2026-06-01 08:00", list_name="Belanja"
    )
    script = scripts[-1]
    assert 'name:"Beli susu"' in script
    assert "due date:due_d" in script
    assert "set hours of due_d to 8" in script
    assert 'list "Belanja"' in script
    assert "Belanja" in result


def test_add_reminder_invalid_due(monkeypatch):
    _patch_osa(monkeypatch)
    assert "Invalid due" in reminders.add_reminder("X", due="besok pagi")


def test_complete_reminder_found(monkeypatch):
    _patch_osa(monkeypatch, stdout="done")
    assert "completed" in reminders.complete_reminder("Beli susu").lower()


def test_complete_reminder_not_found(monkeypatch):
    _patch_osa(monkeypatch, stdout="none")
    assert "No incomplete reminder" in reminders.complete_reminder("Ghost")


# --- Contacts & Messages -----------------------------------------------------
def test_lookup_contact_returns_handle_directly_for_phone():
    # A phone-like string is treated as a handle without touching Contacts.
    assert contacts.lookup_contact("+62 812-3456-7890") == "+62 812-3456-7890"


def test_lookup_contact_resolves_name(monkeypatch):
    _patch_osa(monkeypatch, stdout="rayne@example.com")
    assert contacts.lookup_contact("Rayne") == "rayne@example.com"


def test_lookup_contact_none_when_empty(monkeypatch):
    _patch_osa(monkeypatch, stdout="")
    assert contacts.lookup_contact("Nobody") is None


def test_send_message_to_phone_builds_script(monkeypatch):
    scripts = _patch_osa(monkeypatch)
    result = messages.send_message("555-123-4567", 'hello "world"')
    script = scripts[-1]
    assert 'participant "555-123-4567"' in script
    assert 'send "hello \\"world\\""' in script
    assert "Sent message" in result


def test_send_message_unknown_recipient(monkeypatch):
    _patch_osa(monkeypatch, stdout="")  # contacts lookup returns nothing
    assert "Couldn't find" in messages.send_message("Ghosty McGhost", "hi")


def test_send_message_requires_text():
    assert "empty" in messages.send_message("555-123-4567", "").lower()


def test_close_app_builds_quit_script(monkeypatch):
    scripts = _patch_osa(monkeypatch)

    result = system.close_app("chrome")

    assert 'tell application "Google Chrome" to quit' in scripts[-1]
    assert result == "Closed Google Chrome."
