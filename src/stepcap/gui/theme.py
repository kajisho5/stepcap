"""Look of the `stepcap app` window: Sun Valley ttk theme, Noto Sans JP, light or dark.

The fonts ship with stepcap (``assets/fonts``, SIL Open Font License) and are
registered for this process only - nothing is installed on the system:
Windows ``AddFontResourceExW(FR_PRIVATE)``, macOS CoreText process scope, Linux
fontconfig ``FcConfigAppFontAddFile``. If any of that fails the window keeps
the system font; if ``sv_ttk`` is missing it keeps Tk's default theme.

Light or dark follows the OS (read once at start); ``STEPCAP_THEME=light|dark``
overrides it.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.util
import os
import re
import subprocess
import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from tkinter import ttk

FAMILY = "Noto Sans JP"
FONT_FILES = ("NotoSansJP-Regular.otf", "NotoSansJP-Bold.otf")
SIZES = {  # name: (points, bold)
    "brand": (20, True),
    "title": (16, True),
    "h": (11, True),
    "body": (10, False),
    "small": (9, False),
    "big": (12, True),
}

_registered: bool | None = None

# line breaking: a Latin word stays whole, Japanese may break between any two characters,
# but never before closing punctuation or after an opening bracket (kinsoku)
_UNIT = re.compile(r"[\x21-\x7e]+|\s|.")
_NO_START = set("、。，．）」』】〕〉》！？：；ー…・ぁぃぅぇぉっゃゅょァィゥェォッャュョ")
_NO_END = set("（「『【〔〈《")


@dataclass
class Theme:
    dark: bool
    family: str
    bg: str
    muted: str
    red: str
    green: str
    fonts: dict[str, tuple] = field(default_factory=dict)
    sv_ttk: bool = False


def font_dir() -> Path:
    return Path(str(resources.files("stepcap") / "assets" / "fonts"))


def register_fonts() -> bool:
    """Make Noto Sans JP available to this process (once). False if the OS refused."""
    global _registered
    if _registered is None:
        _registered = False
        paths = [font_dir() / name for name in FONT_FILES]
        if all(p.is_file() for p in paths):
            with contextlib.suppress(Exception):
                _registered = all(_register(p) for p in paths)
    return _registered


def _register(path: Path) -> bool:
    if sys.platform == "win32":
        fr_private = 0x10
        return ctypes.windll.gdi32.AddFontResourceExW(str(path), fr_private, 0) > 0  # type: ignore[attr-defined]
    if sys.platform == "darwin":
        cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        ct = ctypes.CDLL(ctypes.util.find_library("CoreText"))
        cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_bool,
        ]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
        ct.CTFontManagerRegisterFontsForURL.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_void_p,
        ]
        raw = os.fsencode(path)
        url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
        if not url:
            return False
        try:
            process_scope = 1  # kCTFontManagerScopeProcess
            return bool(ct.CTFontManagerRegisterFontsForURL(url, process_scope, None))
        finally:
            cf.CFRelease(url)
    lib = ctypes.util.find_library("fontconfig")
    if not lib:
        return False
    fc = ctypes.CDLL(lib)
    fc.FcConfigAppFontAddFile.restype = ctypes.c_int
    fc.FcConfigAppFontAddFile.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    return bool(fc.FcConfigAppFontAddFile(None, os.fsencode(path)))


def wrap(text: str, font: tkfont.Font, width: int) -> str:
    """``text`` with line breaks so no line is wider than ``width`` pixels in ``font``.

    Tk's own ``wraplength`` only breaks at spaces, so a Japanese sentence with one
    space ("AI エージェント") breaks there and nowhere else. A word wider than
    ``width`` (a path) is cut anywhere.
    """
    lines = []
    for para in text.split("\n"):
        units: list[str] = []
        for u in _UNIT.findall(para):
            if units and (u[0] in _NO_START or units[-1][-1] in _NO_END):
                units[-1] += u
            else:
                units.append(u)
        line = ""
        for u in units:
            if line.strip() and font.measure(line + u) > width:
                lines.append(line.rstrip())
                line = u.lstrip()
            else:
                line += u
            while font.measure(line) > width and len(line) > 1:  # a long path or URL
                fits = (i for i in range(len(line) - 1, 0, -1) if font.measure(line[:i]) <= width)
                cut = next(fits, 1)
                lines.append(line[:cut])
                line = line[cut:]
        lines.append(line.rstrip())
    return "\n".join(lines)


def os_prefers_dark() -> bool:
    choice = os.environ.get("STEPCAP_THEME", "").strip().lower()
    if choice in ("light", "dark"):
        return choice == "dark"
    with contextlib.suppress(Exception):
        if sys.platform == "win32":
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            with key:
                return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
        if sys.platform == "darwin":
            out = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return out.stdout.strip().lower() == "dark"
        out = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return "dark" in out.stdout
    return False


def dark_title_bar(win: tk.Misc, dark: bool) -> None:
    """Windows 10 20H1+ / 11: a dark title bar to match (elsewhere: nothing)."""
    if sys.platform != "win32" or not dark:
        return
    with contextlib.suppress(Exception):
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())  # type: ignore[attr-defined]
        on = ctypes.c_int(1)
        use_immersive_dark_mode = 20
        ctypes.windll.dwmapi.DwmSetWindowAttribute(  # type: ignore[attr-defined]
            hwnd, use_immersive_dark_mode, ctypes.byref(on), ctypes.sizeof(on)
        )


def apply(root: tk.Tk, dark: bool | None = None) -> Theme:
    """Theme, fonts and the few custom styles the window uses."""
    dark = os_prefers_dark() if dark is None else dark
    used_sv = False
    with contextlib.suppress(Exception):
        import sv_ttk

        sv_ttk.set_theme("dark" if dark else "light", root)
        root.update()  # sv-ttk sets its colours on <<ThemeChanged>>
        used_sv = True
    if not used_sv:
        dark = False  # Tk's default themes are light
    family = FAMILY if register_fonts() and FAMILY in tkfont.families(root) else ""
    if family:
        for name in tkfont.names(root):  # sv-ttk's fonts included; not TkFixedFont
            if name != "TkFixedFont":
                tkfont.nametofont(name, root).configure(family=family)
    else:
        family = tkfont.nametofont("TkDefaultFont", root).actual("family")
    fonts: dict[str, tuple] = {
        k: (family, size, "bold") if bold else (family, size) for k, (size, bold) in SIZES.items()
    }
    fonts["mono"] = (tkfont.nametofont("TkFixedFont", root).actual("family"), 11, "bold")
    theme = Theme(
        dark=dark,
        family=family,
        bg="#1c1c1c" if dark else "#fafafa",
        muted="#9aa4af" if dark else "#5f6b76",
        red="#ff5a52" if dark else "#d93025",
        green="#3fb950" if dark else "#1a7f37",
        fonts=fonts,
        sv_ttk=used_sv,
    )
    if not used_sv:
        theme.bg = ttk.Style(root).lookup(".", "background") or "#f0f0f0"
    style = ttk.Style(root)  # without sv-ttk, "Accent.TButton" falls back to "TButton"
    style.configure("Big.Accent.TButton", font=fonts["big"], padding=(16, 12))
    style.configure("TButton", font=fonts["body"])
    style.configure("TCheckbutton", font=fonts["body"])
    style.configure("TLabelframe.Label", font=fonts["h"])
    root.configure(bg=theme.bg)
    dark_title_bar(root, dark)
    return theme
