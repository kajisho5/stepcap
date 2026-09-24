"""Browser test of the edit UI (runs only when Playwright + a Chromium are available).

pip install playwright && playwright install chromium   # or set STEPCAP_CHROMIUM
"""

import glob
import hashlib
import json
import os
import threading

import pytest

sync_api = pytest.importorskip("playwright.sync_api")

from stepcap.edit.server import create_server  # noqa: E402


def _launch(p):
    exe = os.environ.get("STEPCAP_CHROMIUM") or next(
        iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))), None
    )
    try:
        return p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
    except Exception as exc:  # browser not installed
        pytest.skip(f"no Chromium available: {exc}")


def _digest(d):
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.iterdir())}


def test_reorder_delete_rename_blur_save_build(demo_session):
    srv = create_server(demo_session, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    raw_before = _digest(demo_session / "raw")
    try:
        with sync_api.sync_playwright() as p:
            browser = _launch(p)
            # bypass_csp: the UI's CSP forbids eval, which Playwright's wait_for_function uses
            page = browser.new_page(viewport={"width": 1280, "height": 3200}, bypass_csp=True)
            page.goto(url)
            page.wait_for_selector(".step")
            ids = page.eval_on_selector_all(".step", "els => els.map(e => e.dataset.id)")

            page.locator(".step").nth(2).locator(".handle").hover()
            page.mouse.down()
            box = page.locator(".step").nth(0).bounding_box()
            page.mouse.move(box["x"] + 50, box["y"] + 10, steps=10)
            page.mouse.up()
            order = page.eval_on_selector_all(".step", "els => els.map(e => e.dataset.id)")
            assert order[:3] == [ids[2], ids[0], ids[1]]

            page.locator(".step").nth(0).locator(".title").fill("Type the project name")
            page.locator(".step").last.locator(".del").click()

            card = page.locator(".step").nth(1)
            card.locator("button", has_text="Blur area").click()
            bb = card.locator(".shot img").bounding_box()
            page.mouse.move(bb["x"] + bb["width"] * 0.3, bb["y"] + bb["height"] * 0.3)
            page.mouse.down()
            page.mouse.move(bb["x"] + bb["width"] * 0.6, bb["y"] + bb["height"] * 0.5, steps=5)
            page.mouse.up()
            page.wait_for_function(
                "() => document.getElementById('status').textContent.startsWith('Blurred')"
            )
            page.click("#build")
            page.wait_for_function(
                "() => document.getElementById('status').textContent.startsWith('Built')"
            )
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()

    doc = json.loads((demo_session / "steps.json").read_text("utf-8"))
    assert [s["id"] for s in doc["steps"]][:2] == [ids[2], ids[0]]
    assert doc["steps"][0]["title"] == "Type the project name"
    assert len(doc["steps"]) == len(ids) - 1
    assert _digest(demo_session / "raw") == raw_before
    blurred = [
        f.name
        for f in (demo_session / "work").iterdir()
        if f.read_bytes() != (demo_session / "raw" / f.name).read_bytes()
    ]
    assert blurred == [doc["steps"][1]["screenshot"] + ".png"]
    assert "Type the project name" in (demo_session / "guide.md").read_text("utf-8")
