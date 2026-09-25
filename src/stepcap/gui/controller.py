"""Everything `stepcap app` does that is not drawing: no tkinter import here.

The recording runs in a child process (`stepcap record --control`): on recent
macOS a Tk window and pynput's keyboard listener in the same process crash, so
the window process never records and the recording process never draws.
"""

from __future__ import annotations

import contextlib
import json
import locale
import os
import queue
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from stepcap.session import EVENTS_FILE, load_session

TEXTS = {
    "en": {
        "subtitle": "Show your AI agent a task once: stepcap turns the recording into a skill "
        "(SKILL.md) the agent can follow, plus a step-by-step guide for people.",
        "save_to": "Save to",
        "change": "Change…",
        "name": "Name",
        "opt_typing": "Also record typed text (passwords are always masked)",
        "opt_urls": "Record browser URLs (macOS)",
        "opt_clip": "Record copied text",
        "guide_lang": "Guide language",
        "start": "●  Start recording",
        "check": "Check setup",
        "recent": "Recent recordings",
        "edit": "Edit steps",
        "export": "Export guide + skill",
        "open_folder": "Open folder",
        "rec": "REC",
        "paused": "PAUSED",
        "steps": "{n} steps",
        "pause": "Pause",
        "resume": "Resume",
        "note": "Add note",
        "stop": "■ Stop",
        "note_prompt": "Note for this step:",
        "ok": "OK",
        "skip": "Skip",
        "saved": "{n} steps saved",
        "new": "New recording",
        "exporting": "Exporting…",
        "exported": "Exported to {path}",
        "starting": "Starting… (checking permissions)",
        "failed": "Recording could not start",
        "hint_keys": "F9 stop · F8 pause · F7 note also work while recording",
        "no_steps": "No steps were recorded. Run “Check setup”.",
        "open": "Open",
        "for_people": "For people: step-by-step guide",
        "open_guide": "Open guide",
        "checklist": "Printable checklist",
        "for_agents": "For AI agents: skill (SKILL.md)",
        "agents_hint": "Add the skill and your agent can do this task for you.",
        "make_skill": "Create SKILL.md",
        "add_claude": "Add to Claude Code",
        "add_codex": "Add to Codex",
        "refine": "Generalise with {agent} first (optional, may take a few minutes)",
        "refine_confirm": "{agent} will read the draft SKILL.md, the annotated screenshots and "
        "the step list (secrets already masked) and rewrite them into a general procedure.\n\n"
        "Run {agent} now?",
        "working": "Working…",
        "refining": "{agent} is generalising the skill… (this can take a few minutes)",
        "building": "Building the guide…",
        "skill_made": "SKILL.md created: {path}",
        "skill_problems": "The skill did not pass the checks and was not added:\n{problems}",
        "exists": "A skill named “{name}” is already installed:\n{path}\n\nReplace it?",
        "installed_claude": "Added to Claude Code: {path}\nIn Claude Code type /{name}, or just "
        "ask for the task in your own words. If it does not show up, restart Claude Code.",
        "installed_codex": "Added to Codex: {path}\nIn Codex type ${name} or /skills. If it does "
        "not show up, restart Codex.",
        "export_all": "Export guide + skill (to share)",
    },
    "ja": {
        "subtitle": "作業を 1 回見せるだけで、AI エージェントが同じ作業をできる"
        "スキル（SKILL.md）と、人向けの手順書ができます。",
        "save_to": "保存先",
        "change": "変更…",
        "name": "名前",
        "opt_typing": "入力した文字も記録する（パスワードは常に伏せ字）",
        "opt_urls": "ブラウザの URL を記録する（macOS）",
        "opt_clip": "コピーした文字を記録する",
        "guide_lang": "手順書の言語",
        "start": "●  記録開始",
        "check": "環境チェック",
        "recent": "最近の記録",
        "edit": "手順を編集",
        "export": "手順書とスキルを書き出す",
        "open_folder": "フォルダを開く",
        "rec": "記録中",
        "paused": "一時停止中",
        "steps": "{n} ステップ",
        "pause": "一時停止",
        "resume": "再開",
        "note": "メモを追加",
        "stop": "■ 停止",
        "note_prompt": "このステップのメモ:",
        "ok": "OK",
        "skip": "スキップ",
        "saved": "{n} ステップを保存しました",
        "new": "新しく記録",
        "exporting": "書き出し中…",
        "exported": "書き出し先: {path}",
        "starting": "開始しています…（権限を確認中）",
        "failed": "記録を開始できませんでした",
        "hint_keys": "記録中は F9 停止・F8 一時停止・F7 メモ も使えます",
        "no_steps": "ステップが記録されていません。「環境チェック」を実行してください。",
        "open": "開く",
        "for_people": "人向け：手順書",
        "open_guide": "手順書を開く",
        "checklist": "印刷用チェックリスト",
        "for_agents": "AI エージェント向け：スキル（SKILL.md）",
        "agents_hint": "スキルを追加すると、エージェントがこの作業を代わりに行えます。",
        "make_skill": "SKILL.md を作る",
        "add_claude": "Claude Code に追加",
        "add_codex": "Codex に追加",
        "refine": "先に {agent} で一般化する（任意・数分かかることがあります）",
        "refine_confirm": "{agent} が SKILL.md の下書き・注釈付きスクリーンショット・手順一覧"
        "（秘密情報は伏せ字済み）を読み、汎用的な手順に書き直します。\n\n{agent} を実行しますか？",
        "working": "処理中…",
        "refining": "{agent} がスキルを一般化しています…（数分かかることがあります）",
        "building": "手順書を作成中…",
        "skill_made": "SKILL.md を作成しました: {path}",
        "skill_problems": "スキルがチェックに通らなかったため追加していません:\n{problems}",
        "exists": "「{name}」という名前のスキルが既にあります:\n{path}\n\n置き換えますか？",
        "installed_claude": "Claude Code に追加しました: {path}\n"
        "Claude Code で /{name} と入力するか、やりたい作業をそのまま頼んでください。"
        "表示されない場合は Claude Code を再起動してください。",
        "installed_codex": "Codex に追加しました: {path}\nCodex で ${name} または /skills から"
        "使えます。表示されない場合は Codex を再起動してください。",
        "export_all": "手順書とスキルを書き出す（共有用）",
    },
}


