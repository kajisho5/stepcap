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

from stepcap.session import EVENTS_FILE

TEXTS = {
    "en": {
        "subtitle": "Record once: a guide for people and a skill for agents",
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
    },
    "ja": {
        "subtitle": "1 回の記録で、人向けの手順書とエージェント用のスキル",
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
