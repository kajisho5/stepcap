"""Does a skill still say what the recording showed? (RM-067)

After a person or an agent rewrote the draft, details get lost: a button, a
field, the app, a URL, a terminal command or the note that explained why. This
compares the recording with SKILL.md and lists what the text no longer
mentions. It is a hint for review, not a proof: a skill can describe a step
in other words (or replace clicks with a CLI call) and still be right.

Checked items, all from the recording (secrets already masked):
  app      app names of the steps
  element  names of clicked buttons / fields (UI Automation / Accessibility)
  input    typed values that became {{variables}}
  url      host names of browser URLs (--record-urls)
  command  terminal commands (stepcap shell)
  note     F7 notes (the "why")
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from stepcap.build.steps import STEP_KINDS
from stepcap.skill import frontmatter

KINDS = ("app", "element", "input", "url", "command", "note")
NOTE_MATCH = 0.6  # share of a note's character pairs that must appear in the skill


@dataclass
class Item:
    kind: str
    value: str
    steps: list[int] = field(default_factory=list)
    found: bool = False


@dataclass
class Coverage:
    items: list[Item]

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def found(self) -> int:
        return sum(i.found for i in self.items)

    @property
    def score(self) -> float:
        return self.found / self.total if self.items else 1.0

    @property
    def missing(self) -> list[Item]:
        return [i for i in self.items if not i.found]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "found": self.found,
            "total": self.total,
            "items": [asdict(i) for i in self.items],
        }


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", text)


def _squash(text: str) -> str:
    """Letters and digits only (for comparing notes regardless of punctuation)."""
    return "".join(ch for ch in _norm(text) if ch.isalnum())


def _pairs(text: str) -> set[str]:
    s = _squash(text)
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s} if s else set()


def _label(text: str) -> str:
    """A button label without decoration: '+ New project' -> 'new project'."""
    return _norm(text).strip(" +-*•›»…:").strip()


def _mentions(item: Item, body: str, squashed: str) -> bool:
    v = item.value
    if item.kind == "input":
        return f"{{{{{v}}}}}" in body or re.search(rf"\b{re.escape(v)}\b", body) is not None
    if item.kind == "note":
        pairs = _pairs(v)
        if not pairs:
            return True
        return sum(p in squashed for p in pairs) / len(pairs) >= NOTE_MATCH
    if item.kind == "command":
        cmd = _norm(v)
        head = " ".join(cmd.split()[:2])
        return cmd in body or (len(head) >= 3 and head in body)
    label = _label(v) if item.kind == "element" else _norm(v)
    return bool(label) and label in body


def _add(items: dict[tuple[str, str], Item], kind: str, value: Any, step: int | None) -> None:
    if not isinstance(value, str) or not value.strip():
        return
    value = re.sub(r"\s+", " ", value).strip()
    if kind == "element" and len(_label(value)) < 2:
        return
    item = items.setdefault((kind, _norm(value)), Item(kind, value))
    if step is not None and step not in item.steps:
        item.steps.append(step)


def recorded_items(doc: dict[str, Any], events: list[dict[str, Any]]) -> list[Item]:
    items: dict[tuple[str, str], Item] = {}
    steps = [s for s in doc.get("steps", []) if s.get("kind") in STEP_KINDS]
    number = {}
    for n, s in enumerate(steps, 1):
        number[s.get("event_id")] = n
        _add(items, "app", s.get("app_name"), n)
        el = s.get("element") or {}
        if s.get("kind") in ("click", "type"):
            _add(items, "element", el.get("name"), n)
        inp = s.get("input")
        if s.get("kind") == "type" and isinstance(inp, dict) and inp.get("variable", True):
            _add(items, "input", inp.get("name"), n)
        if s.get("kind") == "manual":
            note = s.get("title") or ""
            if s.get("description"):
                note += " " + s["description"]
            _add(items, "note", note, n)
    for ev in events:
        n = number.get(ev.get("seq"))  # context events carry the event id of the next step
        if ev.get("kind") == "url" and ev.get("url"):
            _add(items, "url", urlsplit(ev["url"]).hostname, n)
        elif ev.get("kind") == "terminal":
            _add(items, "command", ev.get("command"), n)
    return list(items.values())


def check(skill_md: str, doc: dict[str, Any], events: list[dict[str, Any]]) -> Coverage:
    try:
        fields, body = frontmatter.parse(skill_md)
        text = f"{fields.get('description', '')}\n{body}"
    except frontmatter.FrontmatterError:
        text = skill_md
    body = _norm(text)
    squashed = _squash(text)
    items = recorded_items(doc, events)
    for item in items:
        item.found = _mentions(item, body, squashed)
    order = {k: i for i, k in enumerate(KINDS)}
    items.sort(key=lambda i: (order[i.kind], i.steps[:1] or [0]))
    return Coverage(items)


def check_dir(skill_dir: Path, session: Path) -> Coverage:
    from stepcap.skill.recording import load_recording

    _, doc, events = load_recording(session)
    return check((Path(skill_dir) / "SKILL.md").read_text(encoding="utf-8"), doc, events)
