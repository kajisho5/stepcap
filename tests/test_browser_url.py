"""Browser URLs for --record-urls: Windows UI Automation (RM-064) and address bar text."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from stepcap.capture import window
from stepcap.capture.events import WindowInfo


@pytest.mark.parametrize(
    ("text", "url"),
    [
        ("github.com/kajisho5/stepcap", "https://github.com/kajisho5/stepcap"),
        ("https://example.com/a?b=1", "https://example.com/a?b=1"),
        ("localhost:8765/edit", "https://localhost:8765/edit"),
        ("file:///C:/Users/me/guide.html", "file:///C:/Users/me/guide.html"),
        ("edge://settings/privacy", "edge://settings/privacy"),
        ("192.168.0.10/admin", "https://192.168.0.10/admin"),
        ("about:blank", "about:blank"),
        ("how to reset the mixer", None),  # search text being typed
        ("mixer", None),
        ("", None),
        (None, None),
    ],
)
def test_address_to_url(text, url):
    assert window.address_to_url(text) == url


def test_windows_asks_only_browsers(monkeypatch):
    calls = []
    monkeypatch.setattr(window.sys, "platform", "win32")
    monkeypatch.setattr(window, "windows_browser_url", lambda hwnd=None: calls.append(1) or "u")
    assert window.browser_url(WindowInfo("Inbox - Outlook", "OUTLOOK")) is None
    assert window.browser_url(WindowInfo("Example - Google Chrome", "chrome")) == "u"
    assert window.browser_url(WindowInfo("x", "msedge")) == "u"
    assert window.browser_url(WindowInfo("x", None)) is None
    assert len(calls) == 2


def test_windows_url_never_raises_elsewhere():
    if sys.platform != "win32":
        assert window.windows_browser_url(12345) is None


# ----------------------------------------------------------- real browsers (Windows CI)
BROWSERS = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
    "msedge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "firefox": [r"C:\Program Files\Mozilla Firefox\firefox.exe"],
}


def _find_window(title_part: str, timeout: float = 30.0) -> int | None:
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if title_part in buf.value and user32.IsWindowVisible(hwnd):
            found.append(hwnd)
        return True

    end = time.time() + timeout
    while time.time() < end:
        found.clear()
        user32.EnumWindows(each, 0)
        if found:
            return found[0]
        time.sleep(0.5)
    return None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows UI Automation")
@pytest.mark.parametrize("browser", list(BROWSERS))
def test_real_browser_address_bar(browser):
    exe = next((p for p in BROWSERS[browser] if os.path.exists(p)), None) or shutil.which(browser)
    if exe is None:
        pytest.skip(f"{browser} is not installed on this runner")
    profile = tempfile.mkdtemp(prefix=f"stepcap-{browser}-")
    page = Path(profile) / "stepcap-url-test.html"
    marker = f"stepcap URL test {browser}"
    page.write_text(f"<title>{marker}</title><h1>{marker}</h1>", encoding="utf-8")
    if browser == "firefox":
        args = [exe, "-no-remote", "-profile", profile, "-new-window", page.as_uri()]
    else:
        args = [
            exe,
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate",
            "--new-window",
            page.as_uri(),
        ]
    proc = subprocess.Popen(args)
    try:
        hwnd = _find_window(marker)
        assert hwnd, f"{browser} window did not appear"
        url = None
        for _ in range(20):  # the address bar fills in after the page loads
            url = window.windows_browser_url(hwnd)
            if url and "stepcap-url-test.html" in url:
                break
            time.sleep(0.5)
        assert url and url.startswith("file:///") and url.endswith("stepcap-url-test.html"), url
    finally:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        shutil.rmtree(profile, ignore_errors=True)
