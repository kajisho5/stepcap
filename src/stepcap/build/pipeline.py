"""`stepcap build`: session -> steps.json + guide.md/images + guide.html."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image, features

from stepcap import __version__
from stepcap.build import annotate, checklist, html, markdown, naming
from stepcap.build import steps as steps_mod
from stepcap.session import STEPS_FILE, SessionError, load_session, write_json

IMAGES_DIR = "images"
GUIDE_MD = "guide.md"
GUIDE_HTML = "guide.html"
CHECKLIST_HTML = "checklist.html"
ALL_FORMATS = ("md", "html", "checklist")
_STEP_IMAGE = re.compile(r"^step-\d{3,}(-full)?\.(webp|jpg|png)$")


@dataclass
class BuildOptions:
    formats: tuple[str, ...] = ALL_FORMATS
    zoom: int | None = None
    width: int | None = 1600
    lang: str | None = None
    title: str | None = None
    image_format: str = "webp"
    quality: int = 85
    reset: bool = False
    dry_run: bool = False
    marker: str | None = None  # box | ring; None = keep the value saved in steps.json
    spotlight: bool | None = None  # dim around the target; None = keep saved value
    auto_arrows: bool | None = None  # arrow to small targets; None = keep saved value
    ocr: bool = True  # name unnamed clicked elements from the screenshot text (build/ocr.py)


@dataclass
class BuildResult:
    session: str
    steps: int
    outputs: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    reused_screenshots: int = 0
    steps_json: str = "created"  # created | kept | reset
    image_format: str = "webp"
    warnings: list[str] = field(default_factory=list)
    ocr_named: int = 0  # steps named from the screenshot text in this build

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def parse_formats(value: str) -> tuple[str, ...]:
    fmts = tuple(dict.fromkeys(f.strip().lower() for f in value.split(",") if f.strip()))
    bad = [f for f in fmts if f not in ALL_FORMATS]
    if bad or not fmts:
        raise ValueError(f"unknown format(s) {', '.join(bad) or '(none)'}; use md, html, checklist")
    return fmts


def _write_bytes(path: Path, data: bytes, res: BuildResult, root: Path) -> None:
    rel = path.relative_to(root).as_posix()
    if path.exists() and path.read_bytes() == data:
        res.unchanged.append(rel)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    res.written.append(rel)


def meta_line(doc: dict[str, Any], meta: dict[str, Any], lang: str) -> str:
    parts = [naming.text(lang, "steps_count", n=len(doc["steps"]))]
    started = str(meta.get("started") or "")[:10]
    if started:
        parts.append(started)
    parts.append(naming.text(lang, "generated", version=__version__))
    return " · ".join(parts)


def load_or_create_steps(session: Path, opt: BuildOptions, res: BuildResult):
    meta, events = load_session(session)
    existing = None if opt.reset else steps_mod.load_steps(session)
    if existing is not None:
        lang = naming.check_lang(opt.lang or existing.get("lang") or "en")
        doc = steps_mod.refresh_auto_texts(existing, events, lang)
        res.steps_json = "kept"
    else:
        lang = naming.check_lang(opt.lang or "en")
        doc = steps_mod.create_steps(session, meta, events, lang)
        res.steps_json = "reset" if opt.reset else "created"
    steps_mod.detect_boxes(session, doc["steps"])  # older steps.json files have no boxes yet
    if opt.ocr:
        res.ocr_named = steps_mod.ocr_names(session, doc["steps"], doc["lang"])
    marker = opt.marker or doc.get("marker") or "box"
    if marker not in annotate.MARKERS:
        raise ValueError(f"unknown marker {marker!r}; use box or ring")
    doc["marker"] = marker
    for key, value, default in (
        ("spotlight", opt.spotlight, False),
        ("auto_arrows", opt.auto_arrows, True),
    ):
        doc[key] = bool(value if value is not None else doc.get(key, default))
    if opt.title:
        doc["title"] = opt.title
        doc["auto_title"] = None
    return meta, doc


def run_build(session: Path, opt: BuildOptions) -> BuildResult:
    session = Path(session)
    if not 1 <= opt.quality <= 100:
        raise ValueError("--quality must be between 1 and 100")
    if opt.image_format not in annotate.FORMATS:
        raise ValueError(f"unknown image format {opt.image_format!r}; use webp, jpeg or png")
    res = BuildResult(session=str(session), steps=0)
    if opt.image_format == "webp" and not features.check("webp"):
        opt.image_format = "jpeg"
        res.warnings.append("Pillow was built without WebP support; using JPEG")
    res.image_format = opt.image_format
    meta, doc = load_or_create_steps(session, opt, res)
    lang = doc["lang"]
    res.steps = len(doc["steps"])
    res.reused_screenshots = sum(
        1
        for s in doc["steps"]
        if s.get("screenshot") and s["screenshot"] != s.get("own_screenshot")
    )

    want_md = "md" in opt.formats
    want_html = "html" in opt.formats
    want_checklist = "checklist" in opt.formats
    ext = annotate.extension(opt.image_format)
    mime = annotate.FORMATS[opt.image_format][1]
    res.outputs = [STEPS_FILE]
    if want_md:
        res.outputs += [GUIDE_MD, IMAGES_DIR + "/"]
    if want_html:
        res.outputs.append(GUIDE_HTML)
    if want_checklist:
        res.outputs.append(CHECKLIST_HTML)
    if opt.dry_run:
        return res

    images: list[dict[str, Any]] = []
    thumbs: list[dict[str, Any]] = []
    expected: set[str] = set()
    loaded: dict[str, Image.Image] = {}
    for n, step in enumerate(doc["steps"], 1):
        sid = step.get("screenshot")
        entry: dict[str, Any] = {"mime": mime}
        small: dict[str, Any] = {"mime": mime}
        step["rendered"] = None
        step.pop("rendered_full", None)
        if sid:
            if sid not in loaded:
                loaded.clear()
                src_path = steps_mod.ensure_work_copy(session, sid)
                loaded[sid] = Image.open(src_path).convert("RGB")
            main, thumb = annotate.render(
                loaded[sid],
                step,
                n,
                opt.width,
                opt.zoom,
                doc["marker"],
                doc["spotlight"],
                doc["auto_arrows"],
            )
            entry["main_bytes"] = annotate.encode(main, opt.image_format, opt.quality)
            entry["main_size"] = main.size
            name = f"{IMAGES_DIR}/step-{n:03d}.{ext}"
            entry["main"] = name
            if thumb is not None:
                entry["thumb_bytes"] = annotate.encode(thumb, opt.image_format, opt.quality)
                entry["thumb_size"] = thumb.size
                entry["thumb"] = f"{IMAGES_DIR}/step-{n:03d}-full.{ext}"
            if want_md:
                _write_bytes(session / name, entry["main_bytes"], res, session)
                expected.add(Path(name).name)
                step["rendered"] = name
                if thumb is not None:
                    _write_bytes(session / entry["thumb"], entry["thumb_bytes"], res, session)
                    expected.add(Path(entry["thumb"]).name)
                    step["rendered_full"] = entry["thumb"]
            if want_checklist:
                crop, _ = annotate.render(
                    loaded[sid],
                    step,
                    n,
                    checklist.THUMB_WIDTH,
                    checklist.THUMB_ZOOM,
                    doc["marker"],
                    doc["spotlight"],
                    doc["auto_arrows"],
                )
                small["bytes"] = annotate.encode(crop, opt.image_format, opt.quality)
                small["size"] = crop.size
        images.append(entry)
        thumbs.append(small)

    line = meta_line(doc, meta, lang)
    if want_md:
        _write_bytes(
            session / GUIDE_MD, markdown.render(doc, images, line).encode("utf-8"), res, session
        )
        img_dir = session / IMAGES_DIR
        if img_dir.is_dir():
            for f in sorted(img_dir.iterdir()):
                if f.is_file() and _STEP_IMAGE.match(f.name) and f.name not in expected:
                    f.unlink()
                    res.removed.append(f"{IMAGES_DIR}/{f.name}")
    if want_html:
        _write_bytes(
            session / GUIDE_HTML,
            html.render(doc, images, line, __version__).encode("utf-8"),
            res,
            session,
        )

    if want_checklist:
        _write_bytes(
            session / CHECKLIST_HTML,
            checklist.render(doc, thumbs, line, __version__).encode("utf-8"),
            res,
            session,
        )

    doc["generator"] = f"stepcap {__version__}"
    if write_json(session / STEPS_FILE, doc):
        res.written.append(STEPS_FILE)
    else:
        res.unchanged.append(STEPS_FILE)
    return res


__all__ = ["BuildOptions", "BuildResult", "SessionError", "parse_formats", "run_build"]
