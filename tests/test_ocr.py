"""Names for clicked elements from the screenshot text (RM-020)."""

from __future__ import annotations

import json
import sys

import pytest
from PIL import Image, ImageDraw

from stepcap.build import ocr
from stepcap.build.pipeline import BuildOptions, run_build
from stepcap.session import read_json, write_json
from stepcap.simulate import simulate


def test_clean_and_join():
    assert ocr.clean("  [| ] Private project ") == "Private project"
    assert ocr.clean("☐ Remember me") == "Remember me"
    assert ocr.clean("e.g. Q3 launch plan") is None  # a placeholder, not a name
    assert ocr.clean("例: 山田太郎") is None
    assert ocr.clean("|| -- ==") is None
    assert ocr.clean("+ New project") == "+ New project"
    assert len(ocr.clean("x" * 200)) == ocr.MAX_NAME
    assert ocr._join(["Project", "name"]) == "Project name"
    assert ocr._join(["プロ", "ジェクト", "名"]) == "プロジェクト名"
    assert ocr._join(["保存", "Save"]) == "保存 Save"


def test_tsv_parsing():
    header = "level page_num block_num par_num line_num word_num left top width height conf text"
    tsv = "\t".join(header.split())
    rows = [
        ("5", "1", "1", "1", "1", "1", "10", "5", "40", "12", "96", "Save"),
        ("5", "1", "1", "1", "1", "2", "55", "5", "30", "12", "95", "all"),
        ("5", "1", "1", "1", "2", "1", "10", "30", "20", "12", "12", "~~"),  # low confidence
        ("4", "1", "1", "1", "1", "0", "10", "5", "75", "12", "-1", ""),
    ]
    tsv += "\n" + "\n".join("\t".join(r) for r in rows)
    lines = ocr._tsv_lines(tsv)
    assert [(ln.text, ln.box) for ln in lines] == [("Save all", (10, 5, 75, 12))]


def _fake(lines_by_call):
    """lines_fn that returns prepared lines (in upscaled crop coordinates)."""
    calls = []

    def fn(img, lang):
        calls.append(img.size)
        return lines_by_call(len(calls), img)

    return fn, calls


def test_choosing_the_name():
    img = Image.new("RGB", (800, 600), "white")
    pad, up = ocr.PAD, ocr.UPSCALE

    # a button: text inside the frame, however far from the click
    def inside(n, im):
        return [ocr.Line("Create", (pad + 20 * up, pad + 5 * up, 60 * up, 14 * up))]

    fn, _ = _fake(inside)
    assert ocr.name_at(img, 380, 320, [300, 300, 200, 40], "en", fn) == "Create"

    # a button with nothing readable: no guess from neighbours
    fn, calls = _fake(lambda n, im: [])
    assert ocr.name_at(img, 380, 320, [300, 300, 200, 40], "en", fn) is None
    assert len(calls) == 2  # normal and inverted, inside the frame only

    # a text field (wide and short): the label above it
    def field(n, im):
        return [] if n <= 2 else [ocr.Line("Project name", (pad, pad + 10 * up, 90 * up, 12 * up))]

    fn, _ = _fake(field)
    assert ocr.name_at(img, 400, 320, [200, 300, 500, 40], "en", fn) == "Project name"

    # no frame (or a checkbox): the line nearest to the click, within NEAR_PX
    def near(n, im):
        cx, cy = ocr.CROP_W / 2 * up + pad, ocr.CROP_H / 2 * up + pad
        return [
            ocr.Line("Far away", (int(cx + 150 * up), int(cy), 40, 10)),
            ocr.Line("Private project", (int(cx + 14 * up), int(cy - 6 * up), 100 * up, 12 * up)),
        ]

    fn, _ = _fake(near)
    assert ocr.name_at(img, 400, 300, [393, 293, 14, 14], "en", fn) == "Private project"


@pytest.mark.ocr
@pytest.mark.skipif(sys.platform != "win32", reason="Windows.Media.Ocr")
def test_windows_engine_reads_rendered_text():
    """Calls the backend directly so an error is shown instead of read_lines' []."""
    from winrt.windows.media.ocr import OcrEngine

    from stepcap.build.annotate import font

    img = Image.new("RGB", (480, 120), "white")
    ImageDraw.Draw(img).text((20, 30), "Create project", font=font(36), fill="black")
    langs = [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    lines = ocr._windows(img, "en")
    assert "create project" in " ".join(ln.text for ln in lines).lower(), (langs, lines)


@pytest.mark.ocr
def test_real_ocr_names_the_demo_controls(tmp_path, spec):
    if ocr.backend() is None:
        pytest.skip("no OCR engine on this machine (Linux: apt install tesseract-ocr)")
    session = tmp_path / "s"
    simulate(spec, session)  # no accessibility names: only the pixels
    res = run_build(session, BuildOptions(formats=("md",)))
    doc = read_json(session / "steps.json")
    named = {
        s["id"]: (s.get("element") or {}).get("name", "")
        for s in doc["steps"]
        if (s.get("element") or {}).get("source") == "ocr"
    }
    text = json.dumps(list(named.values())).lower()
    for expected in ("new project", "project name", "private project", "create", "book venue"):
        assert expected in text, (ocr.backend(), named)
    assert res.ocr_named == len(named) >= 5
    first = doc["steps"][0]
    assert first["title"].endswith('"+ New project"') or "New project" in first["title"]
    typed = next(s for s in doc["steps"] if s["kind"] == "type")
    assert typed["input"]["name"] == "project_name"

    # rebuilds keep the names (tried once) and follow a language change
    run_build(session, BuildOptions(formats=("md",), lang="ja"))
    doc = read_json(session / "steps.json")
    assert "をクリック" in doc["steps"][0]["title"] and "New project" in doc["steps"][0]["title"]
    # an edited title is kept
    doc["steps"][0]["title"] = "Open the dialog"
    write_json(session / "steps.json", doc)
    run_build(session, BuildOptions(formats=("md",)))
    assert read_json(session / "steps.json")["steps"][0]["title"] == "Open the dialog"


@pytest.mark.ocr
def test_no_ocr_option(tmp_path, spec):
    session = tmp_path / "s"
    simulate(spec, session)
    res = run_build(session, BuildOptions(formats=("md",), ocr=False))
    doc = read_json(session / "steps.json")
    assert res.ocr_named == 0 and not any(s.get("element") for s in doc["steps"])
    assert doc["steps"][0]["title"].startswith("Click in ")
