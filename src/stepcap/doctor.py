"""`stepcap doctor`: check that recording can work on this machine.

``collect_probes()`` talks to the OS (not unit tested); ``evaluate()`` turns
the probe results into checks with fix instructions and is pure, so the
logic for every OS is tested on any OS.
"""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import sys
import threading
from dataclasses import asdict, dataclass
from typing import Any

from stepcap import __version__

OK, WARN, FAIL, INFO = "ok", "warn", "fail", "info"


@dataclass
class Check:
    id: str
    status: str
    label: str
    detail: str = ""
    fix: str = ""


# ------------------------------------------------------------------ probes (OS-dependent)
def _dep_version(module: str) -> tuple[str | None, str | None]:
    try:
        mod = __import__(module)
    except Exception as exc:  # ImportError, or pynput's backend error
        return None, f"{type(exc).__name__}: {exc}".splitlines()[0]
    try:
        from importlib.metadata import version

        return version({"PIL": "pillow"}.get(module, module)), None
    except Exception:  # frozen binaries (PyInstaller) may ship without dist-info
        return str(getattr(mod, "__version__", "bundled")), None


def probe_screenshot() -> dict[str, Any]:
    try:
        from stepcap.capture.screenshot import ScreenGrabber

        g = ScreenGrabber("active")
        try:
            m = g.monitors[0]
            img, _ = g.grab(m.left + 1, m.top + 1)
            return {
                "ok": True,
                "monitors": [mm.to_dict() for mm in g.monitors],
                "image_size": [img.width, img.height],
            }
        finally:
            g.close()
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}".splitlines()[0]}


def probe_hooks(timeout: float = 3.0) -> dict[str, Any]:
    """Try to start pynput mouse + keyboard listeners, then stop them."""
    result: dict[str, Any] = {"ok": False, "trusted": None, "error": None}
    try:
        from pynput import keyboard, mouse
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}".splitlines()[0]
        return result

    listeners = []
    try:
        listeners = [mouse.Listener(), keyboard.Listener()]
        for lst in listeners:
            lst.start()
        done = threading.Event()

        def wait_all() -> None:
            for lst in listeners:
                lst.wait()
            done.set()

        threading.Thread(target=wait_all, daemon=True).start()
        if not done.wait(timeout):
            result["error"] = "listeners did not become ready in time"
            return result
        alive = all(lst.is_alive() for lst in listeners)
        trusted = [getattr(lst, "IS_TRUSTED", None) for lst in listeners]
        if any(t is not None for t in trusted):
            result["trusted"] = all(t is not False for t in trusted)
        result["ok"] = alive and result["trusted"] is not False
        if not alive:
            result["error"] = "listener thread exited immediately"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}".splitlines()[0]
    finally:
        for lst in listeners:
            with contextlib.suppress(Exception):
                lst.stop()
    return result


def _mac_permissions() -> dict[str, Any]:
    import ctypes
    import ctypes.util

    res: dict[str, Any] = {
        "accessibility": None,
        "screen_recording": None,
        "input_monitoring": None,
    }
    try:
        app_services = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        app_services.AXIsProcessTrusted.restype = ctypes.c_bool
        res["accessibility"] = bool(app_services.AXIsProcessTrusted())
    except Exception:
        pass
    try:
        cg = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
        )
        cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        res["screen_recording"] = bool(cg.CGPreflightScreenCaptureAccess())
    except Exception:
        pass
    try:
        iokit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
        iokit.IOHIDCheckAccess.restype = ctypes.c_uint32
        iokit.IOHIDCheckAccess.argtypes = [ctypes.c_uint32]
        # kIOHIDRequestTypeListenEvent = 1 ; result 0 granted, 1 denied, 2 unknown
        res["input_monitoring"] = {0: True, 1: False}.get(iokit.IOHIDCheckAccess(1))
    except Exception:
        pass
    return res


def _windows_admin() -> bool | None:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return None


