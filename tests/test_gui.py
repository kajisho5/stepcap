"""`stepcap app`: the control protocol, the controller and (with a display) the window."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pytest

from stepcap.capture.recorder import parse_command
from stepcap.gui import controller as ctl

FAKE_RECORDER = r"""
import json, sys
def say(ev, **kw): print(json.dumps({"event": ev, **kw}), flush=True)
say("ready", session=sys.argv[1])
n = 0
for line in sys.stdin:
    cmd = line.split()
    if not cmd:
        continue
    if cmd[0] == "exclude":
        say("step", n=0, kind="exclude:" + ",".join(cmd[1:]), where="")
    elif cmd[0] == "manual":
        say("note_request")
    elif cmd[0] == "note":
        n += 1; say("step", n=n, kind="manual", where=" ".join(cmd[1:]))
    elif cmd[0] == "pause":
        say("paused")
    elif cmd[0] == "stop":
        say("done", ok=True, events=n, session=sys.argv[1]); break
"""


def test_parse_command():
    assert parse_command("stop\n") == ("stop", None)
    assert parse_command("note  Check the lights ") == ("note", "Check the lights")
    assert parse_command("exclude 10 20 300 40") == ("exclude", (10.0, 20.0, 300.0, 40.0))
    assert parse_command("exclude 0 0 0 0") == ("exclude", None)
    assert parse_command("exclude a b c d") is None
    assert parse_command("rm -rf /") is None
    assert parse_command("") is None


_pending: list[dict] = []


def _wait(rp: ctl.RecorderProcess, kind: str, timeout: float = 10.0) -> dict:
    """Next event of ``kind``; events drained but not yet consumed are kept."""
    end = time.time() + timeout
    while time.time() < end:
        _pending.extend(rp.drain())
        for i, ev in enumerate(_pending):
            if ev["event"] == kind:
                del _pending[: i + 1]
                return ev
        time.sleep(0.02)
    raise AssertionError(f"no {kind!r} event; got {_pending}")


def test_recorder_process_protocol(tmp_path):
    script = tmp_path / "fake.py"
    script.write_text(FAKE_RECORDER, encoding="utf-8")
    _pending.clear()
    rp = ctl.RecorderProcess([sys.executable, str(script), "S"])
    assert _wait(rp, "ready")["session"] == "S"
    rp.exclude(10.4, 20, 300, 40)
    assert _wait(rp, "step")["kind"] == "exclude:10,20,300,40"
    rp.send("manual")
    _wait(rp, "note_request")
    rp.send("note 照明が緑か確認")
    assert _wait(rp, "step")["where"] == "照明が緑か確認"  # UTF-8 both ways
    rp.send("stop")
    assert _wait(rp, "done")["events"] == 1
    assert _wait(rp, "exited")["code"] == 0
    assert not rp.alive


def test_helpers(tmp_path, monkeypatch):
    assert ctl.new_session_name(datetime(2026, 9, 25, 8, 5, 3)) == "20260925-080503"
    assert ctl.free_dir(tmp_path, "demo") == tmp_path / "demo"
    (tmp_path / "demo").mkdir()
    assert ctl.free_dir(tmp_path, "demo") == tmp_path / "demo-2"
    assert ctl.free_dir(tmp_path, "a/b:c*") == tmp_path / "abc"
    assert ctl.free_dir(tmp_path, "  ") == tmp_path / "recording"
    assert ctl.export_dir(tmp_path / "demo") == tmp_path / "demo-export"

    (tmp_path / "old").mkdir()
    (tmp_path / "old" / "events.jsonl").write_text("", encoding="utf-8")
    (tmp_path / "new").mkdir()
    (tmp_path / "new" / "events.jsonl").write_text("", encoding="utf-8")
    later = time.time() + 10
    import os

    os.utime(tmp_path / "new" / "events.jsonl", (later, later))
    assert [p.name for p in ctl.recent_sessions(tmp_path)] == ["new", "old"]
    assert ctl.recent_sessions(tmp_path / "missing") == []

    argv = ctl.record_argv(tmp_path / "s", True, False, True)
    assert argv[-6:] == [
        "record",
        "-o",
        str(tmp_path / "s"),
        "--control",
        "--record-typing",
        "--record-clipboard",
    ]

    if sys.platform != "win32":
        for var in ("LC_ALL", "LC_MESSAGES"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("LANG", "ja_JP.UTF-8")
        assert ctl.ui_lang() == "ja"
        monkeypatch.setenv("LANG", "en_US.UTF-8")
        assert ctl.ui_lang() == "en"


def test_texts_have_the_same_keys():
    assert set(ctl.TEXTS["en"]) == set(ctl.TEXTS["ja"])


def test_window_views(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    from stepcap.gui.app import App

    monkeypatch.setattr(ctl, "default_root", lambda: tmp_path)
    sent = []

    class FakeRec:
        def __init__(self):
            self.stderr_tail = []

        def send(self, cmd):
            sent.append(cmd)

        def exclude(self, *rect):
            sent.append(("exclude", rect))

        def drain(self):
            return []

        def terminate(self):
            pass

    try:
        app = App(root, "ja")
        root.update()
        app.rec = FakeRec()
        app.session = tmp_path / "s1"
        app.handle({"event": "ready", "session": str(app.session)})
        root.update()
        assert any(isinstance(c, tuple) and c[0] == "exclude" for c in sent)
        app.handle({"event": "step", "n": 3, "kind": "single-click", "where": "x"})
        app.update_bar()
        assert "3 ステップ" in app.bar_label.cget("text")
        app.handle({"event": "note_request"})
        root.update()
        assert app.note_row is not None
        app.handle({"event": "paused"})
        app.toggle_pause()
        assert sent[-1] == "resume"
        app.handle({"event": "done", "ok": True, "events": 3, "session": str(app.session)})
        root.update()
        assert app.rec is None
        app.show_home()
        root.update()
        app.handle({"event": "error", "message": "no permission"})
        assert "no permission" in app.status.get()
    finally:
        root.destroy()


def test_cli_app_without_tkinter(monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "stepcap.gui.app":
            raise ImportError("No module named 'tkinter'")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from stepcap.cli import main

    assert main(["app"]) == 1
    assert "tkinter" in capsys.readouterr().err


def test_texts_file_is_json_serialisable():
    json.dumps(ctl.TEXTS, ensure_ascii=False)
    assert Path(ctl.__file__).read_text(encoding="utf-8").count("import tkinter") == 0


def test_macos_note_prompt_uses_osascript_not_tk(monkeypatch):
    import subprocess

    from stepcap.capture import recorder

    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="Check the mixer\n", stderr="")

    monkeypatch.setattr(recorder.sys, "platform", "darwin")
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setitem(sys.modules, "tkinter", None)  # importing tkinter would fail
    assert recorder.prompt_note("auto") == "Check the mixer"
    assert calls[0][0] == "osascript"

    def cancelled(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="User canceled.")

    monkeypatch.setattr(subprocess, "run", cancelled)
    assert recorder.prompt_note("gui") is None
