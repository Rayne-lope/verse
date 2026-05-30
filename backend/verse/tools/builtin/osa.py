from __future__ import annotations

import subprocess


class AppleScriptError(RuntimeError):
    """Raised when an osascript invocation fails."""


def osa_quote(value: str) -> str:
    """Escape a Python string for safe embedding inside an AppleScript string literal.

    AppleScript string literals are delimited by double quotes and cannot contain a
    raw newline, so we escape backslashes and quotes and flatten newlines to spaces.
    Callers wrap the result in quotes themselves, e.g. f'... "{osa_quote(x)}" ...'.
    """
    if value is None:
        return ""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return text.replace("\r", " ").replace("\n", " ")


def run_applescript(script: str, *, timeout: float = 20.0) -> str:
    """Run an AppleScript via osascript and return its trimmed stdout.

    Raises AppleScriptError with a readable message on failure (often a missing
    Automation/TCC permission the user must grant on first use).
    """
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AppleScriptError(f"AppleScript timed out after {timeout}s") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise AppleScriptError(
            f"AppleScript failed (a macOS permission may be required): {stderr}"
        ) from exc
    return result.stdout.strip()
