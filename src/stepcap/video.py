"""`stepcap video`: the built guide as a how-to MP4 — each step's image on screen for a few
seconds, its text burned in as a caption below it. Optional: it needs ffmpeg-skill.

Every media operation goes through ffmpeg-skill's own scripts
(https://github.com/kajisho5/ffmpeg-skill), run as
``python <ffmpeg-skill>/scripts/<tool>.py ... --json``; stepcap never runs ffmpeg itself.

- ``sequence``: still frames -> silent H.264 video. stepcap lays each step's guide image
  onto a frame with Pillow (as it already does for the guide) and repeats it for the step's
  duration (hard links, so a step costs one PNG on disk).
- ``caption``: the step texts, as an SRT, burned into the band below the image with the
  bundled Noto Sans JP font (``--fonts-dir`` + ``--font``), so Japanese renders on any machine.
- ``check``: ffmpeg-skill's delivery check of the result (default platform: youtube).

ffmpeg-skill is found, in order: ``--ffmpeg-skill DIR``, ``$STEPCAP_FFMPEG_SKILL_DIR``,
``$FFMPEG_SKILL_DIR``, ``~/.claude/skills/ffmpeg-skill``, ``./vendor/ffmpeg-skill``,
``../ffmpeg-skill``. Without it ``stepcap video`` fails with a dependency error; nothing
else in stepcap uses it.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from stepcap.build import naming

REPO_URL = "https://github.com/kajisho5/ffmpeg-skill"
ENV_DIRS = ("STEPCAP_FFMPEG_SKILL_DIR", "FFMPEG_SKILL_DIR")
TOOLS_USED = ("sequence", "caption", "check")
# ffmpeg-skill's contract_version this module was written against ("1.0" since its 0.x)
CONTRACT_RANGE = ">=1.0 <2.0"
FONTS_DIR = Path(__file__).parent / "assets" / "fonts"
FONT_FAMILY = "Noto Sans JP"  # covers Latin and Japanese (OFL, bundled for the app)
DEFAULT_OUTPUT = "guide.mp4"
BAND = 0.18  # share of the frame height kept free below the image for the caption
BACKGROUND = (22, 24, 29)
# reading speed for the minimum time a step stays on screen (characters per second)
CPS_LATIN, CPS_CJK = 15.0, 8.0

Runner = Callable[[list[str]], tuple[int, str, str]]


class VideoError(Exception):
    def __init__(self, message: str, code: str = "failed") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class FfmpegSkill:
    root: Path
    version: str

    def script(self, tool: str) -> Path:
        return self.root / "scripts" / f"{tool}.py"


@dataclass
class VideoOptions:
    output: Path | None = None  # default: SESSION/guide.mp4
    seconds: float = 4.0  # minimum time per step; long texts stay longer
    width: int = 1920
    height: int = 1080
    fps: float = 10.0  # stills: 10 fps plays everywhere and encodes 3x faster than 30
    platform: str = "youtube"  # ffmpeg-skill check.py --platform
    fast: bool = False  # ffmpeg-skill --fast (x264 veryfast, preview quality)
    lang: str | None = None  # language of automatic step texts (as `build --lang`)
    ffmpeg_skill: str | None = None


@dataclass
class Segment:
    image: Path | None  # None: a step without a screenshot (a note) shows the plain frame
    text: str
    start: float
    end: float


@dataclass
class VideoResult:
    session: str
    output: str
    steps: int
    duration: float
    frame: tuple[int, int]
    fps: float
    ffmpeg_skill: dict[str, str]
    font: dict[str, Any] = field(default_factory=dict)
    check: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.check.get("ok"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "session": self.session,
            "output": self.output,
            "steps": self.steps,
            "duration": self.duration,
            "frame": list(self.frame),
            "fps": self.fps,
            "ffmpeg_skill": self.ffmpeg_skill,
            "font": self.font,
            "check": self.check,
            "warnings": self.warnings,
        }


# ------------------------------------------------------------------ locating ffmpeg-skill
def candidates(explicit: str | None = None) -> list[Path]:
    out = [explicit] if explicit else []
    out += [os.environ[e] for e in ENV_DIRS if os.environ.get(e)]
    out += ["~/.claude/skills/ffmpeg-skill", "vendor/ffmpeg-skill", "../ffmpeg-skill"]
    return [Path(c).expanduser() for c in out]


def _found(path: Path) -> FfmpegSkill | None:
    if not all((path / "scripts" / f"{t}.py").is_file() for t in TOOLS_USED):
        return None
    version = "unknown"
    with contextlib.suppress(OSError, ValueError, AttributeError):
        version = str(json.loads((path / "package.json").read_text("utf-8")).get("version"))
    return FfmpegSkill(path.resolve(), version)


def locate(explicit: str | None = None) -> FfmpegSkill | None:
    """The first candidate that has every tool this module runs (sequence, caption, check)."""
    for c in candidates(explicit):
        found = _found(c)
        if found:
            return found
    return None


def missing_message(explicit: str | None = None) -> str:
    where = f"{explicit} has no scripts/{{{','.join(TOOLS_USED)}}}.py; " if explicit else ""
    return (
        f"stepcap video needs ffmpeg-skill ({REPO_URL}), which was not found. {where}"
        f"Clone it and pass --ffmpeg-skill DIR, or set STEPCAP_FFMPEG_SKILL_DIR (or "
        f"FFMPEG_SKILL_DIR). It needs FFmpeg 6.1+ on PATH. Nothing else in stepcap needs it."
    )


def require(explicit: str | None = None) -> FfmpegSkill:
    found = locate(explicit)
    if not found:
        raise VideoError(missing_message(explicit), "dependency_missing")
    return found


def python_exe() -> str:
    """The interpreter that runs ffmpeg-skill's scripts: this one, except inside a frozen
    binary (sys.executable is stepcap itself there)."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    exe = shutil.which("python3") or shutil.which("python")
    if not exe:
        raise VideoError(
            "ffmpeg-skill's scripts need Python 3.10+ on PATH (the stepcap binary has none "
            "inside it for other programs)",
            "dependency_missing",
        )
    return exe


