"""Regenerate every image used by README.md / README.ja.md.

    python demos/build.py            # GIF + sample images (no browser needed)
    python demos/build.py --browser  # also guide/edit UI screenshots (needs playwright)

Pipeline: tests/fixtures/make_events.py -> `stepcap simulate` -> `stepcap build`
-> frames from the annotated step images -> docs/demo/demo.gif, plus
`stepcap skill` -> docs/demo/guide-and-skill.png (guide left, SKILL.md right).
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
import threading
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))

from make_events import make_events  # noqa: E402

from stepcap.build.annotate import font  # noqa: E402
from stepcap.build.pipeline import BuildOptions, run_build  # noqa: E402
from stepcap.session import SESSION_FILE, read_json, write_json  # noqa: E402
from stepcap.simulate import simulate  # noqa: E402
from stepcap.skill import frontmatter  # noqa: E402
from stepcap.skill.run import SkillOptions, run_export, run_skill  # noqa: E402

OUT = ROOT / "demos" / "out"
DOCS = ROOT / "docs" / "demo"
SAMPLE = DOCS / "sample"
SKILL_NAME = "create-project-move-card"
REFINED = SAMPLE / "SKILL.refined-by-claude.md"  # one real `--agent claude` run, kept as is
FIXED_START = "2026-09-24T10:00:00+09:00"  # pinned so sample outputs do not change daily
W = 960  # GIF width
CAPTION_H = 92
BG = (22, 24, 29)
FG = (232, 234, 238)
MUTED = (150, 156, 168)
ACCENT = (255, 106, 61)


def terminal_frame(lines: list[tuple[str, tuple[int, int, int]]], h: int) -> Image.Image:
    img = Image.new("RGB", (W, h), BG)
    d = ImageDraw.Draw(img)
    for i, col in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        d.ellipse((18 + i * 22, 16, 30 + i * 22, 28), fill=col)
    y = 64
    for text, color in lines:
        d.text((32, y), text, font=font(24), fill=color)
        y += 40
    return img


def step_frame(src: Path, n: int, total: int, title: str, h: int) -> Image.Image:
    shot = Image.open(src).convert("RGB")
    shot = shot.resize((W, round(shot.height * W / shot.width)), Image.Resampling.LANCZOS)
    img = Image.new("RGB", (W, h), BG)
    img.paste(shot, (0, 0))
    d = ImageDraw.Draw(img)
    y = shot.height
    d.rectangle((0, y, W, h), fill=BG)
    d.text((24, y + 16), f"Step {n} — {title}", font=font(22), fill=FG)
    d.text(
        (24, y + 52), "$ stepcap build demo  ->  guide.md / guide.html", font=font(18), fill=MUTED
    )
    d.text((W - 24, y + 52), f"{n}/{total}", font=font(18), fill=ACCENT, anchor="ra")
    return img


def make_gif(session: Path, doc: dict) -> Path:
    steps = doc["steps"]
    first = Image.open(session / steps[0]["rendered"])
    h = round(first.height * W / first.width) + CAPTION_H
    frames = [
        terminal_frame(
            [
                ("$ stepcap record -o demo", FG),
                ("stepcap: recording to demo", MUTED),
                ("  F9 stop · F8 pause · F7 manual step with a note", MUTED),
                ("  #1  single-click   Projects - Acme Tasks", FG),
                ("  #2  single-click   New project - Acme Tasks", FG),
                ("  #3  type           (12 chars, content not recorded)", FG),
                ("  ...", MUTED),
                (f"stepcap: saved {len(steps)} steps to demo", ACCENT),
            ],
            h,
        )
    ]
    durations = [2600]
    for n, s in enumerate(steps, 1):
        frames.append(step_frame(session / s["rendered"], n, len(steps), s["title"], h))
        durations.append(1500)
    frames.append(
        terminal_frame(
            [
                ("$ stepcap export demo --format both -o dist", FG),
                (f"Guide dist/guide: {len(steps)} steps", MUTED),
                ("  guide.md, guide.html (single file), checklist.html", FG),
                ("Skill 'create-a-project-...': SKILL.md + references/", MUTED),
                ("  valid (Agent Skills spec + no secrets)", FG),
                ("$ stepcap edit demo  # reorder, rename, blur, inputs", ACCENT),
            ],
            h,
        )
    )
    durations.append(3200)
    pal = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=128) for f in frames]
    out = DOCS / "demo.gif"
    pal[0].save(
        out,
        save_all=True,
        append_images=pal[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=1,
    )
    return out


def _wrap(text: str, width: int) -> list[str]:
    out = []
    while len(text) > width:
        cut = text.rfind(" ", 0, width)
        cut = cut if cut > width // 2 else width
        out.append(text[:cut])
        text = "  " + text[cut:].lstrip()
    return [*out, text]


def guide_and_skill(session: Path, doc: dict) -> Path:
    """One recording -> guide for people (left) and SKILL.md for agents (right)."""
    res = run_skill(session, SkillOptions(out_dir=OUT / "skill", name="create-project-move-card"))
    _, body = frontmatter.parse((Path(res.skill_dir) / "SKILL.md").read_text("utf-8"))
    w, h, pad = 1600, 900, 28
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    half = w // 2
    d.text((pad, 20), "For people: guide.html / guide.md", font=font(26), fill=ACCENT)
    d.text((half + pad, 20), "For agents: SKILL.md + references/", font=font(26), fill=ACCENT)
    d.line((half, 16, half, h - 16), fill=(60, 64, 74), width=2)

    step = doc["steps"][1]
    shot = Image.open(session / step["rendered"]).convert("RGB")
    sw = half - 2 * pad
    shot = shot.resize((sw, round(shot.height * sw / shot.width)), Image.Resampling.LANCZOS)
    img.paste(shot, (pad, 70))
    y = 70 + shot.height + 18
    d.text((pad, y), f"Step 2 - {step['title']}", font=font(24), fill=FG)
    y += 40
    for n, s in enumerate(doc["steps"][2:6], 3):
        d.text((pad, y), f"Step {n} - {s['title']}"[:62], font=font(20), fill=MUTED)
        y += 32

    lines = []
    for raw in body.strip().splitlines():
        if raw.startswith("<!--"):
            continue
        lines += _wrap(raw, 60) if raw else [""]
    y = 70
    for line in lines:
        if y > h - 40:
            d.text((half + pad, y), "...", font=font(18), fill=MUTED)
            break
        color = ACCENT if line.startswith("#") else (FG if line.strip() else MUTED)
        d.text((half + pad, y), line, font=font(18), fill=color)
        y += 25
    out = DOCS / "guide-and-skill.png"
    img.save(out, optimize=True)
    return out


def export_sample(session: Path) -> list[Path]:
    """docs/demo/sample/: the exported guide + draft skill, browsable on GitHub."""
    keep = REFINED.read_bytes() if REFINED.exists() else None
    if SAMPLE.exists():
        shutil.rmtree(SAMPLE)
    res = run_export(
        session, "both", SAMPLE, SkillOptions(out_dir=SAMPLE / "skill", name=SKILL_NAME)
    )
    assert res.ok, res.skill
    if keep is not None:
        REFINED.write_bytes(keep)
    return [SAMPLE / "guide" / "guide.md", SAMPLE / "skill" / SKILL_NAME / "SKILL.md"]


def chromium_path() -> str | None:
    env = os.environ.get("STEPCAP_CHROMIUM")
    if env:
        return env
    found = sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux*/chrome"))
    return found[-1] if found else None


def browser_shots(session: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    from stepcap.edit.server import create_server

    written = []
    srv = create_server(session, "127.0.0.1", 0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with sync_playwright() as p:
            exe = chromium_path()
            browser = p.chromium.launch(executable_path=exe) if exe else p.chromium.launch()
            for scheme, name in (("light", "guide-html.png"), ("dark", "guide-html-dark.png")):
                page = browser.new_page(
                    viewport={"width": 1280, "height": 860},
                    color_scheme=scheme,
                    device_scale_factor=1,
                )
                page.goto(f"{base}/guide.html")
                page.wait_for_load_state("networkidle")
                page.screenshot(path=str(DOCS / name))
                written.append(DOCS / name)
                page.close()
            page = browser.new_page(viewport={"width": 900, "height": 1000}, color_scheme="light")
            page.goto(f"{base}/checklist.html")
            page.wait_for_load_state("networkidle")
            page.screenshot(path=str(DOCS / "checklist.png"))
            written.append(DOCS / "checklist.png")
            page.close()
            page = browser.new_page(
                viewport={"width": 1280, "height": 860}, color_scheme="light", bypass_csp=True
            )
            page.goto(base + "/")
            page.wait_for_selector(".step img")
            page.wait_for_load_state("networkidle")
            page.wait_for_function(
                "() => [...document.images].every(i => i.complete && i.naturalWidth)"
            )
            page.locator(".step").nth(0).locator(".title").fill("Open the New project dialog")
            page.locator(".step").nth(0).locator(".desc").fill("Top right of the Projects page.")
            page.locator(".step").nth(0).locator("button", has_text="Blur area").click()
            page.evaluate("() => document.activeElement && document.activeElement.blur()")
            page.evaluate("() => window.scrollTo(0, 0)")
            page.mouse.move(0, 0)
            page.screenshot(path=str(DOCS / "edit-ui.png"), animations="disabled")
            written.append(DOCS / "edit-ui.png")
            browser.close()
    finally:
        srv.shutdown()
        srv.server_close()
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--browser",
        action="store_true",
        help="also take guide.html / edit UI screenshots with Playwright",
    )
    args = ap.parse_args()

    if OUT.exists():
        shutil.rmtree(OUT)  # demos/out is this script's scratch directory
    OUT.mkdir(parents=True)
    DOCS.mkdir(parents=True, exist_ok=True)
    session = OUT / "demo"
    spec = make_events()
    spec["accessibility"] = True  # element names + frames, as Windows UIA / macOS AX report them
    simulate(spec, session)
    meta = read_json(session / SESSION_FILE)
    meta["started"] = FIXED_START
    write_json(session / SESSION_FILE, meta)
    run_build(session, BuildOptions())
    doc = read_json(session / "steps.json")

    written = [make_gif(session, doc), guide_and_skill(session, doc)]
    for n, name in ((9, "step-drag.png"), (2, "step-click.png")):
        Image.open(session / doc["steps"][n - 1]["rendered"]).save(DOCS / name, optimize=True)
        written.append(DOCS / name)
    zoom_dir = OUT / "zoom"
    shutil.copytree(session, zoom_dir, ignore=shutil.ignore_patterns("images", "guide.*"))
    run_build(zoom_dir, BuildOptions(zoom=640, formats=("md",)))
    zdoc = read_json(zoom_dir / "steps.json")
    Image.open(zoom_dir / zdoc["steps"][4]["rendered"]).save(DOCS / "step-zoom.png", optimize=True)
    written.append(DOCS / "step-zoom.png")
    spot_dir = OUT / "spotlight"
    shutil.copytree(session, spot_dir, ignore=shutil.ignore_patterns("images", "guide.*"))
    run_build(spot_dir, BuildOptions(zoom=800, spotlight=True, formats=("md",)))
    sdoc = read_json(spot_dir / "steps.json")
    Image.open(spot_dir / sdoc["steps"][3]["rendered"]).save(
        DOCS / "step-spotlight.png", optimize=True
    )
    written.append(DOCS / "step-spotlight.png")

    written += export_sample(session)
    if args.browser:
        written += browser_shots(session)
    for p in written:
        print(f"wrote {p.relative_to(ROOT)} ({p.stat().st_size // 1024} KB)")
    if not args.browser:
        print("skipped browser screenshots (run with --browser; needs `pip install playwright`)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
