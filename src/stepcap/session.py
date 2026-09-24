"""Session directory layout and I/O.

SESSION_DIR/
  session.json   metadata (start/end, OS, monitors, options, version)
  events.jsonl   one event per line (append-only while recording)
  raw/           original screenshots - never modified after recording
  work/          working copies touched by build/edit (blur etc.)
  steps.json     canonical, editable list of steps (written by build/edit)
"""

from __future__ import annotations

import json
import os
import platform
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from stepcap import __version__

SESSION_FILE = "session.json"
EVENTS_FILE = "events.jsonl"
STEPS_FILE = "steps.json"
RAW_DIR = "raw"
WORK_DIR = "work"
SESSION_FORMAT = 1


class SessionError(Exception):
    """A user-facing problem with a session directory."""


def now_iso() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def default_session_dir() -> Path:
    return Path(f"stepcap-{datetime.now():%Y%m%d-%H%M%S}")


def prepare_new_session(path: Path) -> Path:
    """Create an empty session dir. Refuses to touch a non-empty directory."""
    path = Path(path)
    if path.exists():
        if not path.is_dir():
            raise SessionError(f"{path} exists and is not a directory")
        if any(path.iterdir()):
            raise SessionError(
                f"{path} is not empty; refusing to overwrite. Choose a new -o directory."
            )
    (path / RAW_DIR).mkdir(parents=True, exist_ok=True)
    return path


def base_meta(source: str, options: dict[str, Any]) -> dict[str, Any]:
    return {
        "format": SESSION_FORMAT,
        "stepcap_version": __version__,
        "source": source,
        "started": now_iso(),
        "ended": None,
        "os": platform.platform(),
        "platform": sys.platform,
        "python": platform.python_version(),
        "monitors": [],
        "options": options,
    }


def write_json(path: Path, data: Any) -> bool:
    """Write JSON atomically. Returns False (and does nothing) if content is unchanged."""
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    path = Path(path)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return True


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class EventWriter:
    """Append-only JSONL writer, flushed per line so a crash loses at most one event."""

    def __init__(self, path: Path) -> None:
        self._fh = open(path, "a", encoding="utf-8", newline="\n")  # noqa: SIM115
        self._lock = threading.Lock()
        self.count = 0

    def write(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()
            self.count += 1

    def close(self) -> None:
        with self._lock:
            self._fh.close()


def is_session(path: Path) -> bool:
    return (Path(path) / EVENTS_FILE).is_file()


def load_session(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    path = Path(path)
    if not path.is_dir():
        raise SessionError(f"{path} does not exist or is not a directory")
    if not is_session(path):
        raise SessionError(f"{path} is not a stepcap session (no {EVENTS_FILE})")
    meta: dict[str, Any] = {}
    if (path / SESSION_FILE).is_file():
        meta = read_json(path / SESSION_FILE)
    events = []
    with open(path / EVENTS_FILE, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                # A truncated last line (e.g. power loss) must not make the session unusable.
                print(
                    f"warning: {EVENTS_FILE}:{n}: skipped unreadable line ({exc})", file=sys.stderr
                )
    return meta, events
