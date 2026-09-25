"""`stepcap record`: global hooks -> EventProcessor -> session directory.

Threads:
  pynput listeners   normalise input and enqueue it (nothing slow here: Windows
                     silently removes low-level hooks that take too long)
  processor thread   owns mss + EventProcessor; grabs the screen on press
  writer thread      encodes PNGs to raw/
  main thread        waits, shows the F7 note prompt, handles Ctrl+C
  control thread     (--control only) reads commands from stdin

--control is the protocol `stepcap app` uses to drive a recording in a child
process (no GUI toolkit ever runs in the recording process: on recent macOS,
Tk/Cocoa + pynput's keyboard listener in one process crash). Commands on stdin,
one per line: stop | pause | resume | manual | note <text> | note-cancel |
exclude <x> <y> <w> <h> (clicks inside that screen rectangle are ignored).
Status on stdout, one JSON object per line: ready | step | paused | resumed |
note_request | done | error.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stepcap.capture import window as window_mod
from stepcap.capture.events import EventProcessor, ProcessorOptions, WindowInfo
from stepcap.hotkeys import Hotkey, parse_hotkey
from stepcap.session import (
    EVENTS_FILE,
    SESSION_FILE,
    EventWriter,
    base_meta,
    now_iso,
    prepare_new_session,
    write_json,
)

LATENCY_TARGET_MS = 300
CONTEXT_POLL_S = 0.7  # front window / URL / clipboard poll interval
_MOD_NAMES = {
    "ctrl": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
    "alt": "alt",
    "alt_l": "alt",
    "alt_r": "alt",
    "alt_gr": "alt",
    "cmd": "cmd",
    "cmd_l": "cmd",
    "cmd_r": "cmd",
}
_BUTTONS = {"left", "right", "middle"}


class RecorderError(Exception):
    pass


@dataclass
class RecordOptions:
    out_dir: Path
    monitor: str = "active"
    record_typing: bool = False
    exclude_apps: tuple[str, ...] = ()
    hotkey_stop: Hotkey = field(default_factory=lambda: parse_hotkey("F9"))
    hotkey_pause: Hotkey = field(default_factory=lambda: parse_hotkey("F8"))
    hotkey_manual: Hotkey = field(default_factory=lambda: parse_hotkey("F7"))
    note_prompt: str = "auto"
    double_click_ms: int = 150
    record_urls: bool = False
    keep_query: bool = False
    record_clipboard: bool = False
    dry_run: bool = False
    as_json: bool = False
    control: bool = False
    element_names: bool = True  # name + frame of the clicked element (UIA / AX)


_status_lock = threading.Lock()


def emit_status(event: str, **data: Any) -> None:
    """One JSON line on stdout for `stepcap app` (only used with --control)."""
    line = json.dumps({"event": event, **data}, ensure_ascii=False)
    with _status_lock:
        print(line, flush=True)


def parse_command(line: str) -> tuple[str, Any] | None:
    """Parse one --control command line; None if it is not understood."""
    line = line.strip()
    if not line:
        return None
    cmd, _, rest = line.partition(" ")
    if cmd in ("stop", "pause", "resume", "manual", "note-cancel"):
        return (cmd, None)
    if cmd == "note":
        return ("note", rest.strip())
    if cmd == "exclude":
        try:
            x, y, w, h = (float(v) for v in rest.split())
        except ValueError:
            return None
        return ("exclude", (x, y, w, h) if w > 0 and h > 0 else None)
    return None


def _say(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------- preflight
def preflight() -> list[str]:
    """Fail loudly before recording if hooks or capture cannot work."""
    from stepcap import doctor

    probes = doctor.collect_probes(include_hooks=True)
    problems = doctor.blocking_problems(doctor.evaluate(probes))
    return [f"{c.label}: {c.detail}" + (f"\n    -> {c.fix}" if c.fix else "") for c in problems]


def set_dpi_awareness() -> None:
    """Windows: make hook coordinates and screenshots use the same physical pixels."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
    except Exception:
        with contextlib.suppress(Exception):
            ctypes.windll.user32.SetProcessDPIAware()


