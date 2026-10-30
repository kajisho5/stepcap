"""stepcap video: the how-to MP4 export through ffmpeg-skill.

Unit tests use a stand-in ffmpeg-skill folder and runner. The integration tests run the real
ffmpeg-skill (sequence, caption, check, look) and are skipped when it or ffmpeg is missing:
CI's `video` job provides both (and tesseract-ocr-jpn) and fails if they are skipped.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest
from PIL import Image, ImageOps

from stepcap import video
from stepcap.build.pipeline import BuildOptions, run_build
from stepcap.cli import main
from stepcap.session import STEPS_FILE, read_json, write_json


def fake_skill(root: Path, version: str = "2.21.0", tools=video.TOOLS_USED) -> Path:
    (root / "scripts").mkdir(parents=True)
    for t in tools:
        (root / "scripts" / f"{t}.py").write_text("", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    return root


@pytest.fixture
def no_skill(tmp_path, monkeypatch):
    """No ffmpeg-skill anywhere: env vars unset, an empty home and working folder."""
    for e in video.ENV_DIRS:
        monkeypatch.delenv(e, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    return tmp_path


# ------------------------------------------------------------------ locating
def test_locate_order_and_required_tools(no_skill, monkeypatch):
    assert video.locate() is None
    a = fake_skill(no_skill / "a", "1.0.0")
    b = fake_skill(no_skill / "b", "2.0.0")
    partial = fake_skill(no_skill / "partial", tools=("sequence", "caption"))
    monkeypatch.setenv("FFMPEG_SKILL_DIR", str(a))
    assert video.locate().version == "1.0.0"
    monkeypatch.setenv("STEPCAP_FFMPEG_SKILL_DIR", str(b))  # stepcap's own variable wins
    assert video.locate().version == "2.0.0"
    assert video.locate(str(a)).root == a.resolve()  # --ffmpeg-skill wins over both
    # a folder without every tool is skipped, not used
    assert video.locate(str(partial)).root == b.resolve()


def test_sibling_checkout_is_found(no_skill):
    fake_skill(no_skill / "ffmpeg-skill")  # ../ffmpeg-skill from the working folder
    assert video.locate().root == (no_skill / "ffmpeg-skill").resolve()


def test_video_without_ffmpeg_skill_is_a_clear_dependency_error(no_skill, demo_session, capsys):
    before = sorted(p.name for p in demo_session.iterdir())
    assert main(["video", str(demo_session)]) == 1
    err = capsys.readouterr().err
    assert "needs ffmpeg-skill" in err and video.REPO_URL in err
    assert "STEPCAP_FFMPEG_SKILL_DIR" in err and "--ffmpeg-skill" in err
    # it failed before writing anything
    assert sorted(p.name for p in demo_session.iterdir()) == before


def test_the_rest_of_stepcap_works_without_ffmpeg_skill(no_skill, demo_session):
    assert main(["build", str(demo_session)]) == 0
    assert (demo_session / "guide.html").is_file()


# ------------------------------------------------------------------ plan (pure)
def test_step_text_and_timing():
    step = {"title": "Click Save", "description": "Saves the file.\n\nThen close it."}
    assert video.step_text(3, step, "en") == "Step 3 — Click Save\nSaves the file.\nThen close it."
    assert video.step_seconds("short", 4) == 4
    assert video.step_seconds("x" * 90, 4) == 6  # 15 characters a second
    assert video.step_seconds("設定" * 20, 4) == 5  # 8 a second for Japanese
    assert video.step_seconds("x" * 61, 1) == 4.5  # rounded up to half seconds


def test_srt_times_and_escapes():
    segs = [
        video.Segment(None, "Step 1 — Type C:\\new {id}", 0, 4),
        video.Segment(None, "手順 2\n説明", 4, 3725.5),
    ]
    out = video.srt(segs)
    assert out.startswith("1\n00:00:00,000 --> 00:00:04,000\nStep 1 — Type C:＼new ｛id｝\n")
    assert "2\n00:00:04,000 --> 01:02:05,500\n手順 2\n説明\n" in out
    assert "\\" not in out and "{" not in out


def test_plan_follows_steps_json(demo_session):
    run_build(demo_session, BuildOptions(formats=("md",)))
    doc = read_json(demo_session / STEPS_FILE)
    segs = video.plan(demo_session, doc, 4)
    assert len(segs) == len(doc["steps"])
    assert segs[0].start == 0 and all(a.end == b.start for a, b in pairwise(segs))
    assert all(s.image and s.image.is_file() for s in segs if s.image)
    assert segs[0].text.startswith("Step 1 — ")


def test_compose_frame_keeps_aspect_above_the_caption_band(tmp_path):
    src = tmp_path / "wide.png"
    Image.new("RGB", (400, 100), (255, 0, 0)).save(src)
    frame = video.compose_frame(src, 320, 180)
    assert frame.size == (320, 180)
    assert frame.getpixel((160, 70)) == (255, 0, 0)  # image, scaled to the full width
    assert frame.getpixel((160, 175)) == video.BACKGROUND  # caption band stays free
    assert video.compose_frame(None, 64, 64).getpixel((0, 0)) == video.BACKGROUND


def test_write_frames_counts_and_links(tmp_path):
    segs = [video.Segment(None, "a", 0, 1.5), video.Segment(None, "b", 1.5, 4)]
    n = video.write_frames(segs, 10, 64, 64, tmp_path / "f")
    assert n == 40
    assert len(list((tmp_path / "f").glob("frame_*.png"))) == 40
    assert (tmp_path / "f" / "frame_000039.png").is_file()


# ------------------------------------------------------------------ run (stand-in runner)
class FakeRunner:
    def __init__(self, check_status="completed", fail_tool=None, error=None):
        self.calls: list[list[str]] = []
        self.check_status = check_status
        self.fail_tool = fail_tool
        self.error = error or {"kind": "input", "message": "boom", "hint": "try again"}

    def __call__(self, argv):
        self.calls.append(argv)
        tool = Path(argv[1]).stem
        if tool == self.fail_tool:
            return 1, json.dumps({"status": "failed", "error": self.error}), "error: boom\n"
        if tool in ("sequence", "caption"):
            Path(argv[argv.index("-o") + 1]).write_bytes(b"mp4")
            doc = {"status": "completed", "output": argv[argv.index("-o") + 1]}
            if tool == "caption":
                doc["font_used"] = {"family": "Noto Sans JP", "how": "fonts_dir"}
                doc["diagnostics"] = {"warnings": [{"code": "font_lacks_script", "message": "x"}]}
            return 0, json.dumps(doc), ""
        status = "FAIL" if self.check_status == "failed" else "PASS"
        doc = {
            "status": self.check_status,
            "platform": argv[argv.index("--platform") + 1],
            "checks": [
                {"check": "video codec", "status": status, "value": "h264"},
                {"check": "audio", "status": "WARN", "value": "none"},
            ],
        }
        return (1 if status == "FAIL" else 0), json.dumps(doc), ""

    def args(self, tool):
        return next(c for c in self.calls if Path(c[1]).stem == tool)


def test_run_video_hands_every_media_step_to_ffmpeg_skill(no_skill, demo_session):
    skill = fake_skill(no_skill / "ffmpeg-skill")
    run = FakeRunner()
    res = video.run_video(
        demo_session, video.VideoOptions(ffmpeg_skill=str(skill), fast=True), runner=run
    )
    assert [Path(c[1]).stem for c in run.calls] == ["sequence", "caption", "check"]
    assert all(c[1].startswith(str(skill.resolve())) and c[-1] == "--json" for c in run.calls)
    seq = run.args("sequence")
    assert seq[seq.index("--fps") + 1] == "10" and "--fast" in seq
    cap = run.args("caption")
    assert cap[cap.index("--fonts-dir") + 1] == str(video.FONTS_DIR)
    assert cap[cap.index("--font") + 1] == "Noto Sans JP"
    assert cap[cap.index("--lang") + 1] == "en"
    assert (video.FONTS_DIR / "NotoSansJP-Regular.otf").is_file()
    assert run.args("check")[2] == str(demo_session.resolve() / "guide.mp4")
    assert res.ok and res.output == str(demo_session.resolve() / "guide.mp4")
    assert (demo_session / "guide.mp4").read_bytes() == b"mp4"
    assert res.check["warnings"] == ["audio"] and res.warnings == []
    assert res.font["how"] == "fonts_dir"
    assert res.ffmpeg_skill["version"] == "2.21.0"
    # nothing else (caption's adjusted SRT, frames) is left in the session
    assert not list(demo_session.glob("*.srt")) and not (demo_session / "frames").exists()


def test_cli_exit_follows_ffmpeg_skill_check(no_skill, demo_session, monkeypatch, capsys):
    skill = fake_skill(no_skill / "ffmpeg-skill")
    monkeypatch.setattr(video, "subprocess_runner", FakeRunner(check_status="failed"))
    out = no_skill / "out" / "how-to.mp4"
    argv = ["video", str(demo_session), "-o", str(out), "--ffmpeg-skill", str(skill), "--json"]
    assert main(argv) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False and data["check"]["failed"] == ["video codec"]
    assert out.is_file()  # the file is kept, like ffmpeg-skill's own render

    monkeypatch.setattr(video, "subprocess_runner", FakeRunner())
    assert main(["video", str(demo_session), "-o", str(out), "--ffmpeg-skill", str(skill)]) == 0
    text = capsys.readouterr().out
    assert "check --platform youtube: passed" in text and "how-to.mp4" in text


def test_tool_failure_carries_ffmpeg_skill_message(no_skill, demo_session):
    skill = video.locate(str(fake_skill(no_skill / "ffmpeg-skill")))
    with pytest.raises(video.VideoError, match="ffmpeg-skill caption: boom \\(try again\\)"):
        video.run_tool(skill, "caption", [], FakeRunner(fail_tool="caption"))
    no_ffmpeg = {"kind": "missing_tool", "message": "no ffmpeg"}
    missing = FakeRunner(fail_tool="sequence", error=no_ffmpeg)
    with pytest.raises(video.VideoError) as exc:
        video.run_tool(skill, "sequence", [], missing)
    assert exc.value.code == "dependency_missing"
    with pytest.raises(video.VideoError, match="without a JSON result: Traceback"):
        video.run_tool(skill, "check", [], lambda argv: (1, "", "Traceback\n"))


@pytest.mark.parametrize("args", [["--size", "1921x1080"], ["--size", "big"], ["--seconds", "0"]])
def test_bad_options_are_refused(no_skill, demo_session, capsys, args):
    skill = fake_skill(no_skill / "ffmpeg-skill")
    assert main(["video", str(demo_session), "--ffmpeg-skill", str(skill), *args]) == 1
    assert "stepcap: error:" in capsys.readouterr().err


def test_doctor_reports_video_export():
    from stepcap import doctor

    def check(p):
        return {c.id: c for c in doctor.evaluate({"platform": "linux", **p})}["video"]

    off = check({"video": None})
    assert off.status == doctor.INFO and "STEPCAP_FFMPEG_SKILL_DIR" in off.fix
    on = check({"video": {"root": "/x/ffmpeg-skill", "version": "2.21.0"}})
    assert on.status == doctor.OK and "2.21.0" in on.detail


def test_contract_declares_the_optional_dependency(capsys):
    assert main(["contract", "--json"]) == 0
    c = json.loads(capsys.readouterr().out)
    (dep,) = c["dependencies"]
    assert dep["skill_id"] == "ffmpeg-skill" and dep["required"] is False
    assert dep["version_range"] == video.CONTRACT_RANGE
    assert {"id": "guide.video", "lifecycle": "EXPERIMENTAL", "tool_id": "stepcap/video"} in c[
        "provides"
    ]


# ------------------------------------------------------------------ the real ffmpeg-skill
REAL = video.locate()
needs_real = pytest.mark.skipif(
    REAL is None or shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="needs ffmpeg-skill and ffmpeg",
)

JA_TITLE = "設定画面を開きます"


@needs_real
@pytest.mark.ffmpeg_skill
def test_real_video_passes_ffmpeg_skill_check_and_renders_japanese(demo_session, tmp_path):
    run_build(demo_session, BuildOptions(formats=("md",), lang="ja"))
    doc = read_json(demo_session / STEPS_FILE)
    doc["steps"][0]["title"] = JA_TITLE  # a user's own text: kept by the rebuild
    write_json(demo_session / STEPS_FILE, doc)

    out = tmp_path / "how-to.mp4"
    opts = video.VideoOptions(output=out, seconds=1, width=1280, height=720, fast=True)
    res = video.run_video(demo_session, opts)
    assert res.ok, res.check
    assert res.font.get("family") == "Noto Sans JP" and res.font.get("how") == "fonts_dir"

    # ffmpeg-skill's own check, run again on the file as a user would
    chk = video.run_tool(REAL, "check", [str(out), "--platform", "youtube"], allow_fail=True)
    assert chk.get("status") != "failed", chk.get("error")
    rows = {r["check"]: r["status"] for r in chk["checks"]}
    assert "FAIL" not in rows.values(), rows
    assert rows["video codec"] == "PASS" and rows["vfr"] == "PASS"
    v = video.run_tool(REAL, "probe", [str(out)])["video"]
    assert (v["width"], v["height"], v["fps"]) == (1280, 720, 10.0)

    # the first step's Japanese caption is real glyphs, not tofu: read it back with tesseract
    first = video.plan(demo_session, read_json(demo_session / STEPS_FILE), 1)[0]
    png = tmp_path / "first.png"
    video.run_tool(REAL, "look", [str(out), "--at", f"{first.end / 2:.2f}", "-o", str(png)])
    exe = shutil.which("tesseract")
    have = subprocess.run([exe, "--list-langs"], capture_output=True, text=True) if exe else None
    langs = have.stdout if have else ""
    if "jpn" not in langs.split():
        pytest.skip("no tesseract with Japanese to read the caption back (font and check verified)")
    with Image.open(png) as im:
        gray = im.convert("L")
    band = gray.crop((0, round(gray.height * (1 - video.BAND)), gray.width, gray.height))
    # white text with a dark outline on a dark band -> black text on white for tesseract
    band = ImageOps.invert(band).point(lambda v: 255 if v > 128 else 0)
    band.save(tmp_path / "band.png")
    text = subprocess.run(
        [exe, str(tmp_path / "band.png"), "stdout", "-l", "jpn", "--psm", "7"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.replace(" ", "")
    assert sum(ch in text for ch in JA_TITLE) >= len(JA_TITLE) - 2, text
