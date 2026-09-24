import hashlib
import json
import re
import threading
import urllib.request
from urllib.error import HTTPError

import pytest
from PIL import Image

from stepcap.edit.server import create_server


def digest(root):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir())}


@pytest.fixture
def server(demo_session):
    srv = create_server(demo_session, "127.0.0.1", 0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base, demo_session
    srv.shutdown()
    srv.server_close()


def call(base, method, path, body=None, headers=None):
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(base + path, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            ctype = r.headers.get("Content-Type", "")
            return r.status, json.loads(raw) if "json" in ctype else raw
    except HTTPError as e:
        return e.code, json.loads(e.read())


def test_ui_and_steps(server):
    base, session = server
    status, html = call(base, "GET", "/")
    assert status == 200 and b"stepcap edit" in html
    # no external requests (the SVG namespace URI is an identifier, not a request)
    assert not re.search(rb"(src|href)=[\"']https?:|url\(https?:|fetch\([\"']https?:", html)
    status, data = call(base, "GET", "/api/steps")
    assert status == 200 and len(data["doc"]["steps"]) == 12
    assert data["usage"]["0002"] == 4  # dialog screenshot shared by 4 steps
    assert (session / "steps.json").exists()


def test_reorder_delete_rename_and_save(server):
    base, session = server
    doc = call(base, "GET", "/api/steps")[1]["doc"]
    ids = [s["id"] for s in doc["steps"]]
    new = [
        {"id": ids[1], "title": "Name the project", "description": "Use the quarter."},
        {"id": ids[0]},
    ] + [{"id": i} for i in ids[3:]]  # ids[2] deleted
    status, res = call(base, "POST", "/api/steps", {"title": "Edited guide", "steps": new})
    assert status == 200 and res == {"ok": True, "steps": 11, "deleted": 1}
    saved = json.loads((session / "steps.json").read_text("utf-8"))
    assert saved["title"] == "Edited guide"
    assert [s["id"] for s in saved["steps"]][:2] == [ids[1], ids[0]]
    assert saved["steps"][0]["title"] == "Name the project"
    assert ids[2] not in [s["id"] for s in saved["steps"]]
    # build keeps the edits
    status, res = call(base, "POST", "/api/build", {"formats": "md,html,checklist"})
    assert status == 200 and res["steps"] == 11
    md = (session / "guide.md").read_text("utf-8")
    assert md.startswith("# Edited guide") and "## Step 1 — Name the project" in md
    status, page = call(base, "GET", "/guide.html")
    assert status == 200 and b"Edited guide" in page
    status, page = call(base, "GET", "/checklist.html")
    assert status == 200 and b"Edited guide" in page and page.count(b'class="box"') == 11


def test_save_validation(server):
    base, _ = server
    assert call(base, "POST", "/api/steps", {"steps": []})[0] == 409  # nothing loaded yet
    call(base, "GET", "/api/steps")
    assert call(base, "POST", "/api/steps", {"steps": [{"id": "nope"}]})[0] == 400
    assert call(base, "POST", "/api/steps", {"steps": "x"})[0] == 400
    doc = call(base, "GET", "/api/steps")[1]["doc"]
    sid = doc["steps"][0]["id"]
    assert call(base, "POST", "/api/steps", {"steps": [{"id": sid}, {"id": sid}]})[0] == 400
    assert call(base, "POST", "/api/steps", {"steps": [{"id": sid, "title": 5}]})[0] == 400


def test_blur_changes_work_copy_only(server):
    base, session = server
    call(base, "GET", "/api/steps")
    raw_before = digest(session / "raw")
    status, img = call(base, "GET", "/api/image/0001")
    assert status == 200 and img.startswith(b"\x89PNG")
    before = Image.open(session / "work" / "0001.png").convert("RGB")
    status, res = call(
        base, "POST", "/api/blur", {"screenshot": "0001", "rect": [1220, 60, 188, 44]}
    )
    assert status == 200 and res["rect"] == [1220, 60, 188, 44]
    after = Image.open(session / "work" / "0001.png").convert("RGB")
    box = (1220, 60, 1408, 104)
    assert before.crop(box).tobytes() != after.crop(box).tobytes()
    assert before.crop((0, 500, 400, 900)).tobytes() == after.crop((0, 500, 400, 900)).tobytes()
    assert digest(session / "raw") == raw_before
    # reset restores the original
    assert call(base, "POST", "/api/reset-image", {"screenshot": "0001"})[0] == 200
    assert (session / "work" / "0001.png").read_bytes() == (
        session / "raw" / "0001.png"
    ).read_bytes()


def test_blur_validation_and_path_traversal(server):
    base, _ = server
    assert call(base, "POST", "/api/blur", {"screenshot": "../x", "rect": [0, 0, 5, 5]})[0] == 400
    assert call(base, "POST", "/api/blur", {"screenshot": "9999", "rect": [0, 0, 5, 5]})[0] == 404
    assert call(base, "POST", "/api/blur", {"screenshot": "0001", "rect": [0, 0]})[0] == 400
    assert (
        call(base, "POST", "/api/blur", {"screenshot": "0001", "rect": [5000, 5000, 10, 10]})[0]
        == 400
    )
    assert call(base, "GET", "/api/image/..%2F..%2Fetc")[0] in (400, 404)


def test_csrf_and_dns_rebinding_protection(server):
    base, _ = server
    # wrong Host header (DNS rebinding)
    assert call(base, "GET", "/api/steps", headers={"Host": "evil.example:80"})[0] == 403
    # cross-origin JSON post
    status, _ = call(
        base, "POST", "/api/steps", {"steps": []}, headers={"Origin": "https://evil.example"}
    )
    assert status == 403
    # form-encoded post (what a cross-site form can send without preflight)
    req = urllib.request.Request(
        base + "/api/steps",
        data=b"steps=1",
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with pytest.raises(HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 415


def test_set_and_remove_frame(server):
    base, session = server
    doc = call(base, "GET", "/api/steps")[1]["doc"]
    click = next(s for s in doc["steps"] if s["kind"] == "click")
    status, res = call(base, "POST", "/api/box", {"id": click["id"], "rect": [10, 20, 100, 40]})
    assert status == 200 and res["box"] == [10, 20, 100, 40]
    saved = {s["id"]: s for s in json.loads((session / "steps.json").read_text("utf-8"))["steps"]}
    assert saved[click["id"]]["box"] == [10, 20, 100, 40]
    assert saved[click["id"]]["box_source"] == "manual"
    status, res = call(base, "POST", "/api/box", {"id": click["id"], "rect": None})
    assert status == 200 and res["box"] is None
    # a later build keeps the manual decision (no auto box comes back)
    assert call(base, "POST", "/api/build", {"formats": "md"})[0] == 200
    saved = {s["id"]: s for s in json.loads((session / "steps.json").read_text("utf-8"))["steps"]}
    assert saved[click["id"]]["box"] is None


def test_frame_validation(server):
    base, _ = server
    doc = call(base, "GET", "/api/steps")[1]["doc"]
    key = next(s for s in doc["steps"] if s["kind"] == "key")
    click = next(s for s in doc["steps"] if s["kind"] == "click")
    assert call(base, "POST", "/api/box", {"id": key["id"], "rect": [1, 1, 50, 50]})[0] == 400
    assert call(base, "POST", "/api/box", {"id": "nope", "rect": None})[0] == 400
    assert call(base, "POST", "/api/box", {"id": click["id"], "rect": [1, 2]})[0] == 400
    assert (
        call(base, "POST", "/api/box", {"id": click["id"], "rect": [5000, 5000, 10, 10]})[0] == 400
    )


def test_arrows_and_options(server):
    base, session = server
    doc = call(base, "GET", "/api/steps")[1]["doc"]
    step = doc["steps"][0]
    status, res = call(
        base,
        "POST",
        "/api/arrows",
        {"id": step["id"], "arrows": [[10, 10, 200, 150], [5000, -5, 300, 300]]},
    )
    assert status == 200 and res["arrows"] == [[10, 10, 200, 150], [1439, 0, 300, 300]]
    saved = json.loads((session / "steps.json").read_text("utf-8"))["steps"][0]
    assert saved["arrows"] == res["arrows"]
    assert call(base, "POST", "/api/arrows", {"id": step["id"], "arrows": []})[1]["arrows"] == []
    assert "arrows" not in json.loads((session / "steps.json").read_text("utf-8"))["steps"][0]
    assert call(base, "POST", "/api/arrows", {"id": step["id"], "arrows": [[1, 1, 2, 2]]})[0] == 400
    assert call(base, "POST", "/api/arrows", {"id": step["id"], "arrows": "x"})[0] == 400
    assert call(base, "POST", "/api/arrows", {"id": "nope", "arrows": []})[0] == 400

    status, res = call(
        base, "POST", "/api/options", {"marker": "ring", "spotlight": True, "auto_arrows": False}
    )
    assert status == 200 and res == {
        "ok": True,
        "marker": "ring",
        "spotlight": True,
        "auto_arrows": False,
    }
    assert call(base, "POST", "/api/options", {"marker": "star"})[0] == 400
    assert call(base, "POST", "/api/options", {"spotlight": "yes"})[0] == 400
    call(base, "POST", "/api/build", {"formats": "md"})
    saved = json.loads((session / "steps.json").read_text("utf-8"))
    assert saved["marker"] == "ring" and saved["spotlight"] is True
