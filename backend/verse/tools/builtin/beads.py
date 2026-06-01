"""Beads issue-tracker tools for Verse.

Verse reads the active workspace from Workstation's preferences so it shares
context with whatever project the user has open.  All ``bd`` commands run in
that workspace directory.
"""

from __future__ import annotations

import json
import logging
import os
import plistlib
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Workstation preference keys ─────────────────────────────────────────────
_WORKSTATION_PLIST = (
    Path.home() / "Library/Preferences/local.beads.workstation.plist"
)
_PREFS_KEY = "com.beads.app.preferences"

# Homebrew PATH prefix so ``bd`` is found even when Verse starts without a
# full shell environment.
_HOMEBREW_BIN = "/opt/homebrew/bin"


# ── Workspace detection ──────────────────────────────────────────────────────

def _get_workspace_path() -> str:
    """Return the path of the workspace currently open in Workstation.

    Reads ``lastSelectedPath`` from Workstation's UserDefaults plist.
    Falls back to the verse project directory when the plist is absent.
    """
    try:
        with open(_WORKSTATION_PLIST, "rb") as fh:
            prefs = plistlib.load(fh)
        raw = prefs.get(_PREFS_KEY, "{}")
        data: dict = json.loads(raw)
        path = data.get("lastSelectedPath", "")
        if path and Path(path).exists():
            return path
    except Exception as exc:
        logger.debug("Could not read Workstation prefs: %s", exc)

    # Fallback: directory where the verse backend lives
    return str(Path(__file__).resolve().parents[4])


def _bd_env() -> dict[str, str]:
    env = os.environ.copy()
    if _HOMEBREW_BIN not in env.get("PATH", ""):
        env["PATH"] = _HOMEBREW_BIN + ":" + env.get("PATH", "")
    return env


def _run_bd(*args: str, workspace: str | None = None) -> str:
    """Run a ``bd`` subcommand inside *workspace* and return its output."""
    cwd = workspace or _get_workspace_path()
    try:
        result = subprocess.run(
            ["bd", *args],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=20,
            env=_bd_env(),
        )
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.returncode != 0:
            return f"Error: {err or out or 'bd command failed'}"
        return out or "(no output)"
    except FileNotFoundError:
        return "Error: 'bd' not found. Install beads via Homebrew."
    except subprocess.TimeoutExpired:
        return "Error: bd command timed out after 20 seconds."
    except Exception as exc:  # noqa: BLE001
        return f"Error: {exc}"


# ── Tool functions ───────────────────────────────────────────────────────────

def get_workspace_context() -> str:
    """Return the currently active project name, path, and a stats summary."""
    workspace = _get_workspace_path()
    project_name = Path(workspace).name
    stats = _run_bd("stats", workspace=workspace)
    return (
        f"Active workspace: {project_name}\n"
        f"Path: {workspace}\n\n"
        f"{stats}"
    )


def list_issues(status: str | None = None, type: str | None = None) -> str:
    """List issues, optionally filtered by status and/or type."""
    args: list[str] = ["list", "--json"]
    if status:
        args.append(f"--status={status}")
    if type:
        args.append(f"--type={type}")
    return _run_bd(*args)


def ready_issues() -> str:
    """List issues that are ready to work on (no unresolved blockers)."""
    return _run_bd("ready", "--json")


def show_issue(issue_id: str) -> str:
    """Show full details of a single issue including blockers and dependencies."""
    return _run_bd("show", issue_id)


def search_issues(query: str) -> str:
    """Search issues by keyword across titles, descriptions, and notes."""
    return _run_bd("search", query)


def create_issue(
    title: str,
    description: str,
    type: str = "task",
    priority: int = 2,
    acceptance: str | None = None,
    notes: str | None = None,
) -> str:
    """Create a new issue.

    *type* can be task | bug | feature | epic.
    *priority* is 0 (critical) – 4 (backlog); default 2 (medium).
    """
    args = [
        "create",
        f"--title={title}",
        f"--description={description}",
        f"--type={type}",
        f"--priority={priority}",
    ]
    if acceptance:
        args.append(f"--acceptance={acceptance}")
    if notes:
        args.append(f"--notes={notes}")
    return _run_bd(*args)


def add_dependency(issue_id: str, depends_on_id: str) -> str:
    """Mark *issue_id* as depending on *depends_on_id* (depends_on_id blocks issue_id)."""
    return _run_bd("dep", "add", issue_id, depends_on_id)


def close_issues(issue_ids: str, reason: str | None = None) -> str:
    """Close one or more issues.

    *issue_ids* is a space-separated list of IDs, e.g. ``"verse-12 verse-13"``.
    """
    ids = issue_ids.strip().split()
    if not ids:
        return "Error: no issue IDs provided."
    args = ["close"] + ids
    if reason:
        args.append(f"--reason={reason}")
    return _run_bd(*args)


def update_issue(
    issue_id: str,
    title: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    claim: bool = False,
) -> str:
    """Update an existing issue's fields or claim it as in-progress."""
    args = ["update", issue_id]
    if title:
        args.append(f"--title={title}")
    if description:
        args.append(f"--description={description}")
    if notes:
        args.append(f"--notes={notes}")
    if claim:
        args.append("--claim")
    return _run_bd(*args)
