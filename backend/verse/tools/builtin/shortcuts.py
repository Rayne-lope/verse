from __future__ import annotations

import os
import subprocess
import tempfile


def list_shortcuts() -> str:
    """List the user's Apple Shortcuts (one per line) so they can be run by name."""
    try:
        result = subprocess.run(
            ["shortcuts", "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=15,
        )
    except FileNotFoundError:
        return "The 'shortcuts' command is unavailable (requires macOS Monterey or later)."
    except subprocess.CalledProcessError as exc:
        return f"Failed to list shortcuts: {(exc.stderr or '').strip()}"
    except subprocess.TimeoutExpired:
        return "Listing shortcuts timed out."

    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not names:
        return "You have no shortcuts saved in the Shortcuts app."
    return "Your shortcuts:\n" + "\n".join(f"- {name}" for name in names)


def run_shortcut(name: str, text_input: str | None = None) -> str:
    """Run an Apple Shortcut by name, optionally passing text input. Returns the
    shortcut's text output if any, otherwise a confirmation."""
    name = (name or "").strip()
    if not name:
        return "Shortcut name cannot be empty."

    input_path: str | None = None
    output_fd, output_path = tempfile.mkstemp(suffix=".out")
    os.close(output_fd)
    try:
        argv = ["shortcuts", "run", name]
        if text_input is not None and str(text_input).strip():
            in_fd, input_path = tempfile.mkstemp(suffix=".in")
            with os.fdopen(in_fd, "w", encoding="utf-8") as handle:
                handle.write(str(text_input))
            argv += ["--input-path", input_path]
        argv += ["--output-path", output_path]

        subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except FileNotFoundError:
        return "The 'shortcuts' command is unavailable (requires macOS Monterey or later)."
    except subprocess.CalledProcessError as exc:
        return (
            f"Failed to run shortcut '{name}': {(exc.stderr or '').strip()} "
            "(check the name with list_shortcuts)."
        )
    except subprocess.TimeoutExpired:
        return f"Shortcut '{name}' timed out."
    finally:
        if input_path and os.path.exists(input_path):
            os.unlink(input_path)

    try:
        with open(output_path, encoding="utf-8") as handle:
            output = handle.read().strip()
    except OSError:
        output = ""
    finally:
        if os.path.exists(output_path):
            os.unlink(output_path)

    if output:
        return f"Shortcut '{name}' output:\n{output}"
    return f"Ran shortcut '{name}'."