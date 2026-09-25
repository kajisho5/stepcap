"""Clicked-element names and frames (UI Automation / Accessibility), RM-021."""

from __future__ import annotations

import json
import sys
import threading
import time

import pytest

from stepcap.build.naming import auto_title
from stepcap.build.pipeline import BuildOptions, run_build
from stepcap.capture import element as el_mod
from stepcap.capture.element import ElementInfo, ElementLookup, clean_name
from stepcap.capture.events import EventProcessor, Monitor, ProcessorOptions, Shot, WindowInfo
from stepcap.session import read_json
from stepcap.simulate import simulate


def test_element_info_hides_password_names():
    assert ElementInfo("Save", "button", (1, 2, 3, 4)).to_dict() == {
        "name": "Save",
        "role": "button",
        "rect": [1, 2, 3, 4],
    }
    secret = ElementInfo("hunter2", "text-field", None, secure=True).to_dict()
    assert secret == {"role": "password-field"}


def test_clean_name():
    assert clean_name("  New \n project ") == "New project"
    assert clean_name("") is None and clean_name(None) is None and clean_name(5) is None
    long = clean_name("x" * 200)
    assert long is not None and len(long) == el_mod.MAX_NAME and long.endswith("…")


def test_lookup_timeout_busy_and_errors():
    gate = threading.Event()

    def slow(x, y, focused):
        if x == 1:
            gate.wait(2)
        if x == 2:
            raise RuntimeError("app not responding")
        return ElementInfo(f"at {x}", "button")

    lookup = ElementLookup(timeout=0.1, fn=slow)
    assert lookup(5, 5).name == "at 5"
    t0 = time.monotonic()
    assert lookup(1, 1) is None  # times out
    assert time.monotonic() - t0 < 0.5
    assert lookup(5, 5) is None  # still busy with the hung lookup: skipped at once
    gate.set()
    time.sleep(0.2)
    assert lookup(2, 2) is None  # exception -> None
    assert lookup(7, 7).name == "at 7"


def _proc(events, element, **opts):
    mon = Monitor(1, 0, 0, 1000, 800)

    def capture(x, y, ts):
        return Shot("0001", "raw/0001.png", mon, 2000, 1600)  # a 2x (Retina-like) screen

    return EventProcessor(
        capture,
        lambda: WindowInfo("Settings - App", "app"),
        events.append,
        ProcessorOptions(**opts),
        element=element,
    )


def test_click_gets_element_and_box_in_image_pixels():
    events = []
    proc = _proc(events, lambda x, y, f: ElementInfo("Save", "button", (100, 50, 80, 30)))
    proc.on_mouse(0, 120, 60, "left", True)
    proc.on_mouse(0.05, 120, 60, "left", False)
    proc.tick(1)
    ev = events[0]
    assert ev["element"] == {
        "name": "Save",
        "role": "button",
        "rect": [100, 50, 80, 30],
        "box": [200, 100, 160, 60],
    }
    assert auto_title(ev, "en") == 'Click the "Save" button'
    assert auto_title(ev, "ja") == "ボタン「Save」をクリック"


def test_huge_or_tiny_element_box_is_dropped():
    events = []
    proc = _proc(events, lambda x, y, f: ElementInfo("Main", "list-item", (0, 0, 1000, 800)))
    proc.on_mouse(0, 10, 10, "left", True)
    proc.on_mouse(0.05, 10, 10, "left", False)
    proc.tick(1)
    assert "box" not in events[0]["element"]


def test_password_field_masks_typing_even_with_record_typing():
    events = []
    proc = _proc(
        events,
        lambda x, y, focused: ElementInfo("Password", "text-field", None, secure=focused),
        record_typing=True,
    )
    for i, ch in enumerate("hunter2"):
        proc.on_key(i * 0.05, ch, True, pos=(10, 10))
    proc.flush()
    ev = events[0]
    assert ev["masked"] is True and "text" not in ev
    assert ev["element"] == {"role": "password-field"}


def test_lookup_failure_never_breaks_recording():
    events = []

    def broken(x, y, focused):
        raise OSError("COM error")

    proc = _proc(events, broken)
    proc.on_mouse(0, 5, 5, "left", True)
    proc.on_mouse(0.05, 5, 5, "left", False)
    proc.tick(1)
    assert events[0]["kind"] == "click" and "element" not in events[0]


def test_simulated_accessibility_titles_and_frames(tmp_path, spec):
    spec = json.loads(json.dumps(spec))
    spec["accessibility"] = True
    simulate(spec, tmp_path / "s")
    run_build(tmp_path / "s", BuildOptions(formats=("md",)))
    doc = read_json(tmp_path / "s" / "steps.json")
    titles = [s["title"] for s in doc["steps"]]
    assert titles[0] == 'Click the "+ New project" button'
    assert 'Type into the "Project name" field' in titles
    first = doc["steps"][0]
    assert first["box_source"] == "a11y" and first["box"] == [1220, 60, 188, 44]
    assert first["element"] == {"name": "+ New project", "role": "button"}
    # a later build keeps the a11y frame (no image detection over it)
    run_build(tmp_path / "s", BuildOptions(formats=("md",)))
    assert read_json(tmp_path / "s" / "steps.json")["steps"][0]["box_source"] == "a11y"
    md = (tmp_path / "s" / "guide.md").read_text("utf-8")
    assert 'Click the "+ New project" button' in md
    typed = next(s for s in doc["steps"] if s["kind"] == "type")
    assert typed["input"] == {"name": "project_name", "variable": True}  # named after the field


def test_input_names_from_labels():
    from stepcap.build.steps import assign_inputs, input_name_for

    assert input_name_for("Project name") == "project_name"
    assert input_name_for("E-mail (work)") == "e_mail_work"
    assert input_name_for("プロジェクト名") is None and input_name_for(None) is None
    steps = [
        {"kind": "type", "element": {"name": "Name"}},
        {"kind": "type", "element": {"name": "Name"}},
        {"kind": "type", "element": {"name": "名前"}},
    ]
    assign_inputs(steps)
    assert [s["input"]["name"] for s in steps] == ["name", "name_2", "input_3"]


def test_without_accessibility_titles_are_unchanged(demo_session):
    run_build(demo_session, BuildOptions(formats=("md",)))
    doc = read_json(demo_session / "steps.json")
    assert doc["steps"][0]["title"].startswith("Click in ")
    assert "element" not in doc["steps"][0]


# ------------------------------------------------------------------ real OS APIs (CI runners)
def test_real_lookup_never_raises():
    res = el_mod.lookup_now(5, 5)
    assert res is None or isinstance(res, ElementInfo)
    res = el_mod.lookup_now(5, 5, focused=True)
    assert res is None or isinstance(res, ElementInfo)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows UI Automation")
def test_windows_uia_client_is_created():
    assert el_mod.backend() == "windows-uia"
    uia_module, client = el_mod._uia_client()
    assert client is not None and hasattr(uia_module, "tagPOINT")
    root = client.GetRootElement()
    assert root is not None and root.CurrentControlType == 50033  # the desktop is a pane


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Accessibility API")
def test_macos_ax_api_is_available():
    import HIServices as HI

    assert el_mod.backend() == "macos-ax"
    assert HI.AXUIElementCreateSystemWide() is not None
    assert isinstance(HI.AXIsProcessTrusted(), bool)
