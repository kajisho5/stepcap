"""Addon A1/A2: context events, secret masking end to end, mixed-scale monitors."""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image

from stepcap.build import annotate
from stepcap.build.pipeline import BuildOptions, run_build
from stepcap.capture.events import WindowInfo, normalise_url
from stepcap.session import load_session, read_json
from stepcap.simulate import simulate
from stepcap.skill.run import SkillOptions, run_export

GH = "ghp_" + "Q1w2E3r4T5y6U7i8O9p0A1s2D3f4G5h6J7k8"
CARD = "4111 1111 1111 1111"
URL_PASSWORD = "S3cretPass"
URL_TOKEN = "tok_9f8e7d6c5b4a"


def ctx(events):
    return [e for e in events if "id" not in e]


# ---------------------------------------------------------------- processor
def test_app_switch_only_on_change(harness):
    h = harness()
    win = WindowInfo("Mail - Inbox", "mail")
    h.proc.observe(0.0, win)
    h.proc.observe(0.5, win)
    h.proc.observe(1.0, WindowInfo("Calendar", "calendar"))
    h.click(1.1, 10, 10)
    evs = h.done()
    switches = [e for e in evs if e["kind"] == "app_switch"]
    assert [(e["app_name"], e["window_title"]) for e in switches] == [
        ("mail", "Mail - Inbox"),
        ("calendar", "Calendar"),
    ]
    click = next(e for e in evs if e["kind"] == "click")
    assert click["id"] == 1 and all(e["seq"] == 1 for e in switches)  # ids stay stable


def test_excluded_app_emits_nothing(harness):
    h = harness(exclude_apps=("1password",), record_urls=True, record_clipboard=True)
    pw = WindowInfo("1Password", "1password")
    h.proc.observe_clipboard(0.0, "", pw)
    h.proc.observe(0.1, pw, "https://vault.example.com/")
    h.proc.observe_clipboard(0.2, "hunter2", pw)
    assert ctx(h.done()) == []


def test_urls_are_opt_in_and_stripped(harness):
    off = harness()
    off.proc.observe(0.0, WindowInfo("Docs", "Safari"), "https://example.com/a?x=1")
    assert [e["kind"] for e in ctx(off.done())] == ["app_switch"]

    h = harness(record_urls=True)
    win = WindowInfo("Docs", "Safari")
    h.proc.observe(0.0, win, "https://bob:pw@example.com/a?session=abc#top")
    h.proc.observe(0.5, win, "https://example.com/a?session=other")  # same after stripping
    h.proc.observe(1.0, win, "https://example.com/b")
    urls = [e["url"] for e in ctx(h.done()) if e["kind"] == "url"]
    assert urls == ["https://example.com/a", "https://example.com/b"]


def test_keep_query_still_masks_secrets():
    url = f"https://example.com/cb?user=ann&token={URL_TOKEN}&page=2"
    kept = normalise_url(url, keep_query=True)
    assert URL_TOKEN not in kept and "user=ann" in kept and "page=2" in kept
    assert normalise_url("not a url") is None and normalise_url("") is None


def test_clipboard_baseline_preview_and_masking(harness):
    h = harness(record_clipboard=True)
    win = WindowInfo("Notes", "notes")
    h.proc.observe_clipboard(0.0, "copied before recording", win)
    h.proc.observe_clipboard(0.5, "copied before recording", win)
    long_text = "x" * 70 + GH + " tail"  # the token straddles the 80-character cut
    h.proc.observe_clipboard(1.0, long_text, win)
    h.proc.observe_clipboard(1.5, "secret", WindowInfo("Sign in - Bank", "browser"))
    evs = ctx(h.done())
    assert len(evs) == 2
    assert evs[0]["chars"] == len(long_text) and len(evs[0]["preview"]) == 80
    assert "ghp_" not in evs[0]["preview"] and evs[0]["preview"].startswith("x" * 70)
    assert evs[1]["masked"] is True and "preview" not in evs[1]


def test_empty_clipboard_at_start_is_the_baseline(harness):
    h = harness(record_clipboard=True)
    win = WindowInfo("Notes", "notes")
    h.proc.observe_clipboard(0.0, None, win)  # nothing on the clipboard yet
    h.proc.observe_clipboard(0.7, "first copy", win)
    h.proc.observe_clipboard(1.4, None, win)  # a failed read later changes nothing
    h.proc.observe_clipboard(2.1, "first copy", win)
    assert [e.get("preview") for e in ctx(h.done())] == ["first copy"]


def test_clipboard_off_by_default(harness):
    h = harness()
    win = WindowInfo("Notes", "notes")
    h.proc.observe_clipboard(0.0, "", win)
    h.proc.observe_clipboard(1.0, "something", win)
    assert ctx(h.done()) == []


