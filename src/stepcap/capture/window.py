"""Best-effort lookup of the foreground window title and application name.

Never raises: if nothing works we return an empty WindowInfo and recording
goes on (steps are then titled "Click" instead of 'Click in "…"').

- Windows: ctypes (GetForegroundWindow / GetWindowTextW / QueryFullProcessImageNameW)
- macOS:   Quartz window list via pyobjc (installed with pynput); osascript fallback
- Linux:   xdotool if present; python-xlib (installed with pynput) fallback. X11 only.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable

from stepcap.capture.events import WindowInfo

_TIMEOUT = 1.5


def _safe(fn: Callable[[], WindowInfo]) -> WindowInfo:
    try:
        return fn()
    except Exception:
        return WindowInfo()


# --------------------------------------------------------------------- Windows
def _windows() -> WindowInfo:
    import ctypes
    import ctypes.wintypes as wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return WindowInfo()
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value or None

    app = None
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_query_limited_information = 0x1000
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid.value)
    if handle:
        try:
            size = wintypes.DWORD(1024)
            path = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(size)):
                app = os.path.splitext(os.path.basename(path.value))[0] or None
        finally:
            kernel32.CloseHandle(handle)
    return WindowInfo(title=title, app=app)


# --------------------------------------------------------------------- macOS
def _mac_quartz() -> WindowInfo:
    import Quartz  # pyobjc-framework-Quartz, a pynput dependency on macOS

    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
    for w in windows:  # front-to-back order
        if w.get("kCGWindowLayer", 1) != 0:
            continue
        app = w.get("kCGWindowOwnerName") or None
        # kCGWindowName is only filled when Screen Recording permission is granted.
        title = w.get("kCGWindowName") or None
        return WindowInfo(title=title, app=app)
    return WindowInfo()


_OSASCRIPT = """
tell application "System Events"
  set p to first application process whose frontmost is true
  set n to name of p
  set t to ""
  try
    set t to name of front window of p
  end try
end tell
return n & linefeed & t
"""


def _mac_osascript() -> WindowInfo:
    out = subprocess.run(
        ["osascript", "-e", _OSASCRIPT],
        capture_output=True,
        text=True,
        timeout=_TIMEOUT,
        check=False,
    )
    if out.returncode != 0:
        return WindowInfo()
    app, _, title = out.stdout.rstrip("\n").partition("\n")
    return WindowInfo(title=title.strip() or None, app=app.strip() or None)


def _mac() -> WindowInfo:
    info = _safe(_mac_quartz)
    if info.app:
        return info
    return _safe(_mac_osascript)


# --------------------------------------------------------------------- Linux (X11)
def _linux_xdotool(xdotool: str) -> WindowInfo:
    def run(*args: str) -> str | None:
        out = subprocess.run(
            [xdotool, *args], capture_output=True, text=True, timeout=_TIMEOUT, check=False
        )
        return out.stdout.strip() if out.returncode == 0 else None

    title = run("getactivewindow", "getwindowname")
    pid = run("getactivewindow", "getwindowpid")
    return WindowInfo(title=title or None, app=_proc_name(pid))


def _proc_name(pid: str | int | None) -> str | None:
    if not pid:
        return None
    try:
        with open(f"/proc/{int(pid)}/comm", encoding="utf-8") as fh:
            return fh.read().strip() or None
    except (OSError, ValueError):
        return None


_xlib_display = None


def _linux_xlib() -> WindowInfo:
    global _xlib_display
    from Xlib import X, display  # python-xlib, a pynput dependency on Linux

    if _xlib_display is None:
        _xlib_display = display.Display()
    d = _xlib_display
    root = d.screen().root
    active = d.intern_atom("_NET_ACTIVE_WINDOW")
    prop = root.get_full_property(active, X.AnyPropertyType)
    if not prop or not prop.value or not prop.value[0]:
        return WindowInfo()
    win = d.create_resource_object("window", prop.value[0])
    title = None
    name_prop = win.get_full_property(d.intern_atom("_NET_WM_NAME"), 0)
    if name_prop and name_prop.value:
        v = name_prop.value
        title = v.decode("utf-8", "replace") if isinstance(v, bytes) else str(v)
    else:
        wm_name = win.get_wm_name()
        title = wm_name if isinstance(wm_name, str) else None
    pid_prop = win.get_full_property(d.intern_atom("_NET_WM_PID"), X.AnyPropertyType)
    pid = pid_prop.value[0] if pid_prop and len(pid_prop.value) else None
    app = _proc_name(pid)
    if app is None:
        wm_class = win.get_wm_class()
        app = wm_class[1] if wm_class else None
    return WindowInfo(title=title or None, app=app)


def _linux() -> WindowInfo:
    xdotool = shutil.which("xdotool")
    if xdotool:
        info = _safe(lambda: _linux_xdotool(xdotool))
        if info.title or info.app:
            return info
    return _safe(_linux_xlib)


# --------------------------------------------------------------------- public
def backend_name() -> str:
    if sys.platform == "win32":
        return "win32 (ctypes)"
    if sys.platform == "darwin":
        return "Quartz window list (osascript fallback)"
    if shutil.which("xdotool"):
        return "xdotool (python-xlib fallback)"
    return "python-xlib (install xdotool for better results)"


def get_active_window() -> WindowInfo:
    if sys.platform == "win32":
        return _safe(_windows)
    if sys.platform == "darwin":
        return _mac()
    if sys.platform.startswith("linux"):
        return _linux()
    return WindowInfo()