def collect_probes(include_hooks: bool = True) -> dict[str, Any]:
    from stepcap.capture import window

    p: dict[str, Any] = {
        "platform": sys.platform,
        "os": platform.platform(),
        "python": platform.python_version(),
        "stepcap": __version__,
        "executable": sys.executable,
        "deps": {},
        "env": {
            "DISPLAY": os.environ.get("DISPLAY"),
            "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"),
            "XDG_SESSION_TYPE": os.environ.get("XDG_SESSION_TYPE"),
        },
        "xdotool": shutil.which("xdotool"),
    }
    for mod in ("PIL", "mss", "pynput"):
        ver, err = _dep_version(mod)
        p["deps"][mod] = {"version": ver, "error": err}
    p["screenshot"] = probe_screenshot()
    if include_hooks:
        p["hooks"] = probe_hooks()
    if sys.platform == "darwin":
        p["mac"] = _mac_permissions()
    if sys.platform == "win32":
        p["windows"] = {"admin": _windows_admin()}
    info = window.get_active_window()
    p["window"] = {"backend": window.backend_name(), "title": info.title, "app": info.app}
    return p


# ------------------------------------------------------------------ evaluation (pure)
MAC_ACCESSIBILITY_FIX = (
    "System Settings > Privacy & Security > Accessibility: add and enable the app that runs "
    "stepcap (Terminal, iTerm2, VS Code...). Then quit and reopen that app."
)
MAC_INPUT_FIX = (
    "System Settings > Privacy & Security > Input Monitoring: enable the app that runs stepcap, "
    "then restart it."
)
MAC_SCREEN_FIX = (
    'System Settings > Privacy & Security > Screen & System Audio Recording ("Screen Recording" '
    "on older macOS): enable the app that runs stepcap, then restart it. Without it screenshots "
    "show only the wallpaper and window titles are empty."
)
WAYLAND_FIX = (
    "Wayland sessions are not supported in v0.1 (global input hooks and screen capture are "
    'blocked by design). Log out and pick an "X11" / "Xorg" session on the login screen.'
)
X11_FIX = "Run stepcap inside a graphical X11 session (DISPLAY must be set, e.g. DISPLAY=:0)."
SESSION_FIX = "Run stepcap in an interactive desktop session (not a service or SSH session)."
WIN_ADMIN_NOTE = (
    'Windows blocks input hooks from a normal process while an elevated ("Run as '
    'administrator") window is in front. To document admin tools, run stepcap from an '
    "elevated terminal too."
)


def is_wayland(env: dict[str, str | None]) -> bool:
    return (env.get("XDG_SESSION_TYPE") or "").lower() == "wayland" or bool(
        env.get("WAYLAND_DISPLAY")
    )


