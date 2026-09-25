from stepcap import doctor


def probes(**over):
    p = {
        "platform": "linux",
        "os": "Linux-6",
        "python": "3.11.9",
        "stepcap": "0.1.0",
        "deps": {m: {"version": "1.0", "error": None} for m in ("PIL", "mss", "pynput")},
        "env": {"DISPLAY": ":0", "WAYLAND_DISPLAY": None, "XDG_SESSION_TYPE": "x11"},
        "xdotool": "/usr/bin/xdotool",
        "screenshot": {
            "ok": True,
            "monitors": [{"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1080}],
        },
        "hooks": {"ok": True, "trusted": None, "error": None},
        "window": {"backend": "xdotool", "title": "Terminal", "app": "bash"},
    }
    p.update(over)
    return p


def by_id(checks):
    return {c.id: c for c in checks}


def test_healthy_linux():
    checks = doctor.evaluate(probes())
    assert doctor.exit_code(checks) == 0
    assert by_id(checks)["display"].status == doctor.OK
    assert "Ready to record" in doctor.format_text(checks)


def test_wayland_fails_with_instructions():
    p = probes(
        env={"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"},
        hooks={"ok": False, "trusted": None, "error": "no events"},
    )
    checks = by_id(doctor.evaluate(p))
    assert checks["display"].status == doctor.FAIL
    assert "X11" in checks["display"].fix
    assert "X11" in checks["hooks"].fix
    assert doctor.exit_code(list(checks.values())) == 1


def test_linux_without_display():
    p = probes(
        env={"DISPLAY": None},
        screenshot={"ok": False, "error": "no display"},
        deps={
            "PIL": {"version": "1"},
            "mss": {"version": "1"},
            "pynput": {"version": None, "error": "ImportError: bad display name"},
        },
    )
    checks = by_id(doctor.evaluate(p))
    assert checks["display"].status == doctor.FAIL
    assert checks["dep-pynput"].fix == doctor.X11_FIX
    assert checks["screenshot"].status == doctor.FAIL


def test_mac_missing_permissions():
    p = probes(
        platform="darwin",
        env={},
        mac={"accessibility": False, "screen_recording": False, "input_monitoring": None},
        hooks={"ok": False, "trusted": False, "error": None},
        window={"backend": "quartz", "title": None, "app": None},
    )
    checks = by_id(doctor.evaluate(p))
    assert checks["mac-accessibility"].status == doctor.FAIL
    assert "Accessibility" in checks["mac-accessibility"].fix
    assert checks["mac-screen_recording"].status == doctor.FAIL
    assert checks["mac-input_monitoring"].status == doctor.WARN
    assert checks["hooks"].status == doctor.FAIL and "not trusted" in checks["hooks"].detail
    assert checks["window"].status == doctor.WARN
    assert "display" not in checks


def test_mac_all_granted():
    p = probes(
        platform="darwin",
        env={},
        mac={"accessibility": True, "screen_recording": True, "input_monitoring": True},
        hooks={"ok": True, "trusted": True, "error": None},
    )
    assert doctor.exit_code(doctor.evaluate(p)) == 0


def test_windows_admin_note():
    checks = by_id(doctor.evaluate(probes(platform="win32", env={}, windows={"admin": False})))
    assert checks["win-admin"].status == doctor.INFO
    assert "administrator" in checks["win-admin"].fix
    checks = by_id(doctor.evaluate(probes(platform="win32", env={}, windows={"admin": True})))
    assert checks["win-admin"].fix == ""


def test_old_python_and_missing_dep():
    p = probes(
        python="3.10.2",
        deps={
            "PIL": {"version": None, "error": "No module"},
            "mss": {"version": "9"},
            "pynput": {"version": "1.8"},
        },
    )
    checks = by_id(doctor.evaluate(p))
    assert checks["python"].status == doctor.FAIL
    assert checks["dep-PIL"].fix == "pip install --upgrade pillow"


def test_missing_window_name_on_linux_suggests_xdotool():
    p = probes(xdotool=None, window={"backend": "xlib", "title": None, "app": None})
    assert "xdotool" in by_id(doctor.evaluate(p))["window"].fix


def test_voice_check():
    checks = by_id(doctor.evaluate(probes(voice={"missing": ["sounddevice", "faster_whisper"]})))
    v = checks["voice"]
    assert v.status == doctor.INFO and "stepcap[voice]" in v.fix and "libportaudio2" in v.fix
    assert doctor.exit_code(list(checks.values())) == 0  # optional: never blocks recording
    checks = by_id(doctor.evaluate(probes(voice={"missing": [], "microphone": "USB Mic"})))
    assert checks["voice"].status == doctor.OK and "USB Mic" in checks["voice"].detail
    p = probes(platform="darwin", voice={"missing": [], "microphone_error": "no input device"})
    checks = by_id(doctor.evaluate(p))
    assert checks["voice"].status == doctor.WARN and "Microphone" in checks["voice"].fix
