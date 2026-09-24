"""Best-effort clipboard text reader for ``record --record-clipboard``.

Never raises; returns None when the clipboard has no text or cannot be read.
- Windows: ctypes (OpenClipboard / GetClipboardData(CF_UNICODETEXT))
- macOS:   pbpaste
- Linux:   xclip or xsel (X11)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

MAX_CHARS = 100_000
_TIMEOUT = 1.0


def _windows() -> str | None:
    import ctypes
    import ctypes.wintypes as wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    user32.GetClipboardData.restype = wintypes.HANDLE
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    cf_unicodetext = 13
    if not user32.IsClipboardFormatAvailable(cf_unicodetext):
        return None
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(cf_unicodetext)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            return ctypes.wstring_at(ptr)[:MAX_CHARS]
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def _command() -> list[str] | None:
    if sys.platform == "darwin":
        return ["pbpaste"]
    for exe, args in (("xclip", ["-selection", "clipboard", "-o"]), ("xsel", ["-b", "-o"])):
        path = shutil.which(exe)
        if path:
            return [path, *args]
    return None


def backend() -> str | None:
    """Name of the reader that will be used, or None if none is available."""
    if sys.platform == "win32":
        return "win32"
    cmd = _command()
    return os.path.basename(cmd[0]) if cmd else None


def read_text() -> str | None:
    try:
        if sys.platform == "win32":
            return _windows()
        cmd = _command()
        if cmd is None:
            return None
        env = dict(os.environ, LANG=os.environ.get("LANG") or "en_US.UTF-8")
        out = subprocess.run(cmd, capture_output=True, timeout=_TIMEOUT, env=env)
        if out.returncode != 0:
            return None
        return out.stdout.decode("utf-8", errors="replace")[:MAX_CHARS]
    except Exception:
        return None
