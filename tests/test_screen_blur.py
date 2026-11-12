"""Secrets seen on screen are blurred before export (build/screen_blur.py).

Every value here is an obviously fake placeholder, never a real credential.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from stepcap.build import screen_blur as ss
from stepcap.build.pipeline import BuildOptions, run_build
from stepcap.cli import main
from stepcap.session import read_json
from stepcap.simulate import simulate

FIXTURE = Path(__file__).parent / "fixtures" / "secret_screen.json"
FAKE_KEY = "sk-FAKE0000example0000notreal0000"


def W(text, x, y, w=60, h=16):
    return ss.Word(text, (x, y, w, h))


def kinds(words):
    return [(w.text, k) for w, k in ss.find(words)]


def test_find_keys_and_labelled_values():
    words = [
        W("OPENAI_API_KEY", 10, 10, 150),
        W("=", 165, 14, 8, 6),
        W(FAKE_KEY, 180, 10, 360),
        W("Password:", 10, 50, 90),
        W("hunter2-not-real", 105, 50, 140),
        W("API", 10, 90, 30),
        W("keys", 45, 90, 40),  # a heading: no value after it
        W("Rotate", 10, 130),
        W("keys", 75, 130),
    ]
    assert kinds(words) == [(FAKE_KEY, "openai-key"), ("hunter2-not-real", "password")]


def test_label_value_without_a_pattern_is_blurred():
    words = [W("ACME_TOKEN", 10, 10, 120), W("=", 135, 14, 8, 6), W("fake-value-123", 150, 10)]
    assert kinds(words) == [("fake-value-123", "token")]
    assert kinds([W("password=fake-value", 10, 10, 160)]) == [("password=fake-value", "password")]
    assert kinds([W("api_key:", 10, 10), W("fakefakefake", 75, 10)]) == [
        ("fakefakefake", "api-key")
    ]


def test_nothing_to_blur():
    assert kinds([W("Password:", 10, 50, 90), W("••••••••", 105, 50, 80)]) == []  # shown as dots
    assert kinds([W("Change", 10, 10), W("password", 75, 10)]) == []  # no separator, no value
    # a value far away on the same row belongs to another column
    assert kinds([W("Password:", 10, 10, 90), W("Settings", 900, 10)]) == []
    assert kinds([W("Save", 10, 10), W("Cancel", 80, 10)]) == []


def test_card_number_split_into_words():
    groups = ["4111", "1111", "1111", "1111"]  # the well-known test card number
    words = [W("Card", 10, 10, 40)] + [W(g, 60 + i * 50, 10, 45) for i, g in enumerate(groups)]
    assert [k for _, k in ss.find(words)] == ["card"] * 4


def fake_runner(detections):
    """A stand-in for `detection text ... -o OUT --json` writing detection-skill's shape."""
    calls = []

    def run(cmd):
        calls.append(cmd)
        out = Path(cmd[cmd.index("-o") + 1])
        doc = {
            "schema": "detection-skill/detections@1",
            "kind": "text",
            "engine": {"id": "tesseract", "version": "5.3.4"},
            "frames": [{"index": 0, "t": None, "detections": detections}],
        }
        out.write_text(json.dumps(doc), encoding="utf-8")
        return 0, "{}", ""

    run.calls = calls
    return run


def det(label, box):
    return {"kind": "text", "box": box, "label": label, "score": 0.2}


def test_scan_blurs_work_copy_and_lists_it(demo_session):
    session = demo_session
    run_build(session, BuildOptions(secret_scan=False))
    doc = read_json(session / "steps.json")
    sid = doc["steps"][0]["screenshot"]
    # stripes where the fake key "is", so the blur has something to change
    img = Image.open(session / "raw" / f"{sid}.png").convert("RGB")
    for x in range(410, 710, 4):
        img.paste((0, 0, 0), (x, 200, x + 2, 220))
    img.save(session / "raw" / f"{sid}.png")
    (session / "work" / f"{sid}.png").unlink(missing_ok=True)
    raw = (session / "raw" / f"{sid}.png").read_bytes()
    runner = fake_runner(
        [
            det("API_KEY", [300, 200, 90, 20]),
            det("=", [395, 205, 8, 6]),
            det(FAKE_KEY, [410, 200, 300, 20]),
        ]
    )
    res = ss.scan(session, doc, ["detection"], runner)
    assert res.engine == "tesseract 5.3.4"
    shots = {s["screenshot"] for s in doc["steps"] if s.get("screenshot")}
    assert res.checked == len(shots) == len(runner.calls)
    cmd = runner.calls[0]
    assert cmd[:2] == ["detection", "text"] and "--level" in cmd and "word" in cmd
    assert cmd[cmd.index("--min-score") + 1] == "0"
    blurs = doc["screen_secrets"]["blurs"]
    first = [b for b in blurs if b["screenshot"] == sid]
    assert first == [{"screenshot": sid, "rect": [406, 196, 308, 28], "kind": "openai-key"}]
    assert (session / "raw" / f"{sid}.png").read_bytes() == raw  # raw/ is never changed
    before = Image.open(session / "raw" / f"{sid}.png").convert("RGB").crop((406, 196, 714, 224))
    after = Image.open(session / "work" / f"{sid}.png").convert("RGB").crop((406, 196, 714, 224))
    assert before.tobytes() != after.tobytes()
    # checked screenshots are not read again
    again = ss.scan(session, doc, ["detection"], runner)
    assert again.checked == 0 and len(runner.calls) == len(shots)
    listed = ss.listing(doc)
    assert listed[0]["kind"] == "openai-key" and 1 in listed[0]["steps"]
    assert FAKE_KEY not in json.dumps(doc)  # the text that was read is never stored