# ---------------------------------------------------------------------------- key names
def normalise_key(key: Any) -> str | None:
    """pynput Key/KeyCode -> processor key name (single char or lower-case name)."""
    name = getattr(key, "name", None)
    if name:  # pynput.keyboard.Key
        return _MOD_NAMES.get(name, name)
    char = getattr(key, "char", None)
    if char and len(char) == 1:
        if ord(char) < 32:  # Ctrl+letter arrives as a control char on Windows
            return chr(ord(char) + 96)
        return char
    vk = getattr(key, "vk", None)
    if vk is not None:
        if 65 <= vk <= 90:
            return chr(vk + 32)
        if 48 <= vk <= 57:
            return chr(vk)
    return None


# ---------------------------------------------------------------------------- note prompt
def _prompt_osascript() -> str | None:
    """macOS dialog in a separate process (Tk in this process would crash pynput)."""
    import subprocess

    script = (
        'text returned of (display dialog "Note for this step (Cancel = skip):" '
        'default answer "" with title "stepcap")'
    )
    try:
        out = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    except OSError:
        return None
    if out.returncode != 0:  # Cancel (or no GUI session)
        return None
    return out.stdout.rstrip("\n") or None


def prompt_note(mode: str) -> str | None:
    """Ask for the manual-step note. None = cancelled."""
    if mode == "none":
        return ""
    if mode in ("auto", "gui") and sys.platform == "darwin":
        return _prompt_osascript()
    if mode in ("auto", "gui"):
        try:
            import tkinter as tk
            from tkinter import simpledialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                return simpledialog.askstring(
                    "stepcap", "Note for this step (Cancel = skip):", parent=root
                )
            finally:
                root.destroy()
        except Exception as exc:
            if mode == "gui":
                _say(f"stepcap: GUI prompt unavailable ({exc}); using the terminal")
    _say("stepcap: type the note for this step in this terminal, then Enter (empty = skip):")
    try:
        text = input("> ")
    except EOFError:
        return None
    return text or None


