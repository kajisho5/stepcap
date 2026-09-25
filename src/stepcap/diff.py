"""`stepcap diff A B`: what changed between two recordings of the same task (RM-054).

Two uses:
- the app changed: record the task again and see which steps moved, disappeared or
  now look different, to update the guide;
- an agent did the task: record while the agent works (`stepcap record` captures its
  clicks and typing like yours, `stepcap shell` its commands) and compare with the
  recording its skill came from.

Steps are matched in order (difflib) by what they did: kind + element name, else kind
+ app + window. Matched steps are then checked for a different screen (screenshot
similarity) and a different typed value (when typing was recorded). URLs and terminal
commands are compared as sets: an agent that used a CLI instead of the UI shows up as
extra commands and missing clicks.
"""

from __future__ import annotations

import base64
import difflib
import html
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image

from stepcap.build import annotate, dedupe
from stepcap.build import steps as steps_mod
from stepcap.build.steps import STEP_KINDS
from stepcap.skill.recording import load_recording

SCREEN_SAME = 0.9  # similarity below this = "the screen looks different"
THUMB_W = 480


@dataclass
class StepRef:
    number: int
    title: str
    kind: str
    where: str
    id: str

    @classmethod
    def of(cls, n: int, s: dict[str, Any]) -> StepRef:
        where = s.get("app_name") or s.get("window_title") or ""
        return cls(n, s.get("title") or s.get("kind", ""), s.get("kind", ""), where, s["id"])


@dataclass
class Change:
    status: str  # same | changed | missing | extra
    a: StepRef | None = None
    b: StepRef | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Diff:
    a: str
    b: str
    changes: list[Change]
    urls: dict[str, list[str]]
    commands: dict[str, list[str]]

    def count(self, status: str) -> int:
        return sum(c.status == status for c in self.changes)

    @property
    def identical(self) -> bool:
        return all(c.status == "same" for c in self.changes) and not any(
            self.urls[k] or self.commands[k] for k in ("only_a", "only_b")
        )

    def to_dict(self) -> dict[str, Any]:
        d = {
            "a": self.a,
            "b": self.b,
            "summary": {s: self.count(s) for s in ("same", "changed", "missing", "extra")},
            "identical": self.identical,
            "changes": [asdict(c) for c in self.changes],
            "urls": self.urls,
            "commands": self.commands,
        }
        return d


def _norm(text: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(text or ""))).strip().casefold()


def key(s: dict[str, Any]) -> tuple[str, ...]:
    """What a step did, independent of where on the screen and of wording edits."""
    kind = s.get("kind", "")
    name = _norm((s.get("element") or {}).get("name"))
    if kind == "key":
        return (kind, _norm(s.get("keys")))
    if kind == "manual":
        return (kind, _norm(s.get("title"))[:40])
    if name:
        return (kind, s.get("click_type") or "", name)
    return (kind, s.get("click_type") or "", _norm(s.get("app_name")), _norm(s.get("window_title")))


def typed_values(events: list[dict[str, Any]]) -> dict[int, str]:
    return {
        ev["id"]: ev["text"]
        for ev in events
        if ev.get("kind") == "type" and "id" in ev and ev.get("text") and not ev.get("masked")
    }


def _context(events: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    urls = {
        f"{u.hostname}{u.path}".rstrip("/")
        for ev in events
        if ev.get("kind") == "url" and ev.get("url")
        for u in [urlsplit(ev["url"])]
        if u.hostname
    }
    cmds = {
        _norm(ev["command"]) for ev in events if ev.get("kind") == "terminal" and ev.get("command")
    }
    return urls, cmds


class _Screens:
    def __init__(self, session: Path) -> None:
        self.session = session
        self.cache: dict[str, Image.Image] = {}

    def get(self, sid: str | None) -> Image.Image | None:
        if not sid:
            return None
        if sid not in self.cache:
            p = steps_mod.raw_path(self.session, sid)
            if not p.exists():
                return None
            if len(self.cache) > 8:
                self.cache.clear()
            self.cache[sid] = Image.open(p).convert("RGB")
        return self.cache[sid]


def compare(a: Path, b: Path) -> Diff:
    a, b = Path(a), Path(b)
    _, doc_a, ev_a = load_recording(a)
    _, doc_b, ev_b = load_recording(b)
    sa = [s for s in doc_a["steps"] if s.get("kind") in STEP_KINDS]
    sb = [s for s in doc_b["steps"] if s.get("kind") in STEP_KINDS]
    ka, kb = [key(s) for s in sa], [key(s) for s in sb]
    typed_a, typed_b = typed_values(ev_a), typed_values(ev_b)
    screens_a, screens_b = _Screens(a), _Screens(b)
    changes: list[Change] = []

    def pair(i: int, j: int, status: str) -> None:
        s1, s2 = sa[i], sb[j]
        notes = []
        if status == "changed":
            notes.append(f"was {s1.get('title')!r}, now {s2.get('title')!r}")
        img1 = screens_a.get(s1.get("own_screenshot") or s1.get("screenshot"))
        img2 = screens_b.get(s2.get("own_screenshot") or s2.get("screenshot"))
        if img1 is not None and img2 is not None:
            sim = dedupe.similarity(img1, img2)
            if sim < SCREEN_SAME:
                notes.append(f"the screen looks different ({sim:.0%} similar)")
        t1, t2 = typed_a.get(s1.get("event_id")), typed_b.get(s2.get("event_id"))
        if t1 is not None and t2 is not None and t1 != t2:
            notes.append("a different value was typed")
        if status == "same" and notes:
            status = "changed"
        changes.append(Change(status, StepRef.of(i + 1, s1), StepRef.of(j + 1, s2), notes))

    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ka, b=kb, autojunk=False).get_opcodes():
        if op == "equal":
            for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                pair(i, j, "same")
        elif op == "replace":
            common = min(i2 - i1, j2 - j1)
            for k in range(common):
                pair(i1 + k, j1 + k, "changed")
            for i in range(i1 + common, i2):
                changes.append(Change("missing", a=StepRef.of(i + 1, sa[i])))
            for j in range(j1 + common, j2):
                changes.append(Change("extra", b=StepRef.of(j + 1, sb[j])))
        elif op == "delete":
            for i in range(i1, i2):
                changes.append(Change("missing", a=StepRef.of(i + 1, sa[i])))
        elif op == "insert":
            for j in range(j1, j2):
                changes.append(Change("extra", b=StepRef.of(j + 1, sb[j])))
    ua, ca = _context(ev_a)
    ub, cb = _context(ev_b)
    return Diff(
        str(a),
        str(b),
        changes,
        {"only_a": sorted(ua - ub), "only_b": sorted(ub - ua), "both": sorted(ua & ub)},
        {"only_a": sorted(ca - cb), "only_b": sorted(cb - ca), "both": sorted(ca & cb)},
    )