def subprocess_runner(argv: list[str]) -> tuple[int, str, str]:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    p = subprocess.run(
        argv,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        env=env,
        check=False,
    )
    return p.returncode, p.stdout, p.stderr


def run_tool(
    skill: FfmpegSkill,
    tool: str,
    args: list[str],
    runner: Runner | None = None,
    allow_fail: bool = False,
) -> dict[str, Any]:
    """Run one ffmpeg-skill tool with --json and return its JSON document. A non-zero exit
    raises VideoError with the tool's own error message and hint (unless allow_fail: check.py
    exits 1 on a FAIL row and its document is the answer)."""
    run = runner or subprocess_runner  # looked up now, so tests can replace it
    rc, out, err = run([python_exe(), str(skill.script(tool)), *args, "--json"])
    doc: Any = None
    with contextlib.suppress(ValueError):
        doc = json.loads(out)
    if not isinstance(doc, dict):
        last = (err.strip().splitlines() or ["no output"])[-1]
        raise VideoError(f"ffmpeg-skill {tool} exited {rc} without a JSON result: {last}")
    if rc != 0 and not (allow_fail and doc.get("checks")):
        e = doc.get("error") if isinstance(doc.get("error"), dict) else {}
        msg = e.get("message") or f"exited {rc}"
        hint = f" ({e['hint']})" if e.get("hint") else ""
        code = "dependency_missing" if e.get("kind") == "missing_tool" else "failed"
        raise VideoError(f"ffmpeg-skill {tool}: {msg}{hint}", code)
    return doc


# ------------------------------------------------------------------ plan (pure)
def _is_cjk(text: str) -> bool:
    return any(
        "\u3040" <= ch <= "\u30ff" or "\u3400" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef"
        for ch in text
    )


def step_text(n: int, step: dict[str, Any], lang: str) -> str:
    """'N. title' plus the description (blank lines dropped): the same words as the guide."""
    lines = [naming.heading(n, (step.get("title") or "").strip(), lang)]
    desc = (step.get("description") or "").strip()
    lines += [ln.strip() for ln in desc.splitlines() if ln.strip()]
    return "\n".join(lines)


def step_seconds(text: str, minimum: float) -> float:
    """At least `minimum`, longer when the text needs more reading time; in half seconds."""
    cps = CPS_CJK if _is_cjk(text) else CPS_LATIN
    return math.ceil(max(minimum, len(text) / cps) * 2) / 2


def plan(session: Path, doc: dict[str, Any], seconds: float) -> list[Segment]:
    lang = doc.get("lang") or "en"
    out: list[Segment] = []
    t = 0.0
    for n, step in enumerate(doc.get("steps") or [], 1):
        text = step_text(n, step, lang)
        d = step_seconds(text, seconds)
        image = session / step["rendered"] if step.get("rendered") else None
        out.append(Segment(image, text, t, t + d))
        t += d
    return out


def escape_cue(text: str) -> str:
    """SRT text as libass reads it: `{...}` is an override block and `\\N`, `\\n`, `\\h` are
    escapes, so a step that types `C:\\new` or `{id}` would lose characters. Their full-width
    forms (in the bundled font) keep every character visible."""
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝")


