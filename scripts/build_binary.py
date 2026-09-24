"""Build a single-file stepcap executable with PyInstaller for the current OS.

    pip install . pyinstaller
    python scripts/build_binary.py            # -> dist/stepcap(.exe)
    python scripts/build_binary.py --name stepcap-linux-x64

pynput picks its backend at import time (pynput.keyboard._xorg, ._win32,
._darwin...). PyInstaller cannot import them during analysis (e.g. no X display
in CI), so the backend modules are passed as explicit hidden imports.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BACKENDS = {
    "win32": ["_win32"],
    "darwin": ["_darwin"],
    "linux": ["_xorg", "_uinput"],
}


def hidden_imports() -> list[str]:
    plat = "linux" if sys.platform.startswith("linux") else sys.platform
    mods = []
    for backend in BACKENDS.get(plat, []):
        mods += [f"pynput.keyboard.{backend}", f"pynput.mouse.{backend}"]
    mods += [f"pynput._util.{b.lstrip('_')}" for b in BACKENDS.get(plat, [])]
    if plat == "linux":
        mods += ["Xlib.ext.xtest", "Xlib.ext.record"]
    if plat == "win32":
        mods += ["mss.windows"]
    elif plat == "darwin":
        mods += ["mss.darwin", "Quartz", "ApplicationServices"]
    else:
        mods += ["mss.linux"]
    return mods


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="stepcap")
    args = ap.parse_args()
    import PyInstaller.__main__

    cmd = [
        str(ROOT / "src" / "stepcap" / "__main__.py"),
        "--onefile",
        "--noconfirm",
        "--clean",
        "--name",
        args.name,
        "--collect-data",
        "stepcap",  # edit/ui.html
        "--collect-submodules",
        "mss",
        "--exclude-module",
        "tkinter",
        "--distpath",
        str(ROOT / "dist"),
        "--workpath",
        str(ROOT / "build" / "pyinstaller"),
        "--specpath",
        str(ROOT / "build"),
    ]
    for mod in hidden_imports():
        cmd += ["--hidden-import", mod]
    print("pyinstaller " + " ".join(cmd), flush=True)
    PyInstaller.__main__.run(cmd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