# ------------------------------------------------------------------------ report
LABELS = {
    "same": ("same", "#4a7"),
    "changed": ("changed", "#c80"),
    "missing": ("only in A", "#c33"),
    "extra": ("only in B", "#36c"),
}


def _thumb(session: Path, doc: dict[str, Any], ref: StepRef | None) -> str:
    if ref is None:
        return ""
    step = next((s for s in doc["steps"] if s["id"] == ref.id), None)
    if not step or not step.get("screenshot"):
        return ""
    src = Image.open(steps_mod.ensure_work_copy(session, step["screenshot"])).convert("RGB")
    img, _ = annotate.render(
        src, step, ref.number, THUMB_W, None, doc.get("marker") or "box", False, True
    )
    data = base64.b64encode(annotate.encode(img, "jpeg", 70)).decode("ascii")
    return f'<img alt="step {ref.number}" src="data:image/jpeg;base64,{data}">'


def report_html(d: Diff) -> str:
    """One self-contained HTML page: changed / missing / extra steps side by side."""
    a, b = Path(d.a), Path(d.b)
    _, doc_a, _ = load_recording(a)
    _, doc_b, _ = load_recording(b)
    e = html.escape
    rows = []
    for c in d.changes:
        label, colour = LABELS[c.status]
        left = f"<b>{c.a.number}. {e(c.a.title)}</b>" if c.a else "—"
        right = f"<b>{c.b.number}. {e(c.b.title)}</b>" if c.b else "—"
        notes = "".join(f"<li>{e(n)}</li>" for n in c.notes)
        imgs = ""
        if c.status != "same":
            ta, tb = _thumb(a, doc_a, c.a), _thumb(b, doc_b, c.b)
            imgs = f"<tr><td>{ta}</td><td></td><td>{tb}</td></tr>"
        rows.append(
            f'<tr class="{c.status}"><td>{left}</td>'
            f'<td><span class="tag" style="background:{colour}">{label}</span>'
            f"<ul>{notes}</ul></td><td>{right}</td></tr>{imgs}"
        )

    def ctx(title: str, items: dict[str, list[str]]) -> str:
        if not (items["only_a"] or items["only_b"]):
            return ""
        li = "".join(f"<li>only in A: <code>{e(x)}</code></li>" for x in items["only_a"])
        li += "".join(f"<li>only in B: <code>{e(x)}</code></li>" for x in items["only_b"])
        return f"<h2>{title}</h2><ul>{li}</ul>"

    summary = ", ".join(f"{d.count(s)} {LABELS[s][0]}" for s in LABELS)
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>stepcap diff</title><style>
body{{font:15px/1.5 system-ui,sans-serif;margin:24px;color:#222;background:#fff}}
@media (prefers-color-scheme:dark){{body{{background:#16181c;color:#eee}}td{{border-color:#333}}}}
table{{border-collapse:collapse;width:100%}}td{{border-bottom:1px solid #ddd;padding:6px;
vertical-align:top;width:45%}}td:nth-child(2){{width:10%;text-align:center}}
.tag{{color:#fff;border-radius:4px;padding:1px 6px;font-size:13px;white-space:nowrap}}
img{{max-width:100%;border:1px solid #ccc}}ul{{margin:4px 0;padding-left:18px;text-align:left}}
tr.same td{{color:#888}}
</style></head><body>
<h1>stepcap diff</h1>
<p>A: <code>{e(d.a)}</code><br>B: <code>{e(d.b)}</code></p>
<p>{e(summary)}</p>
<table>{"".join(rows)}</table>
{ctx("Browser URLs", d.urls)}{ctx("Terminal commands", d.commands)}
</body></html>
"""
