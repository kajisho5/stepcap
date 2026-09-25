"""Deterministic SKILL.md draft from a session (``--agent none``: no LLM, no network).

The draft is a faithful, generic description of one recorded run: goal (from
F7 notes), inputs (typed values become ``{{variables}}``), numbered steps with
the app, window, URL and an annotated screenshot, and fixed safety notes for
the agent. Generalising it is left to a person or ``--agent claude|codex``.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from stepcap import __version__
from stepcap.build import naming
from stepcap.build.steps import STEP_KINDS
from stepcap.redact import redact_text
from stepcap.skill import frontmatter
from stepcap.skill.validate import MAX_DESCRIPTION, MAX_NAME

DEFAULT_NAME = "recorded-procedure"
CONTEXT_KINDS = ("app_switch", "url", "clipboard", "terminal")
NOTES_FOR_AGENT = (
    "Prefer tools over replaying clicks: if a CLI, an API or a file edit gives the same result, "
    "use it. The screenshots show the intent of each step, not the only way to do it.",
    "Ask the user before anything destructive or hard to undo: deleting, sending, publishing, "
    "paying, changing permissions.",
    "Values written as `{{name}}` are inputs. Use the ones the user gave you; ask for missing ones "
    "instead of reusing the example from the recording.",
    "The recording is one run. Names, dates, positions and window titles will differ - match by "
    "meaning, and stop and ask when the screen does not look like the description.",
)


def slugify(text: str | None) -> str:
    """ASCII kebab-case skill name, or '' if nothing usable is left."""
    if not text:
        return ""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:MAX_NAME].strip("-")
    return slug


def choose_name(doc: dict[str, Any]) -> str:
    candidates = [doc.get("title")]
    candidates += [s.get("app_name") for s in doc.get("steps", [])]
    for c in candidates:
        slug = slugify(c)
        if len(slug) >= 3:
            return slug
    return DEFAULT_NAME


def _clean(text: Any) -> str:
    return redact_text(str(text)).strip() if text else ""


def _one_line(text: Any) -> str:
    return re.sub(r"\s+", " ", _clean(text))


def _apps(doc: dict[str, Any], events: list[dict[str, Any]]) -> list[str]:
    seen: dict[str, None] = {}
    for s in doc["steps"]:
        if s.get("app_name"):
            seen[_one_line(s["app_name"])] = None
    for ev in events:
        if ev.get("kind") == "app_switch" and ev.get("app_name"):
            seen.setdefault(_one_line(ev["app_name"]), None)
    return [a for a in seen if a]


# Clipboard changes are the result of the step before them (e.g. Ctrl+C); URLs and
# terminal commands are where / how the next step happens.
_AFTER_KINDS = ("clipboard",)
Attached = dict[str, list[dict[str, Any]]]


def _context_by_step(
    doc: dict[str, Any], events: list[dict[str, Any]]
) -> tuple[Attached, Attached, list[dict[str, Any]]]:
    """Return (before step, after step, after the last step) context events.

    Context events carry ``seq`` = the event id the next step received.
    """
    step_ids = sorted(
        (s["event_id"], s["id"]) for s in doc["steps"] if isinstance(s.get("event_id"), int)
    )
    before: Attached = {}
    after: Attached = {}
    trailing: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("kind") not in CONTEXT_KINDS or not isinstance(ev.get("seq"), int):
            continue
        if ev["kind"] in _AFTER_KINDS:
            prev = [sid for eid, sid in step_ids if eid < ev["seq"]]
            if prev:
                after.setdefault(prev[-1], []).append(ev)
                continue
        nxt = next((sid for eid, sid in step_ids if eid >= ev["seq"]), None)
        if nxt is None:
            trailing.append(ev)
        else:
            before.setdefault(nxt, []).append(ev)
    return before, after, trailing


def _context_line(ev: dict[str, Any]) -> str | None:
    kind = ev.get("kind")
    if kind == "url" and ev.get("url"):
        return f"Browser at `{_one_line(ev['url'])}`"
    if kind == "clipboard":
        preview = _one_line(ev.get("preview"))
        n = ev.get("chars", len(preview))
        return f"Copied {n} characters" + (f": `{preview}`" if preview else "")
    if kind == "terminal" and ev.get("command"):
        code = ev.get("exit")
        status = f" (exit status {code})" if isinstance(code, int) and code != 0 else ""
        return f"Ran in a terminal: `{_one_line(ev['command'])}`{status}"
    return None


def _where(step: dict[str, Any]) -> str:
    app, title = _one_line(step.get("app_name")), _one_line(step.get("window_title"))
    if app and title and app.casefold() not in title.casefold():
        return f'{app} - window "{title}"'
    if title:
        return f'window "{title}"'
    return app


def render(
    doc: dict[str, Any],
    events: list[dict[str, Any]],
    meta: dict[str, Any],
    name: str,
    refs: dict[str, str],
) -> str:
    """Return the SKILL.md text. ``refs`` maps step id -> relative image path."""
    by_event = {ev.get("id"): ev for ev in events}
    steps = [s for s in doc["steps"] if s.get("kind") in STEP_KINDS]
    title = _one_line(doc.get("title")) or "Recorded procedure"
    apps = _apps(doc, events)
    notes = []
    for s in steps:
        if s.get("kind") == "manual":
            note = _one_line(s.get("title"))
            if s.get("description"):
                note += f" - {_one_line(s['description'])}"
            if note:
                notes.append(note)

    in_apps = f" in {', '.join(apps[:4])}" if apps else ""
    stop = ".。!！?？"
    goal_hint = f" {notes[0].rstrip(stop)}." if notes else ""
    description = (
        f"{title.rstrip(stop)}.{goal_hint} Recorded procedure with {len(steps)} steps{in_apps}. "
        f'Use when the user asks to do "{title}" or a close variant of it.'
    )
    if len(description) > MAX_DESCRIPTION:
        description = description[: MAX_DESCRIPTION - 3].rstrip() + "..."
    started = str(meta.get("started") or "")[:10]
    head = frontmatter.dump(
        {
            "name": name,
            "description": description,
            "metadata": {
                "generator": f"stepcap {__version__}",
                "recorded": started or "unknown",
                "status": "draft",
            },
        }
    )

    out = [head, f"# {title}", ""]
    out += [
        "> Draft generated by stepcap from one recording. Check the Goal and Inputs, then",
        "> generalise the steps (or run `stepcap skill --agent claude|codex`).",
        "",
        "## Goal",
        "",
    ]
    if notes:
        out += [f"- {n}" for n in notes]
    else:
        out.append(
            "TODO: say what this procedure achieves and when to use it "
            "(press F7 while recording to add notes)."
        )
    out += ["", "## Inputs", ""]

    inputs = []
    for n, s in enumerate(steps, 1):
        inp = s.get("input")
        if s.get("kind") != "type" or not isinstance(inp, dict):
            continue
        ev = by_event.get(s.get("event_id"), {})
        example = _clean(ev.get("text")) if not ev.get("masked", True) else ""
        if inp.get("variable", True) or not example:
            where = _where(s)
            field = _one_line((s.get("element") or {}).get("name"))
            line = f"- `{{{{{inp.get('name', f'input_{n}')}}}}}` - typed "
            line += f'into "{field}" in step {n}' if field else f"in step {n}"
            line += f" ({where})" if where else ""
            if example:
                line += f"; example from the recording: `{_one_line(example)}`"
            else:
                chars = ev.get("chars")
                line += f"; value not recorded ({chars} characters)" if chars else ""
            inputs.append(line)
    out += inputs or ["None recorded."]
    out += ["", "## Steps", ""]

    ctx_before, ctx_after, trailing = _context_by_step(doc, events)
    lang = doc.get("lang") or "en"
    for n, s in enumerate(steps, 1):
        line = f"{n}. **{_one_line(s.get('title')) or 'Step'}**"
        desc = _one_line(s.get("description"))
        kind = s.get("kind")
        auto_desc = (s.get("auto") or {}).get("description")
        if desc and not (kind == "type" and s.get("description") == auto_desc):
            line += f" - {desc}"
        out.append(line)
        sub = [c for c in (_context_line(ev) for ev in ctx_before.get(s["id"], [])) if c]
        where = _where(s)
        window = _one_line(s.get("window_title"))
        if where and kind != "manual" and not (window and window in _one_line(s.get("title"))):
            sub.append(f"Where: {where}")
        ev = by_event.get(s.get("event_id"), {})
        if kind == "type":
            inp = s.get("input") or {}
            example = _clean(ev.get("text")) if not ev.get("masked", True) else ""
            if inp.get("variable", True) or not example:
                value = f"`{{{{{inp.get('name', 'value')}}}}}`"
            else:
                value = f"`{_one_line(example)}`"
            sub.append(f"Enter {value}" + (", then press Enter" if ev.get("enter") else ""))
        elif kind == "key" and s.get("keys"):
            sub.append(f"Keys: `{naming.format_keys(s['keys'])}`")
        elif kind == "scroll" and s.get("direction"):
            sub.append(f"Scroll {s['direction']} until the target is visible")
        elif kind == "drag":
            sub.append("Drag from the marked element to the drop target shown")
        for c in (_context_line(e) for e in ctx_after.get(s["id"], [])):
            if c:
                sub.append(f"Then: {c[0].lower()}{c[1:]}")
        if s["id"] in refs:
            sub.append(f"Screenshot: [{refs[s['id']]}]({refs[s['id']]})")
        out += [f"   - {c}" for c in sub]
    tail = [c for c in (_context_line(ev) for ev in trailing) if c]
    if tail:
        out += ["", "After the last step:", ""] + [f"- {c}" for c in tail]

    out += ["", "## Notes for the agent", ""]
    out += [f"- {n}" for n in NOTES_FOR_AGENT]
    out += [
        "",
        f"<!-- generated by stepcap {__version__} ({lang}); screenshots are annotated: a numbered "
        "frame or ring marks the clicked element -->",
        "",
    ]
    return "\n".join(out)
