"""steps.json: the canonical, editable list of steps.

Created from events.jsonl on the first build. After that the file wins:
titles/descriptions edited by a person, an agent or ``stepcap edit`` are never
overwritten, and deleted/reordered steps stay that way. Untouched automatic
texts are regenerated (e.g. when ``--lang`` changes). ``--reset`` recreates it.

Every step keeps ``auto.title`` / ``auto.description``: when the current text
equals the auto text it is considered untouched.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from stepcap import __version__
from stepcap.build import dedupe, naming
from stepcap.build.annotate import BOX_KINDS
from stepcap.build.detect import detect_box
from stepcap.session import RAW_DIR, STEPS_FILE, WORK_DIR, SessionError, read_json

STEPS_FORMAT = 1
POINT_KEYS = ("x", "y", "rel_x", "rel_y", "img_x", "img_y")


def shot_id(path: str | None) -> str | None:
    if not path:
        return None
    return Path(path).stem


def raw_path(session: Path, sid: str) -> Path:
    return session / RAW_DIR / f"{sid}.png"


def work_path(session: Path, sid: str) -> Path:
    return session / WORK_DIR / f"{sid}.png"


def ensure_work_copy(session: Path, sid: str) -> Path:
    """work/ holds editable copies; raw/ is never modified."""
    dst = work_path(session, sid)
    if not dst.exists():
        src = raw_path(session, sid)
        if not src.exists():
            raise SessionError(f"missing screenshot {src}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    return dst


def _point(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if not d or "x" not in d:
        return None
    return {k: d[k] for k in POINT_KEYS if k in d}


def step_from_event(ev: dict[str, Any], lang: str) -> dict[str, Any]:
    title = naming.auto_title(ev, lang)
    desc = naming.auto_description(ev, lang)
    sid = shot_id(ev.get("screenshot"))
    step: dict[str, Any] = {
        "id": f"s{int(ev['id']):04d}",
        "event_id": ev["id"],
        "kind": ev.get("kind"),
        "title": title,
        "description": desc,
        "auto": {"title": title, "description": desc},
        "screenshot": sid,
        "own_screenshot": sid,
        "image": f"{WORK_DIR}/{sid}.png" if sid else None,
        "rendered": None,
        "point": _point(ev) if ev.get("kind") != "manual" else None,
        "image_size": ev.get("image_size"),
        "window_title": ev.get("window_title"),
        "app_name": ev.get("app_name"),
    }
    for key in ("click_type", "direction", "keys"):
        if key in ev:
            step[key] = ev[key]
    if ev.get("kind") == "drag":
        step["from"] = _point(ev.get("from"))
        step["to"] = _point(ev.get("to"))
    return step


def create_steps(
    session: Path,
    meta: dict[str, Any],
    events: list[dict[str, Any]],
    lang: str,
    dedupe_threshold: float = dedupe.DEFAULT_THRESHOLD,
) -> dict[str, Any]:
    steps = [step_from_event(ev, lang) for ev in events if ev.get("kind")]

    cache: dict[str, Image.Image | None] = {}

    def load(sid: str) -> Image.Image | None:
        if sid not in cache:
            p = raw_path(session, sid)
            cache.clear()  # only the current candidate and base are needed
            cache[sid] = Image.open(p).convert("RGB") if p.exists() else None
        return cache[sid]

    mapping = dedupe.group_consecutive([s["screenshot"] for s in steps], load, dedupe_threshold)
    for s in steps:
        sid = s["screenshot"]
        if sid:
            s["screenshot"] = mapping.get(sid, sid)
            s["image"] = f"{WORK_DIR}/{s['screenshot']}.png"
    detect_boxes(session, steps)
    title = meta.get("title") or naming.text(lang, "default_title")
    return {
        "format": STEPS_FORMAT,
        "generator": f"stepcap {__version__}",
        "lang": lang,
        "title": title,
        "auto_title": title if not meta.get("title") else None,
        "steps": steps,
    }


def detect_boxes(session: Path, steps: list[dict[str, Any]]) -> int:
    """Auto-detect the clicked element's box for steps that have no box decision yet.

    ``box_source`` records who decided: ``auto`` (this function) or ``manual``
    (``stepcap edit``). Steps that already have one are left alone, so manual
    boxes and manual removals survive rebuilds. Detection reads ``raw/``, never
    the (possibly blurred) ``work/`` copy. Returns the number of steps updated.
    """
    cache: dict[str, Image.Image | None] = {}
    changed = 0
    for s in steps:
        if s.get("kind") not in BOX_KINDS or "box_source" in s:
            continue
        box = None
        sid, pt = s.get("screenshot"), s.get("point") or {}
        if sid and "img_x" in pt:
            if sid not in cache:
                cache.clear()
                p = raw_path(session, sid)
                cache[sid] = Image.open(p).convert("RGB") if p.exists() else None
            if cache[sid] is not None:
                box = detect_box(cache[sid], int(pt["img_x"]), int(pt["img_y"]))
        s["box"] = box
        s["box_source"] = "auto"
        changed += 1
    return changed


def refresh_auto_texts(
    doc: dict[str, Any], events: list[dict[str, Any]], lang: str
) -> dict[str, Any]:
    """Regenerate untouched auto texts for ``lang``; keep every human edit."""
    by_id = {ev.get("id"): ev for ev in events}
    for s in doc.get("steps", []):
        ev = by_id.get(s.get("event_id"))
        if ev is None:
            continue
        auto = s.setdefault("auto", {})
        new_title = naming.auto_title(ev, lang)
        new_desc = naming.auto_description(ev, lang)
        if s.get("title") == auto.get("title"):
            s["title"] = new_title
        if (s.get("description") or "") == (auto.get("description") or ""):
            s["description"] = new_desc
        auto["title"], auto["description"] = new_title, new_desc
    if doc.get("auto_title") and doc.get("title") == doc["auto_title"]:
        doc["title"] = doc["auto_title"] = naming.text(lang, "default_title")
    doc["lang"] = lang
    return doc


def validate_steps_doc(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict) or not isinstance(doc.get("steps"), list):
        raise SessionError(f"{STEPS_FILE} is not valid: expected an object with a 'steps' list")
    for i, s in enumerate(doc["steps"], 1):
        if not isinstance(s, dict) or not isinstance(s.get("title", ""), str):
            raise SessionError(f"{STEPS_FILE}: step {i} is not valid")
        if s.get("screenshot") is not None and not str(s["screenshot"]).isalnum():
            raise SessionError(f"{STEPS_FILE}: step {i} has an invalid screenshot id")
    return doc


def load_steps(session: Path) -> dict[str, Any] | None:
    p = session / STEPS_FILE
    if not p.exists():
        return None
    try:
        return validate_steps_doc(read_json(p))
    except ValueError as exc:
        raise SessionError(f"{p}: invalid JSON ({exc}); fix it or rebuild with --reset") from exc