# ---------------------------------------------------------------------------- recorder
class Recorder:
    def __init__(self, opts: RecordOptions, out: Path) -> None:
        self.opts = opts
        self.out = out
        self.raw_q: queue.Queue = queue.Queue()
        self.ui_q: queue.Queue = queue.Queue()
        self.note_q: queue.Queue = queue.Queue()
        self.stopped = threading.Event()
        self.paused = threading.Event()
        self.prompting = threading.Event()
        self.ready = threading.Event()
        self.fatal: list[str] = []
        self.mods: set[str] = set()
        self.down: set[str] = set()
        self.counts: dict[str, int] = {}
        self.context_count = 0
        self.meta: dict[str, Any] = {}
        self.writer: EventWriter | None = None
        self.shot_writer = None
        self.processor: EventProcessor | None = None
        self.stats = None
        self._listeners: list[Any] = []

    # ------------------------------------------------------------ hook callbacks
    def _accepting(self) -> bool:
        return not (self.stopped.is_set() or self.paused.is_set() or self.prompting.is_set())

    # Hook callbacks run on pynput's listener threads: an exception escaping from
    # them stops the listener, so a malformed event is dropped instead.
    def on_click(self, x, y, button, pressed) -> None:
        with contextlib.suppress(Exception):
            name = getattr(button, "name", str(button))
            if name in _BUTTONS and self._accepting():
                self.raw_q.put(("mouse", time.monotonic(), x, y, name, pressed))

    def on_scroll(self, x, y, dx, dy) -> None:
        with contextlib.suppress(Exception):
            if self._accepting():
                self.raw_q.put(("scroll", time.monotonic(), x, y, dx, dy))

    def on_press(self, key) -> None:
        with contextlib.suppress(Exception):
            self._on_key(key, True)

    def on_release(self, key) -> None:
        with contextlib.suppress(Exception):
            self._on_key(key, False)

    def _on_key(self, key, pressed: bool) -> None:
        name = normalise_key(key)
        if name is None:
            return
        ts = time.monotonic()
        if len(name) > 1 and name not in ("space", "backspace"):
            # autorepeat of a held special key (Enter, F-keys, modifiers) is one press
            if pressed and name in self.down:
                return
            (self.down.add if pressed else self.down.discard)(name)
        if name in ("ctrl", "shift", "alt", "cmd"):
            (self.mods.add if pressed else self.mods.discard)(name)
        elif pressed:
            low = name.lower()
            o = self.opts
            if o.hotkey_stop.matches(low, self.mods):
                self.stop("hotkey")
                return
            if o.hotkey_pause.matches(low, self.mods):
                self.toggle_pause()
                return
            if o.hotkey_manual.matches(low, self.mods):
                if not self.prompting.is_set() and not self.stopped.is_set():
                    self.raw_q.put(("manual", ts))
                return
        if self._accepting() or (not pressed and name in ("ctrl", "shift", "alt", "cmd")):
            self.raw_q.put(("key", ts, name, pressed))

    def stop(self, why: str = "") -> None:
        if not self.stopped.is_set():
            self.stopped.set()
            self.raw_q.put(("stop",))

    def toggle_pause(self) -> None:
        if self.paused.is_set():
            self.paused.clear()
            _say("stepcap: resumed")
            if self.opts.control:
                emit_status("resumed")
        else:
            self.paused.set()
            self.raw_q.put(("flush",))
            _say(f"stepcap: paused ({self.opts.hotkey_pause} to resume)")
            if self.opts.control:
                emit_status("paused")

    def _control_main(self) -> None:
        """--control: commands from the parent process (stepcap app) on stdin."""
        for line in sys.stdin:
            parsed = parse_command(line)
            if parsed is None:
                continue
            cmd, arg = parsed
            if cmd == "stop":
                self.stop("control")
            elif (cmd == "pause" and not self.paused.is_set()) or (
                cmd == "resume" and self.paused.is_set()
            ):
                self.toggle_pause()
            elif cmd == "manual":
                if not self.prompting.is_set() and not self.stopped.is_set():
                    self.raw_q.put(("manual", time.monotonic()))
            elif cmd in ("note", "note-cancel"):
                self.note_q.put(arg if cmd == "note" else None)
            elif cmd == "exclude":
                self.raw_q.put(("exclude", arg))
            if self.stopped.is_set():
                break
        else:  # stdin closed: the app went away, so stop and save
            self.note_q.put(None)
            self.stop("control closed")

    def _ask_note(self) -> str | None:
        if not self.opts.control:
            return prompt_note(self.opts.note_prompt)
        while not self.note_q.empty():  # drop stale answers
            self.note_q.get_nowait()
        emit_status("note_request")
        while not self.stopped.is_set():
            try:
                return self.note_q.get(timeout=0.2)
            except queue.Empty:
                continue
        return None

    # ------------------------------------------------------------ processor thread
    def _processor_main(self) -> None:
        from stepcap.capture.screenshot import LatencyStats, ScreenGrabber, ShotWriter

        try:
            grabber = ScreenGrabber(self.opts.monitor)
        except Exception as exc:
            self.fatal.append(f"screen capture failed: {exc}")
            self.ready.set()
            return
        self.meta["monitors"] = [m.to_dict() for m in grabber.monitors]
        self.stats = LatencyStats()
        self.shot_writer = ShotWriter(self.out, self.stats)
        self.shot_writer.start()

        def capture(x, y, ts):
            img, mon = grabber.grab(x, y)
            return self.shot_writer.new_shot(img, mon, ts)

        pointer = None
        # Without a pointer controller, keys/notes fall back to the last click position.
        with contextlib.suppress(Exception):
            from pynput import mouse

            pointer = mouse.Controller()

        def pos():
            try:
                return pointer.position if pointer else None
            except Exception:
                return None

        def emit(ev):
            self.writer.write(ev)
            if "id" not in ev:  # context event (app switch, URL, clipboard): not a step
                self.context_count += 1
                return
            kind = ev["kind"] if ev["kind"] != "click" else f"{ev['click_type']}-click"
            self.counts[ev["kind"]] = self.counts.get(ev["kind"], 0) + 1
            where = ev.get("window_title") or ev.get("app_name") or ""
            _say(f"  #{ev['id']:<3} {kind:<13} {where[:60]}")
            if self.opts.control:
                steps = sum(self.counts.values())
                emit_status("step", n=steps, kind=kind, where=where[:80])

        proc = EventProcessor(
            capture,
            self._window,
            emit,
            ProcessorOptions(
                record_typing=self.opts.record_typing,
                exclude_apps=self.opts.exclude_apps,
                double_click_s=self.opts.double_click_ms / 1000,
                record_urls=self.opts.record_urls,
                keep_query=self.opts.keep_query,
                record_clipboard=self.opts.record_clipboard,
            ),
            t0=time.monotonic(),
            element=self._element_lookup(),
        )
        self.meta["t0_epoch"] = round(time.time(), 3)  # aligns `stepcap shell` commands
        self.processor = proc
        self.ready.set()
        try:
            while True:
                try:
                    item = self.raw_q.get(timeout=0.05)
                except queue.Empty:
                    proc.tick(time.monotonic())
                    continue
                kind = item[0]
                if kind == "stop":
                    break
                if kind == "mouse":
                    proc.on_mouse(*item[1:])
                elif kind == "scroll":
                    proc.on_scroll(*item[1:])
                elif kind == "key":
                    _, ts, name, pressed = item
                    proc.on_key(ts, name, pressed, pos=pos() if pressed else None)
                elif kind == "flush":
                    proc.flush()
                elif kind == "manual":
                    self.ui_q.put(("manual", proc.manual_capture(item[1], pos())))
                elif kind == "manual_commit":
                    proc.manual_commit(item[1], item[2])
                elif kind == "exclude":
                    proc.ignore_rects = [item[1]] if item[1] else []
                elif kind == "observe":
                    _, ts, win, url, clip = item
                    proc.observe(ts, win, url)
                    proc.observe_clipboard(ts, clip, win)
            proc.flush()
        except Exception as exc:  # pragma: no cover - surfaced to the user
            self.fatal.append(f"recording failed: {type(exc).__name__}: {exc}")
            self.stopped.set()
        finally:
            grabber.close()

    def _window(self) -> WindowInfo:
        return window_mod.get_active_window()

    def _element_lookup(self):
        if not self.opts.element_names:
            return None
        from stepcap.capture.element import ElementLookup

        lookup = ElementLookup()
        return lookup if lookup.enabled else None

    def _context_main(self) -> None:
        """Poll the front window (+ browser URL, clipboard) for context events."""
        from stepcap.capture import clipboard

        o = self.opts
        while not self.stopped.wait(CONTEXT_POLL_S):
            if not self._accepting():
                continue
            with contextlib.suppress(Exception):
                win = self._window()
                url = window_mod.browser_url(win) if o.record_urls else None
                clip = clipboard.read_text() if o.record_clipboard else None
                self.raw_q.put(("observe", time.monotonic(), win, url, clip))

    # ------------------------------------------------------------ main
    def run(self) -> dict[str, Any]:
        from pynput import keyboard, mouse

        o = self.opts
        self.meta = base_meta(
            "record",
            {
                "monitor": o.monitor,
                "record_typing": o.record_typing,
                "exclude_apps": list(o.exclude_apps),
                "double_click_ms": o.double_click_ms,
                "record_urls": o.record_urls,
                "keep_query": o.keep_query,
                "record_clipboard": o.record_clipboard,
                "element_names": o.element_names,
            },
        )
        self.writer = EventWriter(self.out / EVENTS_FILE)
        write_json(self.out / SESSION_FILE, self.meta)  # visible even if we crash

        proc_thread = threading.Thread(
            target=self._processor_main, name="stepcap-proc", daemon=True
        )
        proc_thread.start()
        self.ready.wait(10)
        if self.fatal:
            self.writer.close()
            raise RecorderError(self.fatal[0])

        self._listeners = [
            mouse.Listener(on_click=self.on_click, on_scroll=self.on_scroll),
            keyboard.Listener(on_press=self.on_press, on_release=self.on_release),
        ]
        for lst in self._listeners:
            lst.start()
        for lst in self._listeners:
            lst.wait()
        threading.Thread(target=self._context_main, name="stepcap-context", daemon=True).start()
        if o.control:
            threading.Thread(target=self._control_main, name="stepcap-control", daemon=True).start()
            emit_status("ready", session=str(self.out))
        if not all(lst.is_alive() for lst in self._listeners) or any(
            getattr(lst, "IS_TRUSTED", True) is False for lst in self._listeners
        ):
            self.stop()
            self._shutdown(proc_thread)
            raise RecorderError(
                "input hooks could not be started (missing permission?). Run `stepcap doctor`."
            )

        _say(f"stepcap: recording to {self.out}")
        _say(
            f"  {o.hotkey_stop} stop · {o.hotkey_pause} pause/resume · "
            f"{o.hotkey_manual} manual step with a note · Ctrl+C in this terminal also stops"
        )
        if not o.record_typing:
            _say("  typed text is NOT recorded (only the number of characters)")
        if o.record_urls:
            _say("  browser URLs are recorded" + ("" if o.keep_query else " (without ?query)"))
        if o.record_clipboard:
            from stepcap.capture import clipboard

            if clipboard.backend() is None:
                _say("  warning: no clipboard reader found (install xclip or xsel)")
            else:
                _say("  clipboard text is recorded (length + first 80 characters, masked)")
        t_start = time.monotonic()
        try:
            while not self.stopped.is_set():
                try:
                    req = self.ui_q.get(timeout=0.2)
                except queue.Empty:
                    if not all(lst.is_alive() for lst in self._listeners):
                        self.fatal.append("an input hook stopped unexpectedly")
                        self.stop()
                    continue
                if req[0] == "manual":
                    self.prompting.set()
                    try:
                        note = self._ask_note()
                    finally:
                        self.prompting.clear()
                    if note is None:
                        _say("stepcap: manual step skipped")
                    else:
                        self.raw_q.put(("manual_commit", req[1], note))
        except KeyboardInterrupt:
            self.stop("ctrl-c")
        return self._finish(proc_thread, time.monotonic() - t_start)

    def _shutdown(self, proc_thread: threading.Thread) -> None:
        for lst in self._listeners:
            with contextlib.suppress(Exception):
                lst.stop()
        proc_thread.join(10)
        if self.shot_writer is not None:
            self.shot_writer.close()
        if self.writer is not None:
            self.writer.close()

    def _finish(self, proc_thread: threading.Thread, duration: float) -> dict[str, Any]:
        self._shutdown(proc_thread)
        n_events = (self.writer.count if self.writer else 0) - self.context_count
        latency = self.stats.to_dict() if self.stats else {}
        excluded = self.processor.excluded_count if self.processor else 0
        self.meta["ended"] = now_iso()
        self.meta["stats"] = {
            "events": n_events,
            "context_events": self.context_count,
            "screenshots": len(self.stats.grab_ms) if self.stats else 0,
            "excluded": excluded,
            "by_kind": self.counts,
            "duration_s": round(duration, 1),
            "latency": latency,
            "write_errors": self.shot_writer.errors if self.shot_writer else [],
        }
        write_json(self.out / SESSION_FILE, self.meta)
        saved = (latency or {}).get("click_to_saved_ms") or {}
        result = {
            "ok": n_events > 0 and not self.fatal,
            "session": str(self.out),
            "events": n_events,
            "excluded": excluded,
            "latency": latency,
            "errors": self.fatal,
        }
        for e in self.fatal:
            _say(f"stepcap: error: {e}")
        if saved:
            _say(
                f"stepcap: click->saved latency p50 {saved['p50']} ms, p95 {saved['p95']} ms"
                + (
                    f" (above the {LATENCY_TARGET_MS} ms target)"
                    if saved["p95"] > LATENCY_TARGET_MS
                    else ""
                )
            )
        if n_events == 0:
            _say(
                "stepcap: no steps were recorded. If you did click, input hooks are probably "
                "blocked: run `stepcap doctor`."
            )
        else:
            _say(f"stepcap: saved {n_events} steps to {self.out}")
            _say(f"Next: stepcap build {self.out}")
        if self.opts.control:
            emit_status("done", **result)
        return result


def record(opts: RecordOptions) -> dict[str, Any]:
    if sys.platform.startswith("linux"):
        from stepcap.doctor import WAYLAND_FIX, is_wayland

        if is_wayland(dict(os.environ)):
            raise RecorderError(f"Wayland session detected. {WAYLAND_FIX}")
    set_dpi_awareness()  # before mss / pynput touch any coordinates
    problems = preflight()
    if problems:
        raise RecorderError(
            "cannot record on this machine:\n  - "
            + "\n  - ".join(problems)
            + "\nRun `stepcap doctor` for details (see docs/permissions.md)."
        )
    if opts.dry_run:
        return {"ok": True, "dry_run": True, "session": str(opts.out_dir)}
    out = prepare_new_session(opts.out_dir)
    return Recorder(opts, out).run()
