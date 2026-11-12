"""Blur secrets that are visible in screenshots (passwords, API keys, access tokens).

Text stepcap saves is masked by ``stepcap.redact``; this module covers the pixels. At build
time each screenshot that has not been checked yet is read by detection-skill's ``text``
tool (https://github.com/kajisho5/detection-skill, Tesseract, local), run as::

    detection text <raw/ID.png> --lang eng --level word --psm 11 --min-score 0 -o <tmp> --json

``--min-score 0`` because keys and tokens are not words: Tesseract reads them with a low
confidence (0.16 for a correctly read fake key in the test fixture), and a missed secret
costs more than a blurred word.

Words that are secrets by themselves (the patterns of ``redact.PATTERNS``: GitHub / OpenAI /
Anthropic / AWS keys, JWTs, URLs with a password or a token parameter, card numbers) and the
value after a label such as ``Password:`` or ``OPENAI_API_KEY =`` are blurred in the
``work/`` copy (pixelated, then a Gaussian blur, as `stepcap edit`'s Blur area), so every
export (guide, checklist, skill references, video) shows the blurred image. ``raw/`` is never
changed. Every blur is listed in ``steps.json`` (``screen_secrets``) and in the build result:
screenshot, rectangle and kind, never the text that was read.

detection-skill is optional and found, in order: ``$STEPCAP_DETECTION`` (the ``detection``
command), ``detection`` on PATH, the ``detection_skill`` package in this Python. Without it
the build says that the screenshots were not checked. ``build --no-secret-scan`` turns it off.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter

from stepcap.redact import leak_kinds

REPO_URL = "https://github.com/kajisho5/detection-skill"
ENV_COMMAND = "STEPCAP_DETECTION"
# detection-skill's contract_version this module was written against
CONTRACT_RANGE = ">=1.0 <2.0"
TOOLS_USED = ("text",)
TIMEOUT = 180  # seconds per screenshot
PAD = 4  # pixels added around a word before blurring it
DOC_KEY = "screen_secrets"

# A label whose value is a secret: "Password:", "API key =", "OPENAI_API_KEY", "client_secret".
_LABEL = re.compile(
    r"(?i)(pass(?:word|wd|code|phrase)?|pwd|secret|token|api[_\- ]?key|access[_\- ]?key"
    r"|private[_\- ]?key|credential)s?"
)
_SEPARATORS = (":", "=", ":=", "：")
_MASKED = re.compile(r"^[•●*·∙⋅◦.]+$")  # a value already shown as dots
_DIGITS = re.compile(r"^[\d\-]+$")

Runner = Callable[[list[str]], tuple[int, str, str]]


@dataclass
class Word:
    text: str
    box: tuple[float, float, float, float]  # x, y, w, h in screenshot pixels

    @property
    def cy(self) -> float:
        return self.box[1] + self.box[3] / 2


def locate() -> list[str] | None:
    """The command that runs detection-skill, or None."""
    env = os.environ.get(ENV_COMMAND)
    if env:
        return [env] if shutil.which(env) or Path(env).is_file() else None
    exe = shutil.which("detection")
    if exe:
        return [exe]
    if not getattr(sys, "frozen", False):
        with contextlib.suppress(Exception):
            import importlib.util

            if importlib.util.find_spec("detection_skill") is not None:
                return [sys.executable, "-m", "detection_skill.cli"]
    return None


def missing_message() -> str:
    return (
        "screenshots were not checked for passwords or keys on screen: detection-skill "
        f"({REPO_URL}) was not found. Install it (pip install git+{REPO_URL}, plus the "
        f"tesseract command) or set {ENV_COMMAND} to its `detection` command; or blur them by "
        "hand in `stepcap edit`."
    )


def _run(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    return p.returncode, p.stdout, p.stderr


def read_words(
    image: Path, command: list[str], runner: Runner | None = None
) -> tuple[list[Word], dict[str, Any]]:
    """Words in ``image`` from ``detection text`` (word level) and its engine block.

    Raises RuntimeError with detection-skill's exit code when it fails.
    """
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "text.json"
        cmd = [*command, "text", str(image), "--lang", "eng", "--level", "word", "--psm", "11"]
        cmd += ["--min-score", "0"]
        code, _stdout, stderr = (runner or _run)([*cmd, "-o", str(out), "--overwrite", "--json"])
        if code != 0 or not out.exists():
            last = (stderr.strip().splitlines() or [""])[-1][:200]
            raise RuntimeError(f"detection text exited {code}: {last}".rstrip(": "))
        doc = json.loads(out.read_text(encoding="utf-8"))
    words = []
    for frame in doc.get("frames") or []:
        for det in frame.get("detections") or []:
            box = det.get("box")
            text = str(det.get("label") or "").strip()
            if text and isinstance(box, list) and len(box) == 4:
                words.append(Word(text, tuple(float(v) for v in box)))  # type: ignore[arg-type]
    return words, doc.get("engine") or {}


def _lines(words: list[Word]) -> list[list[Word]]:
    """Words grouped into lines (vertical overlap), each line left to right."""
    lines: list[list[Word]] = []
    for w in sorted(words, key=lambda w: w.cy):
        for line in lines:
            ref = line[-1]
            if abs(w.cy - ref.cy) <= max(w.box[3], ref.box[3]) * 0.5:
                line.append(w)
                break
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w.box[0]) for line in lines]


def _label_kind(text: str) -> str:
    t = text.lower()
    if "pass" in t or "pwd" in t:
        return "password"
    if "key" in t:
        return "api-key"
    if "token" in t:
        return "token"
    return "secret"


def find(words: list[Word]) -> list[tuple[Word, str]]:
    """(word, kind) for each word that shows a secret. Kinds are fixed labels."""
    hits: dict[int, tuple[Word, str]] = {}
    for line in _lines(words):
        for i, w in enumerate(line):
            kinds = [k for k in leak_kinds(w.text) if k != "card"]
            if kinds:
                hits[id(w)] = (w, kinds[0])
                continue
            m = _LABEL.search(w.text)
            if not m:
                continue
            rest = w.text[m.end() :]
            inline = re.match(r"^\s*(?::=|[:=：])\s*(\S+)", rest)
            if inline and not _MASKED.match(inline.group(1)):  # password=hunter2 in one word
                hits[id(w)] = (w, _label_kind(m.group(0)))
                continue
            j = i + 1
            if rest.strip() in _SEPARATORS:
                pass  # "Password:" - the value follows
            elif j < len(line) and line[j].text in _SEPARATORS and not rest.strip():
                j += 1  # "OPENAI_API_KEY" "=" value
            else:
                continue  # "API keys" as a heading: no value
            prev = line[j - 1]
            for v in line[j:]:
                gap = v.box[0] - (prev.box[0] + prev.box[2])
                if gap > 4 * max(v.box[3], prev.box[3]) or _LABEL.search(v.text):
                    break  # another column, or the next label
                if not _MASKED.match(v.text):
                    hits.setdefault(id(v), (v, _label_kind(m.group(0))))
                prev = v
        joined = " ".join(w.text for w in line)
        if "card" in leak_kinds(joined):
            for w in line:
                if _DIGITS.match(w.text) and sum(c.isdigit() for c in w.text) >= 4:
                    hits.setdefault(id(w), (w, "card"))
    return sorted(hits.values(), key=lambda h: (h[0].box[1], h[0].box[0]))


def blur_region(img: Image.Image, x0: int, y0: int, x1: int, y1: int) -> None:
    """Pixelate, then blur, ``img`` inside the rectangle (in place).

    Pixelating first means a Gaussian blur cannot be partially reversed.
    """
    region = img.crop((x0, y0, x1, y1))
    radius = max(8, min(x1 - x0, y1 - y0) / 4)
    small = region.resize((max(1, (x1 - x0) // 12), max(1, (y1 - y0) // 12)), Image.Resampling.BOX)
    region = small.resize(region.size, Image.Resampling.NEAREST)
    region = region.filter(ImageFilter.GaussianBlur(radius))
    img.paste(region, (x0, y0))


def _rect(box: tuple[float, float, float, float], size: tuple[int, int]) -> list[int] | None:
    x, y, w, h = box
    x0, y0 = max(0, int(x) - PAD), max(0, int(y) - PAD)
    x1, y1 = min(size[0], int(x + w + 0.999) + PAD), min(size[1], int(y + h + 0.999) + PAD)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


@dataclass
class ScanResult:
    checked: int = 0  # screenshots read in this build
    blurs: list[dict[str, Any]] | None = None  # every blur recorded in steps.json
    engine: str | None = None
    warnings: list[str] | None = None


def scan(
    session: Path,
    doc: dict[str, Any],
    command: list[str] | None = None,
    runner: Runner | None = None,
) -> ScanResult:
    """Read and blur every screenshot of ``doc`` not checked yet; record it in ``doc``."""
    from stepcap.build import steps as steps_mod

    state = doc.setdefault(DOC_KEY, {"checked": [], "blurs": []})
    state.setdefault("checked", [])
    state.setdefault("blurs", [])
    res = ScanResult(blurs=state["blurs"], warnings=[])
    todo = []
    for s in doc.get("steps", []):
        sid = s.get("screenshot")
        if (
            sid
            and sid not in state["checked"]
            and sid not in todo
            and steps_mod.raw_path(session, sid).exists()
        ):
            todo.append(sid)
    if not todo:
        return res
    command = command or locate()
    if not command:
        res.warnings.append(missing_message())
        return res
    for sid in todo:
        try:
            words, engine = read_words(steps_mod.raw_path(session, sid), command, runner)
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
            res.warnings.append(f"screenshot {sid} was not checked for secrets ({exc})")
            continue
        if engine:
            res.engine = f"{engine.get('id', '?')} {engine.get('version', '')}".strip()
        found = find(words)
        if found:
            path = steps_mod.ensure_work_copy(session, sid)
            img = Image.open(path).convert("RGB")
            for word, kind in found:
                rect = _rect(word.box, img.size)
                if rect is None:
                    continue
                blur_region(img, rect[0], rect[1], rect[0] + rect[2], rect[1] + rect[3])
                state["blurs"].append({"screenshot": sid, "rect": rect, "kind": kind})
            tmp = path.with_name(path.name + ".tmp")
            img.save(tmp, format="PNG")
            tmp.replace(path)
        state["checked"].append(sid)
        res.checked += 1
    return res


def listing(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Every recorded blur with the numbers of the steps that show it (for output)."""
    numbers: dict[str, list[int]] = {}
    for n, s in enumerate(doc.get("steps", []), 1):
        if s.get("screenshot"):
            numbers.setdefault(s["screenshot"], []).append(n)
    return [
        {**b, "steps": numbers.get(b["screenshot"], [])}
        for b in (doc.get(DOC_KEY) or {}).get("blurs", [])
    ]
