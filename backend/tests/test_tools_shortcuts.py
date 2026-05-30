import subprocess

from verse.tools.builtin import shortcuts


def test_list_shortcuts_parses_lines(monkeypatch):
    def fake_run(argv, **kwargs):
        assert argv == ["shortcuts", "list"]
        return subprocess.CompletedProcess(argv, 0, stdout="Mode Fokus\nKirim Lokasi\n", stderr="")

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    out = shortcuts.list_shortcuts()
    assert "- Mode Fokus" in out
    assert "- Kirim Lokasi" in out


def test_run_shortcut_builds_argv_and_confirms(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    result = shortcuts.run_shortcut("Mode Fokus")
    assert captured["argv"][:3] == ["shortcuts", "run", "Mode Fokus"]
    assert "--output-path" in captured["argv"]
    assert "Ran shortcut 'Mode Fokus'." == result


def test_run_shortcut_passes_text_input(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(shortcuts.subprocess, "run", fake_run)
    shortcuts.run_shortcut("Echo", text_input="halo")
    assert "--input-path" in captured["argv"]


def test_run_shortcut_empty_name():
    assert "empty" in shortcuts.run_shortcut("").lower()