def ui_lang() -> str:
    """'ja' on a Japanese system, else 'en'."""
    if sys.platform == "win32":
        with contextlib.suppress(Exception):
            import ctypes

            if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x11:
                return "ja"
    for value in (
        os.environ.get("LC_ALL"),
        os.environ.get("LC_MESSAGES"),
        os.environ.get("LANG"),
        (locale.getlocale()[0] or ""),
    ):
        if value:
            return "ja" if value.lower().startswith("ja") else "en"
    return "en"


def self_command() -> list[str]:
    """How to run stepcap itself (the frozen binary, or `python -m stepcap`)."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "stepcap"]


def default_root() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "stepcap"


def new_session_name(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def free_dir(root: Path, name: str) -> Path:
    """root/name, or root/name-2, -3 ... if that already exists."""
    safe = "".join(c for c in name.strip() if c not in '<>:"/\\|?*').strip(" .") or "recording"
    path, n = root / safe, 2
    while path.exists():
        path = root / f"{safe}-{n}"
        n += 1
    return path


def recent_sessions(root: Path, limit: int = 20) -> list[Path]:
    if not root.is_dir():
        return []
    found = [p for p in root.iterdir() if (p / EVENTS_FILE).is_file()]
    found.sort(key=lambda p: (p / EVENTS_FILE).stat().st_mtime, reverse=True)
    return found[:limit]


def record_argv(out: Path, typing: bool, urls: bool, clipboard: bool) -> list[str]:
    argv = [*self_command(), "record", "-o", str(out), "--control"]
    if typing:
        argv.append("--record-typing")
    if urls:
        argv.append("--record-urls")
    if clipboard:
        argv.append("--record-clipboard")
    return argv


def export_dir(session: Path) -> Path:
    """Exports go next to the session (never inside it)."""
    return session.parent / f"{session.name}-export"


def step_count(session: Path) -> int:
    """Recorded steps (context events such as app switches or URLs do not count)."""
    from stepcap.skill.draft import CONTEXT_KINDS

    try:
        _, events = load_session(session)
    except Exception:
        return 0
    return sum(1 for ev in events if ev.get("kind") not in CONTEXT_KINDS)


def refine_agent() -> str | None:
    """The agent CLI that can generalise a skill here (claude first), or None."""
    from stepcap.skill import agents

    return next((a for a in agents.AGENTS if agents.find_cli(a)), None)


def agent_label(agent: str) -> str:
    return {"claude": "Claude Code", "codex": "Codex"}.get(agent, agent)


def build_guide(session: Path, lang: str | None) -> dict[str, Path]:
    """Build guide.html / checklist.html in the session folder (keeps edits in steps.json)."""
    from stepcap.build.pipeline import CHECKLIST_HTML, GUIDE_HTML, BuildOptions, run_build

    run_build(session, BuildOptions(lang=lang))
    return {"guide": session / GUIDE_HTML, "checklist": session / CHECKLIST_HTML}


def skill_out(session: Path) -> Path:
    return export_dir(session) / "skill"


def skill_name(session: Path) -> str:
    """The name `stepcap skill` would pick, made unique per recording when it falls back.

    A title with no ASCII letters (e.g. Japanese) gives the generic
    ``recorded-procedure``; in the window every such recording would then replace
    the previous one, so the recording's folder name (or start time) is appended.
    """
    from stepcap.skill import draft
    from stepcap.skill.run import SkillOptions, run_skill
    from stepcap.skill.validate import MAX_NAME

    res = run_skill(session, SkillOptions(out_dir=skill_out(session), force=True, dry_run=True))
    if res.name != draft.DEFAULT_NAME:
        return res.name
    suffix = draft.slugify(session.name)
    if not suffix:
        stamp = (session / EVENTS_FILE).stat().st_mtime if (session / EVENTS_FILE).exists() else 0
        suffix = new_session_name(datetime.fromtimestamp(stamp))
    return f"{draft.DEFAULT_NAME}-{suffix}"[:MAX_NAME].strip("-")


def skill_target(session: Path, agent: str, home: Path | None = None) -> tuple[str, Path]:
    """(skill name, the folder `agent` loads it from) without writing anything."""
    from stepcap.skill import install as install_mod

    name = skill_name(session)
    return name, install_mod.target_dir(agent, "user", name, home=home)


def make_skill(
    session: Path,
    install: str = "none",
    agent: str = "none",
    replace: bool = False,
    home: Path | None = None,
):
    """Write SKILL.md next to the session and optionally add it to Claude Code / Codex.

    The draft folder (``<session>-export/skill/<name>``) is always ours to replace;
    an installed skill is replaced only with ``replace=True`` (the window asks
    first), and only after the new one passed validation. The agent run was
    confirmed in the window, so ``yes=True``.
    """
    import shutil

    from stepcap.skill.run import SkillOptions, run_skill

    out = skill_out(session)
    name = skill_name(session)
    force = replace or install == "none"
    if not force and (out / name / "SKILL.md").is_file():
        shutil.rmtree(out / name)
    opt = SkillOptions(
        out_dir=out, name=name, install=install, agent=agent, force=force, yes=True, home=home
    )
    return run_skill(session, opt)


def open_path(path: Path) -> None:
    """Show a folder or file with the OS (Explorer, Finder, xdg-open); never raises."""
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])


class RecorderProcess:
    """A `stepcap record --control` child: send commands, receive status events."""

    def __init__(self, argv: list[str]) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
            creationflags=flags,
        )
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.stderr_tail: deque[str] = deque(maxlen=40)
        self._lock = threading.Lock()
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            with contextlib.suppress(ValueError):
                ev = json.loads(line)
                if isinstance(ev, dict) and "event" in ev:
                    self.events.put(ev)
        code = self.proc.wait()
        self.events.put({"event": "exited", "code": code})

    def _read_stderr(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip())

    def send(self, command: str) -> None:
        with self._lock, contextlib.suppress(OSError, ValueError):
            assert self.proc.stdin is not None
            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()

    def exclude(self, x: float, y: float, w: float, h: float) -> None:
        self.send(f"exclude {x:.0f} {y:.0f} {w:.0f} {h:.0f}")

    def drain(self) -> list[dict[str, Any]]:
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def terminate(self) -> None:
        if self.alive:
            self.send("stop")
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
