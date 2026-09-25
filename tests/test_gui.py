"""`stepcap app`: the control protocol, the controller and (with a display) the window."""

from __future__ import annotations

import contextlib
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
    elif cmd[0] == "undo":
        n = max(0, n - 1); say("undone", n=n, target=None)
    elif cmd[0] == "stop":
        say("done", ok=True, events=n, session=sys.argv[1]); break
"""


def test_parse_command():
    assert parse_command("stop\n") == ("stop", None)
    assert parse_command("note  Check the lights ") == ("note", "Check the lights")
    assert parse_command("exclude 10 20 300 40") == ("exclude", (10.0, 20.0, 300.0, 40.0))
    assert parse_command("exclude 0 0 0 0") == ("exclude", None)
    assert parse_command("exclude a b c d") is None
    assert parse_command("undo") == ("undo", None)
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
    rp.send("manual")
    _wait(rp, "note_request")
    rp.send("note second")
    assert _wait(rp, "step")["n"] == 2
    rp.send("undo")
    assert _wait(rp, "undone")["n"] == 1
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


def test_when_text_and_session_time(tmp_path):
    t = ctl.TEXTS["ja"]
    now = datetime(2026, 9, 25, 12, 0)
    assert ctl.when_text(datetime(2026, 9, 25, 9, 2), t, now) == "今日 09:02"
    assert ctl.when_text(datetime(2026, 9, 24, 17, 40), t, now) == "昨日 17:40"
    assert ctl.when_text(datetime(2026, 9, 20, 11, 5), t, now) == "2026-09-20 11:05"
    assert ctl.session_time(tmp_path / "missing") == datetime.fromtimestamp(0)


def test_compare_report_and_combined_skill(demo_session, tmp_path):
    import shutil

    other = tmp_path / "demo-again"
    shutil.copytree(demo_session, other)
    path, summary = ctl.compare_report(demo_session, other)
    assert path == ctl.export_dir(demo_session) / "diff-demo-again.html"
    assert path.is_file() and summary["same"] > 0
    assert summary["changed"] == summary["missing"] == summary["extra"] == 0

    res = ctl.make_skill(demo_session, also=(other,), home=tmp_path / "home")
    assert res.ok and len(res.recordings) == 2
    assert Path(res.skill_dir).parent == ctl.export_dir(demo_session) / "skill"


def test_theme_fonts_and_dark_override(monkeypatch):
    from stepcap.gui import theme

    assert all((theme.font_dir() / name).is_file() for name in theme.FONT_FILES)
    assert (theme.font_dir() / "LICENSE-OFL.txt").is_file()
    monkeypatch.setenv("STEPCAP_THEME", "dark")
    assert theme.os_prefers_dark() is True
    monkeypatch.setenv("STEPCAP_THEME", "light")
    assert theme.os_prefers_dark() is False


def test_wrap_breaks_japanese_between_characters():
    from stepcap.gui.theme import wrap

    class Mono:  # every character is 10 px wide
        def measure(self, text):
            return 10 * len(text)

    text = "作業を 1 回見せるだけで、AI エージェントが同じ作業をできるスキル（SKILL.md）と、人向け"
    lines = wrap(text, Mono(), 200).split("\n")
    assert all(len(line) <= 20 for line in lines)
    assert lines[0] == "作業を 1 回見せるだけで、AI エー"  # not at the space after "AI"
    assert "（SKILL.md）" in "".join(lines) and not any(ln.startswith(("、", "）")) for ln in lines)
    assert wrap("a b", Mono(), 200) == "a b"
    assert wrap("path: /a/very/long/folder/name", Mono(), 100).split("\n") == [
        "path:",
        "/a/very/lo",
        "ng/folder/",
        "name",
    ]
    assert wrap("one\ntwo", Mono(), 100) == "one\ntwo"


def test_texts_have_the_same_keys():
    assert set(ctl.TEXTS["en"]) == set(ctl.TEXTS["ja"])
    for lang in ("en", "ja"):  # every placeholder the window fills in exists in both languages
        t = ctl.TEXTS[lang]
        t["installed_claude"].format(path="p", name="n")
        t["installed_agents"].format(path="p", name="n")
        assert "$n" in t["installed_agents"].format(path="p", name="n")
        assert "A" in t["installed_other"].format(path="p", name="n", agent="A")
        assert "A" in t["add_to"].format(agent="A")
        assert "/n" in t["installed_claude"].format(path="p", name="n")
        t["exists"].format(name="n", path="p")
        t["refine"].format(agent="a")
        t["refine_confirm"].format(agent="a")
        t["compared"].format(a="a", b="b", path="p", same=1, changed=2, missing=3, extra=4)
        t["combine"].format(n=2)
        t["combine_title"].format(n=2)
        t["added_head"].format(agent="A")
        t["copy_cmd"].format(cmd="/x")
        t["copied"].format(cmd="/x")
        assert "SKILL.md" in t["subtitle"]


def test_step_count_and_guide(demo_session):
    n = ctl.step_count(demo_session)
    assert n > 0
    assert ctl.step_count(demo_session.parent / "missing") == 0
    paths = ctl.build_guide(demo_session, "ja")
    assert paths["guide"].is_file() and paths["checklist"].is_file()
    assert paths["guide"].parent == demo_session


def test_add_skill_to_claude_and_codex(demo_session, tmp_path):
    home = tmp_path / "home"
    name, target = ctl.skill_target(demo_session, "claude", home)
    assert target == home / ".claude" / "skills" / name
    assert name == ctl.skill_name(demo_session)
    assert not target.exists()  # the check writes nothing

    res = ctl.make_skill(demo_session, "claude", home=home)
    assert res.ok and res.installed_to == str(target)
    assert (target / "SKILL.md").is_file()
    assert Path(res.skill_dir) == ctl.export_dir(demo_session) / "skill" / name

    # a second time without replace: the draft folder is ours, the installed skill is not
    from stepcap.skill.run import SkillError

    (target / "SKILL.md").write_text("mine", encoding="utf-8")
    with pytest.raises(SkillError, match="already exists"):
        ctl.make_skill(demo_session, "claude", home=home)
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "mine"
    res = ctl.make_skill(demo_session, "claude", replace=True, home=home)
    assert res.ok and (target / "SKILL.md").read_text(encoding="utf-8").startswith("---")

    res = ctl.make_skill(demo_session, "codex", home=home)
    assert res.installed_to == str(home / ".agents" / "skills" / name)

    res = ctl.make_skill(demo_session)  # SKILL.md only; repeatable
    res = ctl.make_skill(demo_session)
    assert res.ok and res.installed_to is None


def test_replace_refuses_a_folder_that_is_not_a_skill(demo_session, tmp_path):
    from stepcap.skill.run import SkillError

    home = tmp_path / "home"
    _, target = ctl.skill_target(demo_session, "claude", home)
    target.mkdir(parents=True)
    (target / "notes.txt").write_text("keep", encoding="utf-8")
    with pytest.raises(SkillError, match="not a skill folder"):
        ctl.make_skill(demo_session, "claude", replace=True, home=home)
    assert (target / "notes.txt").is_file()


def test_skill_name_is_unique_per_recording(demo_session, tmp_path):
    import shutil

    from stepcap.session import STEPS_FILE, read_json, write_json

    ctl.build_guide(demo_session, "en")
    doc = read_json(demo_session / STEPS_FILE)
    doc["title"] = "照明チェック"  # no ASCII: the generic name would collide
    for s in doc["steps"]:
        s["app_name"] = "音響卓"
    write_json(demo_session / STEPS_FILE, doc)
    assert ctl.skill_name(demo_session) == "recorded-procedure-demo"
    other = tmp_path / "録音"
    shutil.copytree(demo_session, other)
    name = ctl.skill_name(other)  # folder name has no ASCII either -> its time stamp
    assert name.startswith("recorded-procedure-2") and name != "recorded-procedure-demo"
    res = ctl.make_skill(demo_session, "claude", home=tmp_path / "home")
    assert res.ok and res.name == "recorded-procedure-demo"

    doc["title"] = "Check the mixer"
    write_json(demo_session / STEPS_FILE, doc)
    assert ctl.skill_name(demo_session) == "check-the-mixer"


def test_generalise_then_add_to_claude(demo_session, tmp_path, monkeypatch):
    from stepcap.skill import agents
    from test_skill_gen import FAKE_AGENT

    script = tmp_path / "fake_agent.py"
    script.write_text(FAKE_AGENT, encoding="utf-8")
    monkeypatch.setattr(agents, "find_cli", lambda a: sys.executable)
    monkeypatch.setattr(agents, "command", lambda agent, exe, d: [exe, str(script)])
    home = tmp_path / "home"
    res = ctl.make_skill(demo_session, "claude", agent="claude", home=home)
    assert res.ok, res.problems
    text = (Path(res.installed_to) / "SKILL.md").read_text(encoding="utf-8")
    assert "# Refined" in text and 'status: "refined by claude"' in text
    assert not (Path(res.installed_to) / "_context").exists()


def test_share_guide(demo_session, tmp_path):
    import json
    import re

    from stepcap import share

    out = ctl.share_guide(demo_session, tmp_path / "x-protected.html", "a long password", "ja")
    text = out.read_text("utf-8")
    assert "パスワード" in text
    blob = json.loads(re.search(r'type="application/json">(.*?)</script>', text, re.S).group(1))
    assert "Create a project" in share.decrypt(blob, "a long password")


def test_refine_agent(monkeypatch):
    from stepcap.skill import agents

    monkeypatch.setattr(agents, "find_cli", lambda a: "/x/codex" if a == "codex" else None)
    assert ctl.refine_agent() == "codex"
    monkeypatch.setattr(agents, "find_cli", lambda a: "/x/" + a)
    assert ctl.refine_agent() == "claude"
    monkeypatch.setattr(agents, "find_cli", lambda a: None)
    assert ctl.refine_agent() is None
    assert ctl.agent_label("claude") == "Claude Code"


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

    for name in ("a", "b", "c"):  # recent recordings on the home view
        (tmp_path / name).mkdir()
        (tmp_path / name / "events.jsonl").write_text("", encoding="utf-8")
    monkeypatch.setenv("STEPCAP_THEME", "dark")
    try:
        app = App(root, "ja")
        root.update()
        assert [(i.width(), i.height()) for i in app.icons] == [(256, 256), (32, 32)]
        assert app.theme.dark == app.theme.sv_ttk  # dark needs sv-ttk; without it: light
        # the bundled font, registered for this process only (Windows / macOS / fontconfig)
        assert app.theme.family == "Noto Sans JP"

        # tick two recordings: combine and compare; a third: combine only
        assert app.combine_btn.instate(["disabled"]) and app.compare_btn.instate(["disabled"])
        boxes = [w for w in _widgets(app.frame) if w.winfo_class() == "TCheckbutton"]
        picks = [b for b in boxes if not b.cget("text")]
        picks[1].invoke()
        picks[0].invoke()
        assert len(app.picked) == 2
        assert not app.combine_btn.instate(["disabled"])
        assert not app.compare_btn.instate(["disabled"])
        first = app.picked[0]
        assert first == app.recent[1]  # the first one ticked is the reference
        picks[2].invoke()
        assert app.compare_btn.instate(["disabled"]) and not app.combine_btn.instate(["disabled"])
        assert app.combine_btn.cget("text") == app.t["combine"].format(n=3)
        app.combine()
        root.update()
        assert app.session == first and len(app.also) == 2
        labels = _texts(app.frame)
        assert app.t["combine_title"].format(n=3) in labels and app.t["add_claude"] in labels
        app.show_home()
        root.update()
        app.rec = FakeRec()
        app.session = tmp_path / "s1"
        app.handle({"event": "ready", "session": str(app.session)})
        root.update()
        assert any(isinstance(c, tuple) and c[0] == "exclude" for c in sent)
        assert app.undo_btn.instate(["disabled"])  # nothing to undo yet
        app.handle({"event": "step", "n": 3, "kind": "single-click", "where": "x"})
        app.update_bar()
        assert "3 ステップ" in app.bar_label.cget("text")
        app.undo()
        assert sent[-1] == "undo"
        app.handle({"event": "undone", "n": 2, "target": 3})
        assert app.steps == 2
        app.handle({"event": "step", "n": 3, "kind": "single-click", "where": "x"})
        app.handle({"event": "note_request"})
        root.update()
        assert app.note_row is not None
        app.handle({"event": "paused"})
        app.toggle_pause()
        assert sent[-1] == "resume"
        app.handle({"event": "transcribing"})
        root.update()
        assert app.bar_label.cget("text") == app.t["transcribing"]
        assert app.stop_btn.instate(["disabled"])
        app.handle({"event": "done", "ok": True, "events": 3, "session": str(app.session)})
        root.update()
        assert app.rec is None
        labels = _texts(app.frame)
        for key in (
            "for_people",
            "open_guide",
            "checklist",
            "share",
            "for_agents",
            "add_claude",
            "add_agents",
            "make_skill",
        ):
            assert app.t[key] in labels, key

        # slow work runs on a thread and is applied on the Tk thread by poll()
        got = []
        app.run_job("…", lambda: 42, got.append)
        assert all(b.instate(["disabled"]) for b in app.action_buttons)
        end = time.time() + 5
        while not got and time.time() < end:
            root.update()
            time.sleep(0.02)
        assert got == [42] and not app.busy
        assert not any(b.instate(["disabled"]) for b in app.action_buttons)
        app.run_job("…", lambda: 1 / 0, got.append)
        end = time.time() + 5
        while app.busy and time.time() < end:
            root.update()
            time.sleep(0.02)
        assert "ZeroDivisionError" in app.status.get()
        app.show_home()
        root.update()
        app.handle({"event": "error", "message": "no permission"})
        assert "no permission" in app.status.get()
    finally:
        root.destroy()


def _widgets(widget) -> list:
    out = [widget]
    for w in widget.winfo_children():
        out += _widgets(w)
    return out


def _texts(widget) -> set[str]:
    """Every ``text`` shown in ``widget`` and its children (labels, buttons, frame titles)."""
    out = set()
    with contextlib.suppress(Exception):
        out.add(str(widget.cget("text")))
    for w in widget.winfo_children():
        out |= _texts(w)
    return out


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