def _srt_time(t: float) -> str:
    ms = round(t * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def srt(segments: list[Segment]) -> str:
    blocks = [
        f"{i}\n{_srt_time(s.start)} --> {_srt_time(s.end)}\n{escape_cue(s.text)}\n"
        for i, s in enumerate(segments, 1)
    ]
    return "\n".join(blocks)


def caption_style() -> tuple[int, int]:
    """(--size, --margin) in caption.py's ASS units (a 288-unit-high script, scaled to any
    frame height): two lines fit in the band kept free below the image."""
    band = 288 * BAND
    size = round(band * 0.3)  # two lines of ~1.2 x size fill ~70% of the band
    margin = round((band - 2.4 * size) / 2)
    return size, max(margin, 2)


# ------------------------------------------------------------------ frames
def compose_frame(image: Path | None, width: int, height: int) -> Image.Image:
    """The step image fitted (aspect kept) into the frame above the caption band."""
    frame = Image.new("RGB", (width, height), BACKGROUND)
    if image is None:
        return frame
    with Image.open(image) as src:
        img = src.convert("RGB")
    area_w, area_h = width, height - round(height * BAND)
    scale = min(area_w / img.width, area_h / img.height)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    img = img.resize(size, Image.Resampling.LANCZOS)
    frame.paste(img, ((area_w - size[0]) // 2, (area_h - size[1]) // 2))
    return frame


def _link_or_copy(src: Path, dst: Path) -> None:
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def write_frames(segments: list[Segment], fps: float, width: int, height: int, out: Path) -> int:
    """frame_%06d.png for ffmpeg-skill sequence: one PNG per step, linked for every frame."""
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for i, seg in enumerate(segments):
        base = out / f"step-{i:04d}.png"
        compose_frame(seg.image, width, height).save(base, compress_level=1)
        count = round(seg.end * fps) - round(seg.start * fps)
        for _ in range(count):
            _link_or_copy(base, out / f"frame_{n:06d}.png")
            n += 1
    return n


# ------------------------------------------------------------------ run
def _check_summary(doc: dict[str, Any], platform: str) -> dict[str, Any]:
    rows = [
        {k: r.get(k) for k in ("check", "status", "value", "expected")}
        for r in doc.get("checks") or []
    ]
    failed = [r["check"] for r in rows if r["status"] == "FAIL"]
    return {
        "platform": doc.get("platform") or platform,
        "ok": doc.get("status") != "failed" and not failed and bool(rows),
        "failed": failed,
        "warnings": [r["check"] for r in rows if r["status"] == "WARN"],
        "rows": rows,
    }


def run_video(session: Path, opts: VideoOptions, runner: Runner | None = None) -> VideoResult:
    from stepcap.build.pipeline import BuildOptions, run_build
    from stepcap.session import STEPS_FILE, read_json

    session = Path(session)
    if opts.width % 2 or opts.height % 2 or opts.width < 64 or opts.height < 64:
        raise ValueError("--size: width and height must be even numbers of at least 64")
    if opts.seconds <= 0 or opts.fps <= 0:
        raise ValueError("--seconds and --fps must be greater than 0")
    skill = require(opts.ffmpeg_skill)  # before anything is written
    output = (opts.output or session / DEFAULT_OUTPUT).resolve()

    # the guide images are the video's pictures: (re)build them, as `export` does
    built = run_build(session, BuildOptions(formats=("md",), lang=opts.lang))
    doc = read_json(session / STEPS_FILE)
    segments = plan(session, doc, opts.seconds)
    if not segments:
        raise VideoError("the recording has no steps")
    duration = segments[-1].end
    common = ["--fast"] if opts.fast else []
    size, margin = caption_style()

    with tempfile.TemporaryDirectory(prefix="stepcap-video-") as tmp:
        work = Path(tmp)
        write_frames(segments, opts.fps, opts.width, opts.height, work / "frames")
        slides = work / "slides.mp4"
        run_tool(
            skill,
            "sequence",
            [
                *("--dir", str(work / "frames"), "--pattern", "frame_%06d.png"),
                *("--fps", f"{opts.fps:g}", "--width", str(opts.width)),
                *("--height", str(opts.height), "-o", str(slides), *common),
            ],
            runner,
        )
        cues = work / "steps.srt"
        cues.write_text(srt(segments), encoding="utf-8", newline="\n")
        captioned = work / "video.mp4"
        cap = run_tool(
            skill,
            "caption",
            [
                *(str(slides), "--srt", str(cues), "--lang", doc.get("lang") or "en"),
                *("--fonts-dir", str(FONTS_DIR), "--font", FONT_FAMILY),
                *("--size", str(size), "--margin", str(margin), "--max-lines", "2"),
                *("--position", "bottom", "-o", str(captioned), *common),
            ],
            runner,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        shutil.move(str(captioned), str(output))

    chk = run_tool(skill, "check", [str(output), "--platform", opts.platform], runner, True)
    font = cap.get("font_used") if isinstance(cap.get("font_used"), dict) else {}
    warnings = list(built.warnings)
    for w in (cap.get("diagnostics") or {}).get("warnings") or []:
        # caption.py asks fontconfig whether the font covers the script, and fontconfig does
        # not see --fonts-dir; the bundled Noto Sans JP does cover Japanese
        if isinstance(w, dict) and w.get("code") != "font_lacks_script":
            warnings.append(str(w.get("message")))
    return VideoResult(
        session=str(session),
        output=str(output),
        steps=len(segments),
        duration=duration,
        frame=(opts.width, opts.height),
        fps=opts.fps,
        ffmpeg_skill={"root": str(skill.root), "version": skill.version},
        font=font,
        check=_check_summary(chk, opts.platform),
        warnings=warnings,
    )
