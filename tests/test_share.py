"""`stepcap share`: password-protected guide.html."""

from __future__ import annotations

import glob
import json
import os
import re

import pytest

from stepcap import share
from stepcap.cli import main

PW = "correct horse battery"


def _payload(html: str) -> dict:
    m = re.search(r'<script id="payload" type="application/json">(.*?)</script>', html, re.S)
    assert m
    return json.loads(m.group(1).replace("<\\/", "</"))


def test_roundtrip_and_wrong_password():
    page = "<html><body><h1>Guide</h1><script>x='</script>'</script></body></html>"
    out = share.protect(page, PW, "ja")
    assert "Guide" not in out and "パスワード" in out
    blob = _payload(out)
    assert blob["iter"] == share.ITERATIONS
    assert share.decrypt(blob, PW) == page
    with pytest.raises(share.ShareError, match="wrong password"):
        share.decrypt(blob, "not the password")
    other = _payload(share.protect(page, PW))
    assert other["salt"] != blob["salt"] and other["iv"] != blob["iv"]  # fresh every time
    with pytest.raises(share.ShareError, match="at least"):
        share.protect(page, "short")


def test_cli_share(demo_session, tmp_path, monkeypatch, capsys):
    out = tmp_path / "shared.html"
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(PW + "\n"))
    code = main(["share", str(demo_session), "-o", str(out), "--password-stdin", "--json"])
    assert code == 0, capsys.readouterr().err
    page = share.decrypt(_payload(out.read_text("utf-8")), PW)
    assert page == (demo_session / "guide.html").read_text("utf-8")  # built on demand
    monkeypatch.setenv("STEPCAP_PASSWORD", PW)
    out2 = tmp_path / "check.html"
    assert main(["share", str(demo_session), "-o", str(out2), "--file", "checklist"]) == 0
    assert share.decrypt(_payload(out2.read_text("utf-8")), PW).startswith("<!doctype html>")
    guide = demo_session / "guide.html"
    assert main(["share", str(demo_session), "-o", str(guide)]) == 1  # never over the original
    assert "another file" in capsys.readouterr().err


def test_browser_decrypts_the_file(demo_session, tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    out = share.share(demo_session, tmp_path / "shared.html", PW)
    exe = os.environ.get("STEPCAP_CHROMIUM") or next(
        iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))), None
    )
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
        except Exception as exc:
            pytest.skip(f"no Chromium available: {exc}")
        page = browser.new_page()
        page.goto(out.as_uri())  # file:// - WebCrypto works on local files
        page.fill("#pw", "wrong password!")
        page.click("button")
        page.wait_for_function("document.getElementById('err').textContent.length > 0")
        assert "Wrong password" in page.inner_text("#err")
        page.fill("#pw", PW)
        page.click("button")
        page.wait_for_selector(".step", timeout=30000)  # the real guide
        assert "Create a project" in page.title()
        browser.close()