# ---------------------------------------------------------------- acceptance 3
def _secret_spec(spec):
    spec = json.loads(json.dumps(spec))
    first = next(iter(spec["screens"]))
    spec["screens"][first]["url"] = (
        f"https://admin:{URL_PASSWORD}@tasks.example.com/login?password={URL_PASSWORD}"
        f"&token={URL_TOKEN}"
    )
    typed = next(e for e in spec["events"] if e["kind"] == "type")
    typed["text"] = f"{GH} {CARD}"
    spec["events"].append({"kind": "copy", "screen": typed["screen"], "text": f"card {CARD}"})
    return spec


def test_no_secret_reaches_any_saved_file(tmp_path, spec):
    session = tmp_path / "s"
    simulate(
        _secret_spec(spec),
        session,
        record_typing=True,
        record_urls=True,
        keep_query=True,
        record_clipboard=True,
    )
    _, events = load_session(session)
    kinds = {e["kind"] for e in ctx(events)}
    assert {"app_switch", "url", "clipboard"} <= kinds
    run_export(session, "both", tmp_path / "dist", SkillOptions(out_dir=tmp_path))
    needles = [GH, CARD, CARD.replace(" ", ""), URL_PASSWORD, URL_TOKEN]
    files = [p for p in tmp_path.rglob("*") if p.is_file()]
    assert len(files) > 30
    for p in files:
        data = p.read_bytes()
        for needle in needles:
            assert needle.encode() not in data, f"{needle!r} found in {p}"
    skill_md = next((tmp_path / "dist" / "skill").rglob("SKILL.md")).read_text("utf-8")
    assert "[REDACTED:github-token]" in skill_md and "[REDACTED:card]" in skill_md


# ---------------------------------------------------------------- acceptance 2
def _ring_at(img: Image.Image, x: int, y: int) -> int:
    """How many of 24 points on the marker ring around (x, y) have the accent color."""
    st = annotate.MarkerStyle.for_image(img.width, img.height)
    r = st.radius - st.line / 2
    hits = 0
    for k in range(24):
        a = 2 * math.pi * k / 24
        px, py = round(x + r * math.cos(a)), round(y + r * math.sin(a))
        if 0 <= px < img.width and 0 <= py < img.height:
            cr, cg, cb = img.getpixel((px, py))[:3]
            hits += cr > 200 and cg < 150 and cb < 120
    return hits


def test_ring_on_mixed_scale_monitors(tmp_path):
    screen = {"app": "Viewer", "window_title": "Viewer", "heading": "Viewer", "widgets": []}
    spec = {
        "screen": {"width": 800, "height": 500},
        "monitors": [{"left": 0, "top": 0, "scale": 1.0}, {"left": 800, "top": 0, "scale": 2.0}],
        "screens": {"left": dict(screen, monitor=0), "right": dict(screen, monitor=1)},
        "events": [
            {"kind": "click", "screen": "left", "target": [600, 400]},
            {"kind": "click", "screen": "right", "target": [600, 400]},
        ],
    }
    session = tmp_path / "s"
    simulate(spec, session)
    run_build(session, BuildOptions(formats=("md",), marker="ring", auto_arrows=False))
    doc = read_json(session / "steps.json")
    left, right = doc["steps"]
    assert left["point"]["x"] == 600 and right["point"]["x"] == 1400  # global logical px
    assert (left["point"]["img_x"], left["point"]["img_y"]) == (600, 400)
    assert (right["point"]["img_x"], right["point"]["img_y"]) == (1200, 800)  # 2x pixels
    assert right["image_size"] == [1600, 1000]
    for n, step in enumerate(doc["steps"], 1):
        raw = Image.open(Path(session) / "raw" / f"{step['screenshot']}.png").convert("RGB")
        img, _ = annotate.render(raw, step, n, None, None, "ring", False, False)
        x, y = step["point"]["img_x"], step["point"]["img_y"]
        assert _ring_at(img, x, y) >= 18, f"no ring at the click on step {n}"
        if n == 2:  # a ring at the logical (unscaled) position would be the scaling bug
            assert _ring_at(img, 600, 400) <= 2


def test_skill_places_url_before_and_clipboard_after(tmp_path, spec):
    spec = json.loads(json.dumps(spec))
    first = next(iter(spec["screens"]))
    spec["screens"][first]["url"] = "https://tasks.example.com/projects?page=2"
    spec["events"].insert(1, {"kind": "copy", "screen": first, "text": "Q3 launch plan"})
    session = tmp_path / "s"
    simulate(spec, session, record_urls=True, record_clipboard=True)
    res = run_export(session, "skill", tmp_path / "out", SkillOptions(out_dir=tmp_path))
    body = next((tmp_path / "out" / "skill").rglob("SKILL.md")).read_text("utf-8")
    assert res.ok
    step1 = body.split("1. **", 1)[1].split("2. **", 1)[0]
    assert "Browser at `https://tasks.example.com/projects`" in step1  # before, no query
    assert "Then: copied 14 characters: `Q3 launch plan`" in step1  # after the first click
