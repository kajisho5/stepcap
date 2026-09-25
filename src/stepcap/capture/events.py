"""Turn low-level input (press/release/scroll/key) into high-level steps.

This module is pure logic: it never touches the OS. The recorder feeds it
events from global hooks and ``simulate`` feeds it synthetic ones, so both
paths share exactly the same debounce / drag / scroll / masking behaviour.

Timestamps are seconds (float) on any monotonic clock.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from stepcap.redact import redact_text

# Window titles that force typed content to be masked even with --record-typing.
SENSITIVE_TITLE_PATTERNS = (
    "password",
    "passwd",
    "passcode",
    "パスワード",
    "1password",
    "bitwarden",
    "keepass",
    "lastpass",
    "keychain",
    "キーチェーン",
    "sign in",
    "sign-in",
    "signin",
    "log in",
    "login",
    "ログイン",
    "サインイン",
)

MODIFIERS = frozenset({"ctrl", "alt", "cmd", "shift"})
# Special keys that become their own step when pressed outside of typing.
STEP_KEYS = frozenset({"enter", "esc"})
DEFAULT_DOUBLE_CLICK_S = 0.150
DEFAULT_DRAG_THRESHOLD_PX = 12.0
DEFAULT_SCROLL_GAP_S = 0.8
CLIPBOARD_PREVIEW = 80


def normalise_url(url: str, keep_query: bool = False) -> str | None:
    """Drop query and fragment (unless ``keep_query``) and any user:password@."""
    url = (url or "").strip()
    if not url or len(url) > 4096:
        return None
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if not parts.scheme:
        return None
    netloc = parts.netloc.rsplit("@", 1)[-1]
    if keep_query:
        return redact_text(urlunsplit((parts.scheme, netloc, parts.path, parts.query, "")))
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def is_sensitive_title(title: str | None) -> bool:
    if not title:
        return False
    low = title.casefold()
    return any(p in low for p in SENSITIVE_TITLE_PATTERNS)


@dataclass(frozen=True)
class Monitor:
    index: int
    left: int
    top: int
    width: int
    height: int

    def contains(self, x: float, y: float) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height

    def to_dict(self) -> dict[str, int]:
        return {
            "index": self.index,
            "left": self.left,
            "top": self.top,
            "width": self.width,
            "height": self.height,
        }


def pick_monitor(monitors: list[Monitor], x: float, y: float) -> Monitor:
    """Return the monitor containing (x, y), or the nearest one."""
    for m in monitors:
        if m.contains(x, y):
            return m

    def dist(m: Monitor) -> float:
        cx = min(max(x, m.left), m.left + m.width - 1)
        cy = min(max(y, m.top), m.top + m.height - 1)
        return math.hypot(x - cx, y - cy)

    return min(monitors, key=dist)


@dataclass
class Shot:
    """A screenshot handle. Pixels may be written asynchronously by the caller."""

    id: str  # "0001"
    path: str  # relative to the session dir, e.g. "raw/0001.png"
    monitor: Monitor
    width: int  # image pixels
    height: int

    @property
    def scale_x(self) -> float:
        return self.width / self.monitor.width if self.monitor.width else 1.0

    @property
    def scale_y(self) -> float:
        return self.height / self.monitor.height if self.monitor.height else 1.0

    def point(self, x: float, y: float) -> dict[str, Any]:
        rel_x, rel_y = x - self.monitor.left, y - self.monitor.top
        img_x = min(max(round(rel_x * self.scale_x), 0), self.width - 1)
        img_y = min(max(round(rel_y * self.scale_y), 0), self.height - 1)
        return {
            "x": round(x),
            "y": round(y),
            "rel_x": round(rel_x),
            "rel_y": round(rel_y),
            "img_x": img_x,
            "img_y": img_y,
        }


@dataclass
class WindowInfo:
    title: str | None = None
    app: str | None = None


CaptureFn = Callable[[float, float, float], "Shot | None"]  # (x, y, ts) -> Shot
WindowFn = Callable[[], WindowInfo]
EmitFn = Callable[[dict[str, Any]], None]


@dataclass
class _PendingClick:
    ts: float
    x: float
    y: float
    button: str
    shot: Shot | None
    win: WindowInfo
    count: int = 1
    released: bool = False
    release_ts: float = 0.0


@dataclass
class _ScrollRun:
    ts: float
    last_ts: float
    x: float
    y: float
    shot: Shot | None
    win: WindowInfo
    ignored: bool
    dx: float = 0.0
    dy: float = 0.0


@dataclass
class _TypingRun:
    ts: float
    x: float
    y: float
    shot: Shot | None
    win: WindowInfo
    ignored: bool
    masked: bool
    chars: int = 0
    text: list[str] = field(default_factory=list)
    enter: bool = False


@dataclass
class ProcessorOptions:
    record_typing: bool = False
    exclude_apps: tuple[str, ...] = ()
    double_click_s: float = DEFAULT_DOUBLE_CLICK_S
    drag_threshold_px: float = DEFAULT_DRAG_THRESHOLD_PX
    scroll_gap_s: float = DEFAULT_SCROLL_GAP_S
    record_urls: bool = False
    keep_query: bool = False
    record_clipboard: bool = False


class EventProcessor:
    """State machine from raw input to step events.

    Emitted events are plain dicts, ready to be written as JSON lines.
    """

    def __init__(
        self,
        capture: CaptureFn,
        window: WindowFn,
        emit: EmitFn,
        options: ProcessorOptions | None = None,
        t0: float = 0.0,
    ) -> None:
        self.capture = capture
        self.window = window
        self._emit_cb = emit
        self.opt = options or ProcessorOptions()
        self.t0 = t0
        self._next_id = 1
        self._click: _PendingClick | None = None
        self._ignored_buttons: set[str] = set()
        self._scroll: _ScrollRun | None = None
        self._typing: _TypingRun | None = None
        self._mods: set[str] = set()
        self.last_pos: tuple[float, float] | None = None
        self.excluded_count = 0
        self._last_win: tuple[str | None, str | None] | None = None
        self._last_url: str | None = None
        self._clip: str | None = None
        self._clip_seen = False
        # Screen rectangles (x, y, w, h) whose clicks/scrolls are ignored: the
        # `stepcap app` control bar, so pressing Stop is not a step.
        self.ignore_rects: list[tuple[float, float, float, float]] = []

    # ------------------------------------------------------------------ helpers
    def is_excluded(self, win: WindowInfo) -> bool:
        if not self.opt.exclude_apps:
            return False
        hay = [s.casefold() for s in (win.app, win.title) if s]
        return any(pat.casefold() in h for pat in self.opt.exclude_apps for h in hay)

    def _base(self, kind: str, ts: float, win: WindowInfo, shot: Shot | None) -> dict[str, Any]:
        ev: dict[str, Any] = {
            "id": self._next_id,
            "ts": round(ts - self.t0, 3),
            "kind": kind,
            "window_title": win.title,
            "app_name": win.app,
            "screenshot": shot.path if shot else None,
        }
        if shot:
            ev["monitor"] = shot.monitor.to_dict()
            ev["image_size"] = [shot.width, shot.height]
        self._next_id += 1
        return ev

    def _with_point(self, ev: dict[str, Any], shot: Shot | None, x: float, y: float) -> None:
        if shot:
            ev.update(shot.point(x, y))
        else:
            ev.update({"x": round(x), "y": round(y)})

    def _emit(self, ev: dict[str, Any]) -> None:
        self._emit_cb(ev)

    def in_ignored_rect(self, x: float, y: float) -> bool:
        return any(rx <= x < rx + rw and ry <= y < ry + rh for rx, ry, rw, rh in self.ignore_rects)

    def _pos(self, pos: tuple[float, float] | None) -> tuple[float, float]:
        if pos is not None:
            return pos
        return self.last_pos if self.last_pos is not None else (0.0, 0.0)

    # ------------------------------------------------------------------ flushing
    def _flush_click(self) -> None:
        c = self._click
        if c is None:
            return
        self._click = None
        if c.count >= 2:
            click_type = "double"
        elif c.button == "right":
            click_type = "right"
        elif c.button == "middle":
            click_type = "middle"
        else:
            click_type = "single"
        ev = self._base("click", c.ts, c.win, c.shot)
        ev["button"] = c.button
        ev["click_type"] = click_type
        self._with_point(ev, c.shot, c.x, c.y)
        self._emit(ev)

    def _flush_scroll(self) -> None:
        s = self._scroll
        if s is None:
            return
        self._scroll = None
        if s.ignored:
            return
        if abs(s.dy) >= abs(s.dx):
            direction = "up" if s.dy > 0 else "down"
            amount = abs(s.dy)
        else:
            direction = "right" if s.dx > 0 else "left"
            amount = abs(s.dx)
        ev = self._base("scroll", s.ts, s.win, s.shot)
        ev["direction"] = direction
        ev["amount"] = round(amount, 2) if amount % 1 else int(amount)
        self._with_point(ev, s.shot, s.x, s.y)
        self._emit(ev)

    def _flush_typing(self) -> None:
        t = self._typing
        if t is None:
            return
        self._typing = None
        if t.ignored or (t.chars == 0 and not t.enter):
            return
        ev = self._base("type", t.ts, t.win, t.shot)
        ev["chars"] = t.chars
        ev["enter"] = t.enter
        ev["masked"] = t.masked
        if not t.masked:
            ev["text"] = "".join(t.text)
        self._with_point(ev, t.shot, t.x, t.y)
        self._emit(ev)

    def flush(self) -> None:
        """Emit everything still pending (call on stop)."""
        self._flush_click()
        self._flush_scroll()
        self._flush_typing()

    def tick(self, now: float) -> None:
        """Emit time-based events whose window has closed."""
        c = self._click
        if c and c.released and c.count == 1 and now - c.release_ts > self.opt.double_click_s:
            self._flush_click()
        s = self._scroll
        if s and now - s.last_ts > self.opt.scroll_gap_s:
            self._flush_scroll()

    # ------------------------------------------------------------------ mouse
    def on_mouse(self, ts: float, x: float, y: float, button: str, pressed: bool) -> None:
        self.tick(ts)
        if pressed:
            self._on_press(ts, x, y, button)
        else:
            self._on_release(ts, x, y, button)

    def _on_press(self, ts: float, x: float, y: float, button: str) -> None:
        self.last_pos = (x, y)
        self._flush_typing()
        self._flush_scroll()
        c = self._click
        if (
            c is not None
            and button == "left"
            and c.button == "left"
            and c.count == 1
            and c.released
            and ts - c.release_ts <= self.opt.double_click_s
            and math.hypot(x - c.x, y - c.y) <= self.opt.drag_threshold_px
        ):
            c.count = 2
            c.released = False
            return
        self._flush_click()
        if self.in_ignored_rect(x, y):
            self._ignored_buttons.add(button)
            return
        win = self.window()
        if self.is_excluded(win):
            self._ignored_buttons.add(button)
            self.excluded_count += 1
            return
        self._ignored_buttons.discard(button)
        shot = self.capture(x, y, ts)
        self._click = _PendingClick(ts=ts, x=x, y=y, button=button, shot=shot, win=win)

    def _on_release(self, ts: float, x: float, y: float, button: str) -> None:
        self.last_pos = (x, y)
        if button in self._ignored_buttons:
            self._ignored_buttons.discard(button)
            return
        c = self._click
        if c is None or c.button != button or c.released:
            return
        if c.count >= 2:
            self._flush_click()
            return
        if math.hypot(x - c.x, y - c.y) > self.opt.drag_threshold_px:
            self._click = None
            ev = self._base("drag", c.ts, c.win, c.shot)
            ev["button"] = c.button
            self._with_point(ev, c.shot, c.x, c.y)
            if c.shot:
                ev["from"] = c.shot.point(c.x, c.y)
                ev["to"] = c.shot.point(x, y)
            else:
                ev["from"] = {"x": round(c.x), "y": round(c.y)}
                ev["to"] = {"x": round(x), "y": round(y)}
            self._emit(ev)
            return
        if button != "left":
            self._flush_click()
            return
        c.released = True
        c.release_ts = ts

    def on_scroll(self, ts: float, x: float, y: float, dx: float, dy: float) -> None:
        self.tick(ts)
        if self.in_ignored_rect(x, y):
            return
        self.last_pos = (x, y)
        self._flush_click()
        self._flush_typing()
        s = self._scroll
        if s is not None:
            same_dir = (dy == 0 or s.dy == 0 or (dy > 0) == (s.dy > 0)) and (
                dx == 0 or s.dx == 0 or (dx > 0) == (s.dx > 0)
            )
            if ts - s.last_ts <= self.opt.scroll_gap_s and same_dir:
                s.dx += dx
                s.dy += dy
                s.last_ts = ts
                return
            self._flush_scroll()
        win = self.window()
        ignored = self.is_excluded(win)
        if ignored:
            self.excluded_count += 1
        shot = None if ignored else self.capture(x, y, ts)
        self._scroll = _ScrollRun(
            ts=ts, last_ts=ts, x=x, y=y, shot=shot, win=win, ignored=ignored, dx=dx, dy=dy
        )

    # ------------------------------------------------------------------ keyboard
    def on_key(
        self,
        ts: float,
        key: str,
        pressed: bool = True,
        pos: tuple[float, float] | None = None,
    ) -> None:
        """Feed a key event.

        ``key`` is either a single printable character (``"a"``, ``" "``) or a
        lower-case special key name (``"enter"``, ``"ctrl"``, ``"backspace"``...).
        """
        self.tick(ts)
        if key in MODIFIERS:
            if pressed:
                self._mods.add(key)
            else:
                self._mods.discard(key)
            return
        if not pressed:
            return

        printable = len(key) == 1 or key == "space"
        combo_mods = self._mods - {"shift"}
        if combo_mods and (printable or key not in {"backspace", "tab"}):
            self._key_step(ts, "+".join([*sorted(combo_mods), key]), pos)
            return

        if printable:
            self._flush_click()
            self._flush_scroll()
            run = self._typing or self._start_typing(ts, pos)
            run.chars += 1
            if not run.masked and not run.ignored:
                run.text.append(" " if key == "space" else key)
            return
        if key == "backspace":
            if self._typing is not None:
                self._typing.chars = max(0, self._typing.chars - 1)
                if self._typing.text:
                    self._typing.text.pop()
            return
        if key == "tab":
            self._flush_typing()
            return
        if key == "enter" and self._typing is not None:
            self._typing.enter = True
            self._flush_typing()
            return
        if key in STEP_KEYS:
            self._key_step(ts, key, pos)
        # everything else (arrows, function keys, ...) is ignored

    def _start_typing(self, ts: float, pos: tuple[float, float] | None) -> _TypingRun:
        x, y = self._pos(pos)
        win = self.window()
        ignored = self.is_excluded(win)
        if ignored:
            self.excluded_count += 1
        masked = (not self.opt.record_typing) or is_sensitive_title(win.title)
        shot = None if ignored else self.capture(x, y, ts)
        self._typing = _TypingRun(
            ts=ts, x=x, y=y, shot=shot, win=win, ignored=ignored, masked=masked
        )
        return self._typing

    def _key_step(self, ts: float, keys: str, pos: tuple[float, float] | None) -> None:
        self.flush()
        x, y = self._pos(pos)
        win = self.window()
        if self.is_excluded(win):
            self.excluded_count += 1
            return
        shot = self.capture(x, y, ts)
        ev = self._base("key", ts, win, shot)
        ev["keys"] = keys
        self._with_point(ev, shot, x, y)
        self._emit(ev)

    # ------------------------------------------------------------------ context
    # Context events (app switches, URLs, clipboard) never become steps. They have
    # no ``id`` so step ids stay stable; ``seq`` is the id the next step will get.
    def _ctx(self, kind: str, ts: float) -> dict[str, Any]:
        return {"seq": self._next_id, "ts": round(ts - self.t0, 3), "kind": kind}

    def observe(self, ts: float, win: WindowInfo, url: str | None = None) -> None:
        """Feed the front window (and browser URL) from a periodic poll."""
        self.tick(ts)
        if self.is_excluded(win):
            self._last_win = None
            self._last_url = None
            return
        key = (win.app, win.title)
        if key != self._last_win and (win.app or win.title):
            self._last_win = key
            ev = self._ctx("app_switch", ts)
            ev["app_name"], ev["window_title"] = win.app, win.title
            self._emit(ev)
        if not self.opt.record_urls or not url:
            return
        norm = normalise_url(url, self.opt.keep_query)
        if norm and norm != self._last_url:
            self._last_url = norm
            ev = self._ctx("url", ts)
            ev["url"] = norm
            ev["app_name"] = win.app
            self._emit(ev)

    def observe_clipboard(self, ts: float, text: str | None, win: WindowInfo) -> None:
        """Feed the clipboard text from a periodic poll; emits only on change."""
        if not self._clip_seen:  # whatever was copied before recording started
            # None = no text on the clipboard (or unreadable): an empty baseline
            self._clip_seen, self._clip = True, text or ""
            return
        if text is None:
            return
        if text == self._clip:
            return
        self._clip = text
        if not self.opt.record_clipboard or not text or self.is_excluded(win):
            return
        ev = self._ctx("clipboard", ts)
        ev["chars"] = len(text)
        ev["app_name"] = win.app
        if is_sensitive_title(win.title):
            ev["masked"] = True
        else:
            # redact before cutting, so a secret cut in half cannot survive
            one_line = re.sub(r"\s+", " ", redact_text(text[:2000])).strip()
            ev["preview"] = one_line[:CLIPBOARD_PREVIEW]
        self._emit(ev)

    def observe_terminal(self, ts: float, command: str, exit_code: int | None = None) -> None:
        """A command run in ``stepcap shell`` (simulate uses this directly)."""
        if not command.strip():
            return
        ev = self._ctx("terminal", ts)
        ev["command"] = command.strip()[:2000]
        if exit_code is not None:
            ev["exit"] = int(exit_code)
        self._emit(ev)

    # ------------------------------------------------------------------ manual
    def manual_capture(self, ts: float, pos: tuple[float, float] | None = None):
        """First half of a manual step: grab the screen now, before any prompt."""
        self.flush()
        x, y = self._pos(pos)
        win = self.window()
        shot = None if self.is_excluded(win) else self.capture(x, y, ts)
        return (ts, x, y, win, shot)

    def manual_commit(self, token, note: str) -> None:
        ts, x, y, win, shot = token
        ev = self._base("manual", ts, win, shot)
        ev["note"] = note.strip()
        self._with_point(ev, shot, x, y)
        self._emit(ev)
