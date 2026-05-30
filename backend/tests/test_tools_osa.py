import subprocess

import pytest

from verse.tools.builtin import osa


def test_osa_quote_escapes_quotes_backslash_and_newlines():
    assert osa.osa_quote('say "hi"') == 'say \\"hi\\"'
    assert osa.osa_quote("a\\b") == "a\\\\b"
    assert osa.osa_quote("line1\nline2\r3") == "line1 line2 3"
    assert osa.osa_quote(None) == ""


def test_run_applescript_returns_stdout(monkeypatch):
    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="  ok  ", stderr="")

    monkeypatch.setattr(osa.subprocess, "run", fake_run)
    assert osa.run_applescript("tell app") == "ok"
    assert calls["argv"][:2] == ["osascript", "-e"]


def test_run_applescript_wraps_errors(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.CalledProcessError(1, argv, stderr="not authorized")

    monkeypatch.setattr(osa.subprocess, "run", fake_run)
    with pytest.raises(osa.AppleScriptError) as exc:
        osa.run_applescript("tell app")
    assert "not authorized" in str(exc.value)
