"""Name the clicked element from the screenshot text when the OS gave no name (RM-020).

Many apps expose no names to UI Automation / Accessibility, so a step can only
say "Click in <window>". At build time stepcap reads the text in a small area
around the click and uses the nearest line as the element name ("Click "Save"").

Backends, all on this computer (nothing is sent anywhere):
  Windows  Windows.Media.Ocr (built in) via pywinrt
  macOS    Vision framework (built in) via pyobjc
  Linux    the `tesseract` command, if installed (apt install tesseract-ocr)

Only a crop around the click is read, the result is masked like every other
text (secrets), and it can be turned off with `build --no-ocr`.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

MAX_NAME = 60
CROP_W, CROP_H = 320, 90  # around the click when there is no detected frame
MAX_BOX_W, MAX_BOX_H = 700, 160  # a detected frame bigger than this is not one control
NEAR_PX = 40  # a line further than this from the click is not its label
UPSCALE = 2  # small UI text reads better enlarged
PAD = 12  # margin added around a crop (in upscaled pixels)


@dataclass
class Line:
    text: str
    box: tuple[int, int, int, int]  # x, y, w, h in the image passed to read_lines

    def distance(self, x: float, y: float) -> float:
        bx, by, bw, bh = self.box
        dx = max(bx - x, 0, x - (bx + bw))
        dy = max(by - y, 0, y - (by + bh))
        return (dx * dx + dy * dy) ** 0.5


def backend() -> str | None:
    if sys.platform == "win32":
        try:
            from winrt.windows.media.ocr import OcrEngine  # noqa: F401
        except Exception:
            return None
        return "windows-ocr"
    if sys.platform == "darwin":
        try:
            import Vision  # noqa: F401
        except Exception:
            return None
        return "macos-vision"
    return "tesseract" if shutil.which("tesseract") else None


# ------------------------------------------------------------------ backends
def _windows(img: Image.Image, lang: str) -> list[Line]:
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter

    engine = None
    tag = "ja" if lang == "ja" else "en-US"
    with contextlib.suppress(Exception):
        if OcrEngine.is_language_supported(Language(tag)):
            engine = OcrEngine.try_create_from_language(Language(tag))
    engine = engine or OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        return []
    rgba = img.convert("RGBA")
    r, g, b, a = rgba.split()
    bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
    writer = DataWriter()
    writer.write_bytes(bgra)
    bitmap = SoftwareBitmap(
        BitmapPixelFormat.BGRA8, rgba.width, rgba.height, BitmapAlphaMode.PREMULTIPLIED
    )
    bitmap.copy_from_buffer(writer.detach_buffer())

    async def run():
        return await engine.recognize_async(bitmap)

    result = asyncio.run(run())
    lines = []
    for line in result.lines:
        rects = [w.bounding_rect for w in line.words]
        if not rects:
            continue
        x0 = min(r.x for r in rects)
        y0 = min(r.y for r in rects)
        x1 = max(r.x + r.width for r in rects)
        y1 = max(r.y + r.height for r in rects)
        text = _join([w.text for w in line.words])
        lines.append(Line(text, (int(x0), int(y0), int(x1 - x0), int(y1 - y0))))
    return lines


def _macos(img: Image.Image, lang: str) -> list[Line]:
    import Vision
    from Foundation import NSData

    buf = io.BytesIO()
    img.convert("RGB").save(buf, "PNG")
    data = NSData.dataWithBytes_length_(buf.getvalue(), len(buf.getvalue()))
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, None)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setUsesLanguageCorrection_(False)
    langs = ["ja-JP", "en-US"] if lang == "ja" else ["en-US", "ja-JP"]
    with contextlib.suppress(Exception):
        request.setRecognitionLanguages_(langs)
    ok = handler.performRequests_error_([request], None)
    if isinstance(ok, tuple):
        ok = ok[0]
    if not ok:
        return []
    w, h = img.size
    lines = []
    for obs in request.results() or []:
        cands = obs.topCandidates_(1)
        if not cands:
            continue
        bb = obs.boundingBox()  # normalised, origin at the bottom left
        x, y = bb.origin.x * w, (1 - bb.origin.y - bb.size.height) * h
        lines.append(
            Line(
                str(cands[0].string()),
                (int(x), int(y), int(bb.size.width * w), int(bb.size.height * h)),
            )
        )
    return lines


def _tesseract(img: Image.Image, lang: str) -> list[Line]:
    exe = shutil.which("tesseract")
    if not exe:
        return []
    have = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=10)
    installed = set(have.stdout.split())
    # eng first keeps spaces between Latin words; spaces tesseract puts between Japanese
    # words are removed again by _join
    langs = [x for x in ("eng", "jpn") if x in installed]
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "crop.png"
        img.convert("RGB").save(path)
        for psm in ("6", "7"):  # a block of text; then a single line (short button labels)
            cmd = [exe, str(path), "stdout", "--psm", psm]
            if langs:
                cmd += ["-l", "+".join(langs)]
            out = subprocess.run([*cmd, "tsv"], capture_output=True, text=True, timeout=20)
            lines = _tsv_lines(out.stdout) if out.returncode == 0 else []
            if lines:
                return lines
    return []


def _tsv_lines(tsv: str) -> list[Line]:
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE):
        if row.get("level") != "5" or not (row.get("text") or "").strip():
            continue
        with contextlib.suppress(ValueError):
            if float(row.get("conf") or -1) < 40:
                continue
        groups.setdefault((row["block_num"], row["par_num"], row["line_num"]), []).append(row)
    lines = []
    for words in groups.values():
        x0 = min(int(w["left"]) for w in words)
        y0 = min(int(w["top"]) for w in words)
        x1 = max(int(w["left"]) + int(w["width"]) for w in words)
        y1 = max(int(w["top"]) + int(w["height"]) for w in words)
        text = _join([w["text"] for w in words])
        lines.append(Line(text, (x0, y0, x1 - x0, y1 - y0)))
    return lines


def _is_cjk(text: str) -> bool:
    return any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text)


def _join(words: list[str]) -> str:
    """Words of a line: no space between two Japanese words, a space otherwise."""
    out = ""
    for w in words:
        if out and w and not (_is_cjk(out[-1]) and _is_cjk(w[0])):
            out += " "
        out += w
    return out


_BACKENDS = {"windows-ocr": _windows, "macos-vision": _macos, "tesseract": _tesseract}


def read_lines(img: Image.Image, lang: str = "en", engine: str | None = None) -> list[Line]:
    """Text lines in ``img``; [] when no backend works (never raises)."""
    name = engine or backend()
    fn = _BACKENDS.get(name or "")
    if fn is None:
        return []
    try:
        return [ln for ln in fn(img, lang) if ln.text.strip()]
    except Exception:
        return []


# ------------------------------------------------------------------ choosing the name
PLACEHOLDER = re.compile(r"^(e\.?g\.?|ex\.|例[:：)）]?|例えば)\s*", re.I)
SMALL_BOX = 40  # checkboxes and radio buttons: their label is next to them


LEADING_JUNK = re.compile(r"^[\[\]()|\s□☐☑✓✔○●◯◉_=~-]+(?=\w)")


def clean(text: str) -> str | None:
    text = re.sub(r"\s+", " ", text).strip(" |:;,.·•-–—_=~\"'`")
    text = LEADING_JUNK.sub("", text)  # a checkbox read as "[| ]"
    if PLACEHOLDER.match(text):
        return None  # "e.g. Q3 launch plan" is an example value, not the field's name
    letters = sum(ch.isalnum() for ch in text)
    if letters < 2 or letters < len(text) / 3:
        return None  # noise such as "|| --"
    return text if len(text) <= MAX_NAME else text[: MAX_NAME - 1].rstrip() + "…"


def _nearest(
    image: Image.Image,
    region: tuple[int, int, int, int],
    x: float,
    y: float,
    lang: str,
    lines_fn,
    limit: float | None,
) -> str | None:
    """Nearest clean line to (x, y) in ``region`` (dark-on-light, then inverted)."""
    W, H = image.size
    x0, y0 = max(0, region[0]), max(0, region[1])
    x1, y1 = min(W, region[2]), min(H, region[3])
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = ImageOps.autocontrast(ImageOps.grayscale(image.crop((x0, y0, x1, y1))))
    crop = crop.resize((crop.width * UPSCALE, crop.height * UPSCALE), Image.LANCZOS)
    # a margin in the background colour: OCR engines miss text that touches the edge
    crop = ImageOps.expand(crop, border=PAD, fill=crop.getpixel((0, 0)))
    px, py = (x - x0) * UPSCALE + PAD, (y - y0) * UPSCALE + PAD
    for variant in (crop, ImageOps.invert(crop)):  # light text on buttons reads inverted
        best = None
        for ln in lines_fn(variant.convert("RGB"), lang):
            text = clean(ln.text)
            if not text:
                continue
            d = ln.distance(px, py) / UPSCALE
            if (limit is None or d <= limit) and (best is None or d < best[0]):
                best = (d, text)
        if best:
            return best[1]
    return None


def name_at(
    image: Image.Image,
    x: float,
    y: float,
    box: list[int] | None = None,
    lang: str = "en",
    lines_fn=read_lines,
    kind: str = "click",
) -> str | None:
    """The text of the control at (x, y).

    With a detected frame (button, card, field): the text inside it nearest to the click;
    for a text field without a name inside, the label just above or left of it. With no
    frame, or a tiny one (checkbox): the line nearest to the click within NEAR_PX.
    """
    usable = box and SMALL_BOX <= box[2] <= MAX_BOX_W and 8 <= box[3] <= MAX_BOX_H
    if usable:
        bx, by, bw, bh = box
        inside = (bx + 4, by + 4, bx + bw - 4, by + bh - 4)  # without the rounded border
        name = _nearest(image, inside, x, y, lang, lines_fn, None)
        field = bw >= 6 * bh  # wide and short: a text field, named by its label
        if kind != "type" and not field:
            return name  # a button without readable text: no guess from its neighbours
        above = (bx - 8, by - 44, bx + bw, by + 2)  # "Project name" over its field
        label = _nearest(image, above, bx, by, lang, lines_fn, 44)
        if label:
            return label
        left = (bx - 220, by - 2, bx + 2, by + bh + 2)  # "Name:" left of its field
        label = _nearest(image, left, bx, by + bh / 2, lang, lines_fn, 60)
        return label or name
    area = (int(x - CROP_W / 2), int(y - CROP_H / 2), int(x + CROP_W / 2), int(y + CROP_H / 2))
    return _nearest(image, area, x, y, lang, lines_fn, NEAR_PX)
