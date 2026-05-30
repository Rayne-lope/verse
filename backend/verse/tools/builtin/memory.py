from __future__ import annotations

from verse.persistence.db import default_store


def remember(content: str) -> str:
    """Explicitly store a durable fact about the user (e.g. when they say
    "remember that ..."). Complements automatic background extraction; stored
    with higher salience so it ranks above auto-derived facts."""
    content = (content or "").strip()
    if not content:
        return "There's nothing to remember."
    try:
        default_store().upsert_memory(content, salience=2.0)
        return f"Got it — I'll remember that: {content}"
    except Exception as exc:  # pragma: no cover - defensive
        return f"Failed to remember that: {exc}"
