"""`stepcap simulate`: build a session from synthetic events (tests, CI, demos).

Screens are drawn with Pillow from a small JSON description, and the input is
replayed through the same ``EventProcessor`` the real recorder uses, so
debounce / drag / scroll / masking behave exactly as in a real recording.

EVENTS.json::

    {
      "title": "Create a project",                 # optional guide title
      "screen": {"width": 1440, "height": 900},    # virtual monitor size
      "screens": {
        "home": {
          "app": "Acme Tasks", "window_title": "Acme Tasks — Projects",
          "sidebar": ["Inbox", "Projects"], "sidebar_active": "Projects",
          "heading": "Projects",
          "widgets": [
            {"id": "new", "type": "button", "label": "New project",
             "rect": [1180, 100, 180, 44], "primary": true},
            {"type": "input", "id": "search", "placeholder": "Search", "rect": [...]},
            {"type": "list", "rect": [...], "items": ["a", "b"]},
            {"type": "card", "id": "c1", "rect": [...], "label": "Draft", "badge": "To do"},
            {"type": "column", "rect": [...], "label": "To do"},
            {"type": "checkbox", "id": "private", "label": "Private", "rect": [...]},
            {"type": "select", "id": "tpl", "label": "Template", "value": "Blank", "rect": [...]},
            {"type": "text", "text": "Hello", "at": [x, y], "size": 16, "color": "#555"},
            {"type": "menu", "rect": [...], "items": ["Rename", "Delete"]}
          ]
        },
        "dialog": {"base": "home", "dialog": {"title": "New project", "rect": [...]},
                   "widgets": [...]}
      },
      "events": [
        {"kind": "click", "screen": "home", "target": "new"},
        {"kind": "double_click" | "right_click", "screen": "...", "target": "..."},
        {"kind": "type", "screen": "...", "target": "name", "text": "abc", "enter": false},
        {"kind": "drag", "screen": "...", "from": "c1", "to": [x, y]},
        {"kind": "scroll", "screen": "...", "target": "list", "dy": -3},
        {"kind": "key", "screen": "...", "keys": "ctrl+s"},
        {"kind": "manual", "screen": "...", "note": "Check the result"},
        {"kind": "copy", "screen": "...", "text": "copied text"}
      ]
    }

A screen may set ``"url": "https://..."`` (recorded with ``record_urls``) and
``"monitor": 1`` (index into an optional top-level ``"monitors"`` list of
``{"left", "top", "scale"}``; every monitor has the ``screen`` size in logical
points, and ``scale`` 2.0 gives Retina-like screenshots with twice the pixels).

``target`` / ``from`` / ``to`` accept a widget id or ``[x, y]``. Each event
may set ``t`` (seconds); otherwise events are 1.5 s apart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from stepcap.build.annotate import font
from stepcap.capture.events import EventProcessor, Monitor, ProcessorOptions, Shot, WindowInfo
from stepcap.session import (
    EVENTS_FILE,
    RAW_DIR,
    SESSION_FILE,
    EventWriter,
    SessionError,
    base_meta,
    now_iso,
    prepare_new_session,
    write_json,
)

TITLEBAR = 38
C = {
    "desk": "#dfe3ea",
    "bg": "#ffffff",
    "chrome": "#eceef2",
    "line": "#d7dbe2",
    "text": "#1f2329",
    "muted": "#6a7280",
    "sidebar": "#f4f5f8",
    "active": "#e4e9ff",
    "primary": "#3355ff",
    "primary_text": "#ffffff",
    "card": "#ffffff",
    "column": "#f1f3f6",
    "badge": "#eef1ff",
    "dim": (20, 24, 32, 110),
}


class SimulationError(SessionError):
    pass


@dataclass
class _State:
    values: dict[str, str]
    checked: dict[str, bool]


def _rect(w: dict[str, Any]) -> tuple[int, int, int, int]:
    x, y, ww, hh = w["rect"]
    return int(x), int(y), int(x + ww), int(y + hh)


def _center(w: dict[str, Any]) -> tuple[float, float]:
    x0, y0, x1, y1 = _rect(w)
    return (x0 + x1) / 2, (y0 + y1) / 2


class ScreenRenderer:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        screen = spec.get("screen") or {}
        self.width = int(screen.get("width", 1440))
        self.height = int(screen.get("height", 900))
        self.screens: dict[str, dict[str, Any]] = spec.get("screens") or {}
        if not self.screens:
            raise SimulationError("EVENTS.json: 'screens' must define at least one screen")
        mons = spec.get("monitors") or [{}]
        if not isinstance(mons, list) or not all(isinstance(m, dict) for m in mons):
            raise SimulationError("EVENTS.json: 'monitors' must be a list of objects")
        self.monitors = [
            Monitor(i + 1, int(m.get("left", 0)), int(m.get("top", 0)), self.width, self.height)
            for i, m in enumerate(mons)
        ]
        self.scales = [float(m.get("scale", 1.0)) for m in mons]
        if any(not 0.5 <= sc <= 4 for sc in self.scales):
            raise SimulationError("EVENTS.json: monitor scale must be between 0.5 and 4")

    def monitor_index(self, name: str) -> int:
        idx = self.screen(name).get("monitor", 0)
        if not isinstance(idx, int) or not 0 <= idx < len(self.monitors):
            raise SimulationError(f"EVENTS.json: screen {name!r} has an invalid monitor index")
        return idx

    def url(self, name: str) -> str | None:
        sc = self.screen(name)
        if sc.get("url"):
            return str(sc["url"])
        return self.url(sc["base"]) if sc.get("base") else None

    def screen(self, name: str) -> dict[str, Any]:
        if name not in self.screens:
            raise SimulationError(f"EVENTS.json: unknown screen {name!r}")
        return self.screens[name]

    def widgets(self, name: str) -> list[dict[str, Any]]:
        sc = self.screen(name)
        out = list(self.widgets(sc["base"])) if sc.get("base") else []
        return out + list(sc.get("widgets") or [])

    def widget(self, screen: str, wid: str) -> dict[str, Any]:
        for w in reversed(self.widgets(screen)):
            if w.get("id") == wid:
                return w
        raise SimulationError(f"EVENTS.json: no widget {wid!r} on screen {screen!r}")

    def resolve(self, screen: str, target: Any) -> tuple[float, float]:
        """Global (virtual desktop) coordinates of a target on ``screen``."""
        m = self.monitors[self.monitor_index(screen)]
        if isinstance(target, (list, tuple)) and len(target) == 2:
            x, y = float(target[0]), float(target[1])
        elif isinstance(target, str):
            x, y = _center(self.widget(screen, target))
        else:
            x, y = self.width / 2, self.height / 2
        return x + m.left, y + m.top

    # ------------------------------------------------------------------ drawing
    def render(self, name: str, state: _State) -> Image.Image:
        img = Image.new("RGB", (self.width, self.height), C["bg"])
        self._draw_screen(img, name, state, top=True)
        return img

    def _draw_screen(self, img: Image.Image, name: str, state: _State, top: bool) -> None:
        sc = self.screen(name)
        if sc.get("base"):
            self._draw_screen(img, sc["base"], state, top=False)
            if sc.get("dialog"):
                overlay = Image.new("RGBA", img.size, C["dim"])
                base = img.convert("RGBA")
                base.alpha_composite(overlay)
                img.paste(base.convert("RGB"))
        else:
            self._draw_frame(img, sc)
        d = ImageDraw.Draw(img)
        if sc.get("dialog"):
            dl = sc["dialog"]
            x0, y0, x1, y1 = _rect(dl)
            d.rounded_rectangle((x0 + 4, y0 + 6, x1 + 4, y1 + 6), 14, fill="#9aa0ab")
            d.rounded_rectangle((x0, y0, x1, y1), 14, fill=C["bg"], outline=C["line"])
            d.text((x0 + 28, y0 + 26), dl.get("title", ""), font=font(24), fill=C["text"])
        for w in sc.get("widgets") or []:
            self._draw_widget(d, w, state)
        if top:
            # the title bar always shows the foreground window's title
            self._draw_titlebar(d, sc)

    def _draw_frame(self, img: Image.Image, sc: dict[str, Any]) -> None:
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, self.width, self.height), fill=C["bg"])
        side = sc.get("sidebar")
        if side:
            d.rectangle((0, TITLEBAR, 240, self.height), fill=C["sidebar"])
            d.line((240, TITLEBAR, 240, self.height), fill=C["line"])
            d.text((24, TITLEBAR + 22), sc.get("app", ""), font=font(20), fill=C["text"])
            for i, item in enumerate(side):
                y = TITLEBAR + 76 + i * 44
                if item == sc.get("sidebar_active"):
                    d.rounded_rectangle((12, y - 8, 228, y + 30), 8, fill=C["active"])
                d.ellipse((28, y + 4, 40, y + 16), outline=C["muted"], width=2)
                d.text((54, y), item, font=font(17), fill=C["text"])
        if sc.get("heading"):
            x = 272 if side else 32
            d.text((x, TITLEBAR + 28), sc["heading"], font=font(30), fill=C["text"])
            d.line((x, TITLEBAR + 80, self.width - 32, TITLEBAR + 80), fill=C["line"])

    def _draw_titlebar(self, d: ImageDraw.ImageDraw, sc: dict[str, Any]) -> None:
        d.rectangle((0, 0, self.width, TITLEBAR), fill=C["chrome"])
        d.line((0, TITLEBAR, self.width, TITLEBAR), fill=C["line"])
        for i, col in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            d.ellipse((16 + i * 22, 13, 28 + i * 22, 25), fill=col)
        d.text(
            (self.width / 2, TITLEBAR / 2),
            sc.get("window_title", ""),
            font=font(15),
            fill=C["muted"],
            anchor="mm",
        )

    def _draw_widget(self, d: ImageDraw.ImageDraw, w: dict[str, Any], state: _State) -> None:
        t = w.get("type")
        if t == "text":
            d.text(
                tuple(w["at"]),
                w.get("text", ""),
                font=font(w.get("size", 16)),
                fill=w.get("color", C["text"]),
            )
            return
        x0, y0, x1, y1 = _rect(w)
        cy = (y0 + y1) / 2
        if t == "button":
            primary = w.get("primary")
            d.rounded_rectangle(
                (x0, y0, x1, y1),
                8,
                fill=C["primary"] if primary else C["bg"],
                outline=C["primary"] if primary else C["line"],
                width=1,
            )
            d.text(
                ((x0 + x1) / 2, cy),
                w.get("label", ""),
                font=font(17),
                fill=C["primary_text"] if primary else C["text"],
                anchor="mm",
            )
        elif t in ("input", "select"):
            if w.get("label"):
                d.text((x0, y0 - 26), w["label"], font=font(15), fill=C["muted"])
            d.rounded_rectangle((x0, y0, x1, y1), 8, fill=C["bg"], outline=C["line"], width=2)
            value = state.values.get(w.get("id", ""), w.get("value", ""))
            if value:
                d.text((x0 + 14, cy), value, font=font(17), fill=C["text"], anchor="lm")
            elif w.get("placeholder"):
                d.text((x0 + 14, cy), w["placeholder"], font=font(17), fill="#a0a6b1", anchor="lm")
            if t == "select":
                d.polygon(
                    [(x1 - 28, cy - 4), (x1 - 16, cy - 4), (x1 - 22, cy + 4)], fill=C["muted"]
                )
        elif t == "checkbox":
            checked = state.checked.get(w.get("id", ""), bool(w.get("checked")))
            s = y1 - y0
            d.rounded_rectangle(
                (x0, y0, x0 + s, y1),
                5,
                fill=C["primary"] if checked else C["bg"],
                outline=C["primary"] if checked else C["muted"],
                width=2,
            )
            if checked:
                d.line(
                    [(x0 + 5, cy), (x0 + s / 2 - 1, y1 - 6), (x0 + s - 5, y0 + 6)],
                    fill="#fff",
                    width=3,
                )
            d.text(
                (x0 + s + 12, cy), w.get("label", ""), font=font(17), fill=C["text"], anchor="lm"
            )
        elif t == "list":
            items = w.get("items") or []
            row = int(w.get("row", 52))
            for i, item in enumerate(items):
                ry = y0 + i * row
                if ry + row > y1:
                    break
                d.line((x0, ry + row, x1, ry + row), fill=C["line"])
                d.rounded_rectangle((x0 + 8, ry + 14, x0 + 32, ry + 38), 6, fill=C["badge"])
                d.text((x0 + 48, ry + row / 2), item, font=font(17), fill=C["text"], anchor="lm")
        elif t == "column":
            d.rounded_rectangle((x0, y0, x1, y1), 12, fill=C["column"])
            d.text((x0 + 16, y0 + 16), w.get("label", ""), font=font(16), fill=C["muted"])
        elif t == "card":
            d.rounded_rectangle((x0, y0 + 3, x1, y1 + 3), 10, fill="#e2e5ea")
            d.rounded_rectangle((x0, y0, x1, y1), 10, fill=C["card"], outline=C["line"])
            label = state.values.get(w.get("id", ""), w.get("label", ""))
            d.text((x0 + 16, y0 + 16), label, font=font(17), fill=C["text"])
            if w.get("badge"):
                d.rounded_rectangle((x0 + 16, y1 - 34, x0 + 110, y1 - 12), 11, fill=C["badge"])
                d.text(
                    (x0 + 63, y1 - 23), w["badge"], font=font(13), fill=C["primary"], anchor="mm"
                )
        elif t == "menu":
            d.rounded_rectangle((x0 + 3, y0 + 4, x1 + 3, y1 + 4), 8, fill="#c9cdd4")
            d.rounded_rectangle((x0, y0, x1, y1), 8, fill=C["bg"], outline=C["line"])
            for i, item in enumerate(w.get("items") or []):
                d.text((x0 + 16, y0 + 12 + i * 34), item, font=font(16), fill=C["text"])
        else:
            d.rectangle((x0, y0, x1, y1), outline=C["line"])


def load_spec(path: Path) -> dict[str, Any]:
    try:
        spec = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SimulationError(f"{path} not found") from exc
    except json.JSONDecodeError as exc:
        raise SimulationError(f"{path}: invalid JSON ({exc})") from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("events"), list):
        raise SimulationError(f"{path}: expected an object with an 'events' list")
    return spec


def simulate(
    spec: dict[str, Any],
    out_dir: Path,
    record_typing: bool = False,
    exclude_apps: tuple[str, ...] = (),
    record_urls: bool = False,
    keep_query: bool = False,
    record_clipboard: bool = False,
) -> dict[str, Any]:
    renderer = ScreenRenderer(spec)
    out = prepare_new_session(out_dir)
    options = {
        "monitor": "active",
        "record_typing": record_typing,
        "exclude_apps": list(exclude_apps),
        "record_urls": record_urls,
        "keep_query": keep_query,
        "record_clipboard": record_clipboard,
    }
    meta = base_meta("simulate", options)
    meta["monitors"] = [m.to_dict() for m in renderer.monitors]
    if spec.get("title"):
        meta["title"] = spec["title"]

    state = _State(values={}, checked={})
    current = {"screen": next(iter(renderer.screens))}
    n_shots = 0

    def capture(x: float, y: float, ts: float) -> Shot:
        nonlocal n_shots
        n_shots += 1
        sid = f"{n_shots:04d}"
        idx = renderer.monitor_index(current["screen"])
        img = renderer.render(current["screen"], state)
        scale = renderer.scales[idx]
        if scale != 1.0:
            size = (round(img.width * scale), round(img.height * scale))
            img = img.resize(size, Image.Resampling.BICUBIC)
        img.save(out / RAW_DIR / f"{sid}.png", format="PNG", compress_level=1)
        return Shot(
            id=sid,
            path=f"{RAW_DIR}/{sid}.png",
            monitor=renderer.monitors[idx],
            width=img.width,
            height=img.height,
        )

    def window() -> WindowInfo:
        sc = renderer.screen(current["screen"])
        return WindowInfo(title=sc.get("window_title"), app=sc.get("app"))

    writer = EventWriter(out / EVENTS_FILE)
    n_context = 0

    def emit(ev: dict[str, Any]) -> None:
        nonlocal n_context
        n_context += "id" not in ev  # context events (app switch, URL, clipboard)
        writer.write(ev)

    proc = EventProcessor(
        capture,
        window,
        emit,
        ProcessorOptions(
            record_typing=record_typing,
            exclude_apps=tuple(exclude_apps),
            record_urls=record_urls,
            keep_query=keep_query,
            record_clipboard=record_clipboard,
        ),
    )
    proc.observe_clipboard(0.0, "", window())  # clipboard is empty when recording starts
    t = 0.0
    try:
        for i, ev in enumerate(spec["events"], 1):
            if not isinstance(ev, dict) or "kind" not in ev:
                raise SimulationError(f"EVENTS.json: event {i} needs a 'kind'")
            t = float(ev["t"]) if "t" in ev else t + 1.5
            screen = ev.get("screen", current["screen"])
            renderer.screen(screen)
            current["screen"] = screen
            proc.observe(t - 0.05, window(), renderer.url(screen))
            _replay(proc, renderer, state, screen, ev, t, i)
        proc.tick(t + 10)
        proc.flush()
    finally:
        writer.close()
    meta["ended"] = now_iso()
    meta["stats"] = {
        "events": writer.count - n_context,
        "context_events": n_context,
        "screenshots": n_shots,
        "excluded": proc.excluded_count,
    }
    write_json(out / SESSION_FILE, meta)
    return {
        "session": str(out),
        "events": writer.count - n_context,
        "context_events": n_context,
        "screenshots": n_shots,
    }


def _replay(
    proc: EventProcessor,
    r: ScreenRenderer,
    state: _State,
    screen: str,
    ev: dict[str, Any],
    t: float,
    i: int,
) -> None:
    kind = ev["kind"]
    target = ev.get("target")
    if kind in ("click", "double_click", "right_click", "middle_click"):
        x, y = r.resolve(screen, target if target is not None else [ev.get("x"), ev.get("y")])
        button = {"right_click": "right", "middle_click": "middle"}.get(kind, "left")
        proc.on_mouse(t, x, y, button, True)
        proc.on_mouse(t + 0.08, x, y, button, False)
        if kind == "double_click":
            proc.on_mouse(t + 0.14, x, y, button, True)
            proc.on_mouse(t + 0.2, x, y, button, False)
        proc.tick(t + 0.6)
        if isinstance(target, str):
            w = r.widget(screen, target)
            if w.get("type") == "checkbox":
                state.checked[target] = not state.checked.get(target, bool(w.get("checked")))
    elif kind == "drag":
        x1, y1 = r.resolve(screen, ev.get("from"))
        x2, y2 = r.resolve(screen, ev.get("to"))
        proc.on_mouse(t, x1, y1, "left", True)
        proc.on_mouse(t + 0.7, x2, y2, "left", False)
    elif kind == "scroll":
        x, y = r.resolve(screen, target)
        dy = float(ev.get("dy", -3))
        dx = float(ev.get("dx", 0))
        steps = int(max(abs(dy), abs(dx), 1))
        for k in range(steps):
            proc.on_scroll(t + k * 0.05, x, y, dx / steps, dy / steps)
        proc.tick(t + steps * 0.05 + 2)
    elif kind == "type":
        pos = r.resolve(screen, target)
        txt = str(ev.get("text", ""))
        for k, ch in enumerate(txt):
            proc.on_key(t + k * 0.06, "space" if ch == " " else ch, True, pos=pos)
        if ev.get("enter"):
            proc.on_key(t + len(txt) * 0.06, "enter", True, pos=pos)
        else:
            proc.flush()
        if isinstance(target, str):
            state.values[target] = txt
    elif kind == "key":
        pos = r.resolve(screen, target) if target is not None else None
        parts = str(ev.get("keys", "")).lower().split("+")
        *mods, key = parts
        for m in mods:
            proc.on_key(t, m, True, pos=pos)
        proc.on_key(t + 0.02, key, True, pos=pos)
        for m in mods:
            proc.on_key(t + 0.04, m, False, pos=pos)
    elif kind == "manual":
        pos = r.resolve(screen, target) if target is not None else None
        token = proc.manual_capture(t, pos)
        proc.manual_commit(token, str(ev.get("note", "")))
    elif kind == "copy":
        sc = r.screen(screen)
        win = WindowInfo(title=sc.get("window_title"), app=sc.get("app"))
        proc.observe_clipboard(t, str(ev.get("text", "")), win)
    else:
        raise SimulationError(f"EVENTS.json: event {i} has unknown kind {kind!r}")
