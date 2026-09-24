import hashlib
import json
import re

import pytest

from stepcap.build.pipeline import BuildOptions, parse_formats, run_build
from stepcap.session import SessionError


def digest(root):
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def steps_doc(session):
    return json.loads((session / "steps.json").read_text(encoding="utf-8"))


def test_build_outputs(demo_session):
    res = run_build(demo_session, BuildOptions())
    assert res.steps == 12 and res.steps_json == "created"
    md = (demo_session / "guide.md").read_text(encoding="utf-8")
    html = (demo_session / "guide.html").read_text(encoding="utf-8")
    doc = steps_doc(demo_session)

    # markdown references existing images, one per step
    refs = re.findall(r"\]\((images/[^)]+)\)", md)
    assert len(refs) == 12
    assert all((demo_session / r).is_file() for r in refs)
    assert md.startswith("# Create a project and move a card in Acme Tasks")
    assert '## Step 1 — Click in "Projects - Acme Tasks"' in md

    # html is a single file: every image inlined, no external resources
    assert html.count('src="data:image/webp;base64,') == 12
    assert not re.search(r'(src|href)="(https?:)?//', html)
    assert "@media print" in html and "prefers-color-scheme:dark" in html
    assert html.count('<a href="#step-') == 12

    # steps.json is the canonical record
    assert [s["kind"] for s in doc["steps"]][:3] == ["click", "click", "type"]
    s1 = doc["steps"][0]
    assert s1["rendered"] == "images/step-001.webp" and s1["image"] == "work/0001.png"
    assert s1["point"]["img_x"] == 1314


def test_consecutive_identical_screens_reuse_screenshot(demo_session):
    res = run_build(demo_session, BuildOptions())
    doc = steps_doc(demo_session)
    pairs = [(s["own_screenshot"], s["screenshot"]) for s in doc["steps"]]
    # steps 2-5 happen in the same dialog -> all use screenshot 0002
    assert [p[1] for p in pairs[1:5]] == ["0002"] * 4
    # the context menu (step 8) is a different screen
    assert pairs[7] == ("0008", "0008")
    assert res.reused_screenshots == sum(1 for a, b in pairs if a != b) >= 4
    work = sorted(p.name for p in (demo_session / "work").iterdir())
    assert "0003.png" not in work  # reused screenshot is not copied


def test_build_is_idempotent(demo_session):
    run_build(demo_session, BuildOptions())
    before = digest(demo_session)
    res = run_build(demo_session, BuildOptions())
    assert res.written == [] and res.steps_json == "kept"
    assert digest(demo_session) == before


def test_human_edits_in_steps_json_survive_rebuild(demo_session):
    run_build(demo_session, BuildOptions())
    doc = steps_doc(demo_session)
    doc["steps"][0]["title"] = "Open the New project dialog"
    doc["steps"][0]["description"] = "Top right corner."
    del doc["steps"][5]  # delete a step
    doc["steps"][1], doc["steps"][2] = doc["steps"][2], doc["steps"][1]  # reorder
    (demo_session / "steps.json").write_text(json.dumps(doc), encoding="utf-8")

    run_build(demo_session, BuildOptions())
    after = steps_doc(demo_session)
    assert after["steps"][0]["title"] == "Open the New project dialog"
    assert after["steps"][0]["description"] == "Top right corner."
    assert len(after["steps"]) == 11
    assert after["steps"][1]["kind"] == "type"
    md = (demo_session / "guide.md").read_text(encoding="utf-8")
    assert "## Step 1 — Open the New project dialog" in md
    assert not (demo_session / "images" / "step-012.webp").exists()  # stale image removed


def test_lang_switch_regenerates_only_untouched_texts(demo_session):
    run_build(demo_session, BuildOptions())
    doc = steps_doc(demo_session)
    doc["steps"][0]["title"] = "Custom"
    (demo_session / "steps.json").write_text(json.dumps(doc), encoding="utf-8")
    run_build(demo_session, BuildOptions(lang="ja"))
    doc = steps_doc(demo_session)
    assert doc["lang"] == "ja"
    assert doc["steps"][0]["title"] == "Custom"
    assert doc["steps"][1]["title"] == "「New project - Acme Tasks」でクリック"
    assert "## 手順 2 — " in (demo_session / "guide.md").read_text(encoding="utf-8")
    # lang is remembered
    run_build(demo_session, BuildOptions())
    assert steps_doc(demo_session)["lang"] == "ja"


def test_reset_discards_edits(demo_session):
    run_build(demo_session, BuildOptions())
    doc = steps_doc(demo_session)
    doc["steps"][0]["title"] = "Custom"
    (demo_session / "steps.json").write_text(json.dumps(doc), encoding="utf-8")
    res = run_build(demo_session, BuildOptions(reset=True))
    assert res.steps_json == "reset"
    assert steps_doc(demo_session)["steps"][0]["title"] != "Custom"


def test_title_option_and_formats(demo_session):
    run_build(demo_session, BuildOptions(formats=("html",), title="My guide"))
    assert not (demo_session / "guide.md").exists()
    assert not (demo_session / "images").exists()
    assert "<title>My guide</title>" in (demo_session / "guide.html").read_text(encoding="utf-8")
    assert steps_doc(demo_session)["title"] == "My guide"


def test_zoom_and_jpeg(demo_session):
    run_build(demo_session, BuildOptions(zoom=600, image_format="jpeg", formats=("md",)))
    assert (demo_session / "images" / "step-001.jpg").is_file()
    assert (demo_session / "images" / "step-001-full.jpg").is_file()
    assert "step-001-full.jpg" in (demo_session / "guide.md").read_text(encoding="utf-8")


def test_raw_is_never_modified(demo_session):
    raw_before = digest(demo_session / "raw")
    run_build(demo_session, BuildOptions(zoom=500))
    run_build(demo_session, BuildOptions(lang="ja", reset=True))
    assert digest(demo_session / "raw") == raw_before


def test_dry_run_writes_nothing(demo_session):
    before = digest(demo_session)
    res = run_build(demo_session, BuildOptions(dry_run=True))
    assert res.steps == 12 and "guide.html" in res.outputs
    assert digest(demo_session) == before


def test_errors(tmp_path):
    with pytest.raises(SessionError):
        run_build(tmp_path / "missing", BuildOptions())
    with pytest.raises(SessionError):
        run_build(tmp_path, BuildOptions())
    with pytest.raises(ValueError):
        parse_formats("pdf")
    assert parse_formats("html, md,html") == ("html", "md")


def test_invalid_steps_json_is_reported(demo_session):
    run_build(demo_session, BuildOptions())
    (demo_session / "steps.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SessionError, match="--reset"):
        run_build(demo_session, BuildOptions())


def test_markdown_escapes_window_titles(tmp_path, spec):
    from stepcap.simulate import simulate

    spec["screens"]["home"]["window_title"] = "*bold* [link](x) <script>"
    simulate(spec, tmp_path / "s")
    run_build(tmp_path / "s", BuildOptions())
    md = (tmp_path / "s" / "guide.md").read_text(encoding="utf-8")
    assert r"\*bold\* \[link\](x) \<script\>" in md
    html = (tmp_path / "s" / "guide.html").read_text(encoding="utf-8")
    assert '<script>"' not in html and "&lt;script&gt;" in html