def test_scan_failure_and_missing_engine(demo_session, monkeypatch):
    run_build(demo_session, BuildOptions(secret_scan=False))
    doc = read_json(demo_session / "steps.json")
    res = ss.scan(demo_session, doc, ["detection"], lambda cmd: (3, "", "tesseract not found"))
    assert res.checked == 0 and "exited 3" in res.warnings[0]
    assert doc["screen_secrets"]["checked"] == []  # tried again next build
    monkeypatch.setenv(ss.ENV_COMMAND, str(demo_session / "no-such-command"))
    res = ss.scan(demo_session, doc)
    assert res.checked == 0 and "detection-skill" in res.warnings[0]
    built = run_build(demo_session, BuildOptions())
    assert any("not checked for passwords or keys" in w for w in built.warnings)


def test_build_records_and_keeps_the_list(demo_session, monkeypatch):
    runner = fake_runner(
        [det("Password:", [300, 200, 90, 20]), det("not-a-real-one", [400, 200, 120, 20])]
    )
    monkeypatch.setattr(ss, "_run", runner)
    monkeypatch.setattr(ss, "locate", lambda: ["detection"])
    res = run_build(demo_session, BuildOptions())
    assert res.screen_blurs and {b["kind"] for b in res.screen_blurs} == {"password"}
    assert res.screen_scan["engine"] == "tesseract 5.3.4"
    n = len(runner.calls)
    res2 = run_build(demo_session, BuildOptions())
    assert res2.screen_blurs == res.screen_blurs and len(runner.calls) == n
    assert res2.written == []
    # --dry-run never writes work/
    assert run_build(demo_session, BuildOptions(dry_run=True, reset=True)).screen_blurs == []


def test_cli_lists_every_blur(demo_session, monkeypatch, capsys):
    monkeypatch.setattr(ss, "_run", fake_runner([det(FAKE_KEY, [300, 200, 300, 20])]))
    monkeypatch.setattr(ss, "locate", lambda: ["detection"])
    assert main(["build", str(demo_session)]) == 0
    out = capsys.readouterr().out
    assert "Blurred" in out and "openai-key at 296,196 308x28" in out and FAKE_KEY not in out
    assert main(["build", str(demo_session), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["screen_blurs"][0]["kind"] == "openai-key"


def test_no_secret_scan_flag(demo_session, monkeypatch):
    def boom(cmd):
        raise AssertionError("must not run")

    monkeypatch.setattr(ss, "_run", boom)
    monkeypatch.setattr(ss, "locate", lambda: ["detection"])
    assert main(["build", str(demo_session), "--no-secret-scan"]) == 0


def test_export_reports_the_blurs(demo_session, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ss, "_run", fake_runner([det(FAKE_KEY, [300, 200, 300, 20])]))
    monkeypatch.setattr(ss, "locate", lambda: ["detection"])
    out = tmp_path / "out"
    assert main(["export", str(demo_session), "--format", "guide", "-o", str(out), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["screen_blurs"][0]["kind"] == "openai-key"


# ------------------------------------------------- the real engine (detection-skill text)
needs_detection = pytest.mark.skipif(ss.locate() is None, reason="detection-skill not installed")


@needs_detection
def test_fixture_screenshot_with_an_api_key_is_blurred(tmp_path):
    """Done when: a fixture screenshot with an API key is blurred, and the list names it."""
    session = tmp_path / "keys"
    simulate(json.loads(FIXTURE.read_text(encoding="utf-8")), session)
    res = run_build(session, BuildOptions())
    assert res.screen_scan["checked"] == 1, res.warnings
    by_kind = {b["kind"]: b for b in res.screen_blurs}
    assert {"openai-key", "password"} <= set(by_kind), res.screen_blurs
    assert by_kind["openai-key"]["steps"] == [1]
    # read the exported image back: the key and the password are gone, the rest is still there
    words, _ = ss.read_words(session / "work" / "0001.png", ss.locate())
    text = " ".join(w.text for w in words)
    assert "sk-" not in text and "hunter2" not in text, text
    assert "Rotate" in text and "Password:" in text
    raw_words, _ = ss.read_words(session / "raw" / "0001.png", ss.locate())
    assert any(w.text.startswith("sk-") for w in raw_words)  # raw/ keeps the original


def test_reset_image_in_edit_undoes_an_automatic_blur(demo_session, monkeypatch):
    import threading
    import urllib.request

    from stepcap.edit.server import create_server

    monkeypatch.setattr(ss, "_run", fake_runner([det(FAKE_KEY, [300, 200, 300, 20])]))
    monkeypatch.setattr(ss, "locate", lambda: ["detection"])
    run_build(demo_session, BuildOptions())
    sid = read_json(demo_session / "steps.json")["screen_secrets"]["blurs"][0]["screenshot"]
    srv = create_server(demo_session, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{srv.server_address[1]}/api/reset-image",
            data=json.dumps({"screenshot": sid}).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req) as r:
            assert r.status == 200
    finally:
        srv.shutdown()
        srv.server_close()
    state = read_json(demo_session / "steps.json")["screen_secrets"]
    assert all(b["screenshot"] != sid for b in state["blurs"])
    assert sid in state["checked"]  # the person's decision: the next build does not blur it again
    assert sid not in {
        b["screenshot"] for b in run_build(demo_session, BuildOptions()).screen_blurs
    }