def evaluate(p: dict[str, Any]) -> list[Check]:
    checks: list[Check] = []
    plat = p.get("platform", sys.platform)
    checks.append(
        Check("stepcap", INFO, "stepcap", f"{p.get('stepcap')} on Python {p.get('python')}", "")
    )
    checks.append(Check("os", INFO, "Operating system", str(p.get("os", plat))))

    py = tuple(int(x) for x in str(p.get("python", "3.11")).split(".")[:2])
    if py < (3, 11):
        checks.append(
            Check(
                "python",
                FAIL,
                "Python version",
                str(p.get("python")),
                "Install Python 3.11 or newer.",
            )
        )

    for mod, label in (("PIL", "Pillow"), ("mss", "mss"), ("pynput", "pynput")):
        d = p.get("deps", {}).get(mod, {})
        if d.get("version"):
            checks.append(Check(f"dep-{mod}", OK, f"{label} installed", d["version"]))
        else:
            err = d.get("error") or "not importable"
            fix = f"pip install --upgrade {label.lower()}"
            if mod == "pynput" and plat.startswith("linux") and "display" in err.lower():
                fix = X11_FIX
            checks.append(Check(f"dep-{mod}", FAIL, f"{label} importable", err, fix))

    env = p.get("env", {})
    if plat.startswith("linux"):
        if is_wayland(env):
            checks.append(
                Check("display", FAIL, "Display server", "Wayland session detected", WAYLAND_FIX)
            )
        elif not env.get("DISPLAY"):
            checks.append(Check("display", FAIL, "Display server", "DISPLAY is not set", X11_FIX))
        else:
            checks.append(Check("display", OK, "Display server", f"X11 (DISPLAY={env['DISPLAY']})"))

    mac = p.get("mac") or {}
    if plat == "darwin":
        for key, label, fix in (
            ("accessibility", "Accessibility permission", MAC_ACCESSIBILITY_FIX),
            ("input_monitoring", "Input Monitoring permission", MAC_INPUT_FIX),
            ("screen_recording", "Screen Recording permission", MAC_SCREEN_FIX),
        ):
            val = mac.get(key)
            if val is True:
                checks.append(Check(f"mac-{key}", OK, label, "granted"))
            elif val is False:
                sev = WARN if key == "input_monitoring" and mac.get("accessibility") else FAIL
                checks.append(Check(f"mac-{key}", sev, label, "not granted", fix))
            else:
                checks.append(Check(f"mac-{key}", WARN, label, "could not be determined", fix))

    shot = p.get("screenshot") or {}
    if shot.get("ok"):
        mons = shot.get("monitors") or []
        detail = f"{len(mons)} monitor(s): " + ", ".join(
            f"#{m['index']} {m['width']}x{m['height']}@({m['left']},{m['top']})" for m in mons
        )
        checks.append(Check("screenshot", OK, "Screen capture", detail))
    else:
        if plat == "darwin":
            fix = MAC_SCREEN_FIX
        elif plat.startswith("linux"):
            fix = WAYLAND_FIX if is_wayland(env) else X11_FIX
        else:
            fix = SESSION_FIX
        checks.append(Check("screenshot", FAIL, "Screen capture", shot.get("error", "failed"), fix))

    hooks = p.get("hooks")
    if hooks is not None:
        if hooks.get("ok"):
            checks.append(Check("hooks", OK, "Global mouse/keyboard hooks", "listeners started"))
        else:
            err = hooks.get("error") or ""
            if hooks.get("trusted") is False:
                err = err or "process is not trusted for input monitoring"
            if plat == "darwin":
                fix = MAC_ACCESSIBILITY_FIX
            elif plat.startswith("linux"):
                fix = WAYLAND_FIX if is_wayland(env) else X11_FIX
            else:
                fix = SESSION_FIX
            checks.append(Check("hooks", FAIL, "Global mouse/keyboard hooks", err or "failed", fix))

    if plat == "win32":
        admin = (p.get("windows") or {}).get("admin")
        checks.append(
            Check(
                "win-admin",
                INFO,
                "Elevation",
                "running as administrator" if admin else "not elevated",
                "" if admin else WIN_ADMIN_NOTE,
            )
        )

    win = p.get("window") or {}
    if win.get("title") or win.get("app"):
        checks.append(
            Check(
                "window",
                OK,
                "Foreground window name",
                f"{win.get('app') or '?'} - {win.get('title') or '(no title)'} "
                f"[{win.get('backend')}]",
            )
        )
    else:
        fix = ""
        if plat.startswith("linux") and not p.get("xdotool"):
            fix = "Optional: install xdotool (sudo apt install xdotool) for window names."
        elif plat == "darwin":
            fix = MAC_SCREEN_FIX
        checks.append(
            Check(
                "window",
                WARN,
                "Foreground window name",
                f"unavailable [{win.get('backend')}]; steps will be titled without the window name",
                fix,
            )
        )
    return checks


def exit_code(checks: list[Check]) -> int:
    return 1 if any(c.status == FAIL for c in checks) else 0


def blocking_problems(checks: list[Check]) -> list[Check]:
    return [c for c in checks if c.status == FAIL]


_SYMBOL = {OK: "[ok]  ", WARN: "[warn]", FAIL: "[FAIL]", INFO: "[info]"}


def format_text(checks: list[Check]) -> str:
    lines = []
    for c in checks:
        lines.append(f"{_SYMBOL[c.status]} {c.label}: {c.detail}".rstrip(": "))
        if c.fix and c.status != OK:
            lines.append(f"         -> {c.fix}")
    fails = blocking_problems(checks)
    lines.append("")
    if fails:
        lines.append(
            f"{len(fails)} problem(s) block recording. Fix them and run `stepcap doctor` "
            "again. See docs/permissions.md."
        )
    else:
        lines.append("Ready to record: stepcap record")
    return "\n".join(lines)


def run(as_json: bool = False) -> int:
    probes = collect_probes()
    checks = evaluate(probes)
    if as_json:
        print(
            json.dumps(
                {
                    "ok": exit_code(checks) == 0,
                    "checks": [asdict(c) for c in checks],
                    "probes": probes,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(format_text(checks))
    return exit_code(checks)
