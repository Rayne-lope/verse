from __future__ import annotations

import os
from pathlib import Path

NOTES_DIR = Path("~/Verse/notes/").expanduser()


def take_note(title: str, content: str) -> str:
    """Save a quick note to a local file in ~/Verse/notes/."""
    if not title.strip():
        return "Note title cannot be empty."

    # Sanitize title to prevent path traversal
    safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    if not safe_title:
        return "Invalid note title."

    try:
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        note_file = NOTES_DIR / f"{safe_title}.md"
        note_file.write_text(content, encoding="utf-8")
        return f"Successfully saved note '{safe_title}' to {note_file}."
    except Exception as exc:
        return f"Failed to save note: {exc}"


def read_note(title: str) -> str:
    """Read a saved note by title from ~/Verse/notes/."""
    safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_")).strip()
    note_file = NOTES_DIR / f"{safe_title}.md"

    if not note_file.exists():
        return f"Note '{safe_title}' does not exist."

    try:
        content = note_file.read_text(encoding="utf-8")
        return f"Note '{safe_title}':\n\n{content}"
    except Exception as exc:
        return f"Failed to read note: {exc}"


def list_notes() -> str:
    """List all saved notes in ~/Verse/notes/."""
    if not NOTES_DIR.exists():
        return "No notes found (notes directory does not exist)."

    try:
        files = [f.stem for f in NOTES_DIR.glob("*.md")]
        if not files:
            return "No notes found in your notes directory."
        return "Your saved notes:\n" + "\n".join(f"- {name}" for name in sorted(files))
    except Exception as exc:
        return f"Failed to list notes: {exc}"
