"""Screenshots of `stepcap app` for the README: docs/demo/app.png (en), app-ja.png (ja).

Drives the real window on an X display with real mouse clicks: Start, two clicks on
the desktop, Add note, Stop, "Add to Claude Code". Needs tkinter, pynput and a
display without a window manager (Xvfb); install stepcap[voice] too, or the voice
option is shown greyed out. The light theme is used (``STEPCAP_THEME=light``). E.g.

    Xvfb :99 -screen 0 1600x1000x24 &
    DISPLAY=:99 python demos/app_screenshots.py --lang en
    DISPLAY=:99 python demos/app_screenshots.py --lang ja

The skill is installed into a temporary home folder shown as /home/me.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageGrab

ROOT = Path(__file__).resolve().parents[1]
HOME = Path("/home/me")  # a short, neutral path in the finished view
NOTE = {"en": "Save the file first", "ja": "先にファイルを保存する"}
LABELS = {
    "en": (
        "1. Start",
        "2. Recording bar (always on top; its clicks are not steps and it is painted out "
        "of the screenshots; Undo forgets the last step)",
        "3. Done: add the skill to your agent (Claude Code, Codex, Gemini CLI, Cursor) "
        "or open the guide",
    ),
    "ja": (
        "1. 開始",
        "2. 記録バー（常に手前に表示。バーのクリックは手順にならず、画像からも消えます。"
        "取り消すで直前の手順を削除）",
        "3. 完了: スキルをエージェント（Claude Code・Codex など）に追加、または手順書を開く",
    ),
}
BUNDLED = str(ROOT / "src" / "stepcap" / "assets" / "fonts" / "NotoSansJP-Regular.otf")
FONTS = {  # label fonts, first one found wins (the window's own font first)
    "en": (BUNDLED, "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    "ja": (
        BUNDLED,
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
        "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    ),
}


def capture(lang: str, shots: Path) -> None:
    import tkinter as tk

    from pynput.mouse import Button, Controller

    from stepcap.gui import app as app_mod
    from stepcap.gui import controller as ctl
    from stepcap.gui.app import App

    ctl.open_path = lambda p: None
    app_mod.messagebox.askyesno = lambda *a, **kw: True
    ctl.default_root = lambda: Path("stepcap")
    t = ctl.TEXTS[lang]
    root = tk.Tk()
    app = App(root, lang)
    mouse = Controller()

    def on_tk(fn):
        box: dict = {}
        done = threading.Event()
        root.after(0, lambda: (box.setdefault("v", fn()), done.set()))
        done.wait(5)
        return box.get("v")

    def find(text):
        def walk(w):
            for c in w.winfo_children():
                if c.winfo_class() == "TButton" and c.cget("text") == text:
                    return c
                r = walk(c)
                if r is not None:
                    return r
            return None

        return on_tk(lambda: walk(root))

    def click(widget=None, x=None, y=None):
        if widget is not None:
            x, y = on_tk(
                lambda: (
                    widget.winfo_rootx() + widget.winfo_width() // 2,
                    widget.winfo_rooty() + widget.winfo_height() // 2,
                )
            )
        mouse.position = (x, y)
        time.sleep(0.15)
        mouse.click(Button.left)
        time.sleep(0.5)

    def until(cond, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            if on_tk(cond):
                return
            time.sleep(0.1)
        raise SystemExit("timeout")

    def shot(name):
        ImageGrab.grab(xdisplay=os.environ.get("DISPLAY")).save(shots / name)

    def drive():
        try:
            time.sleep(1.0)
            shot("1-home.png")
            click(find(t["start"]))
            until(lambda: bool(app.started))
            time.sleep(0.8)
            click(x=300, y=500)
            click(x=700, y=600)  # two steps on the desktop
            click(find(t["note"]))
            until(lambda: app.note_row is not None)
            kids = on_tk(lambda: app.note_row.winfo_children())
            entry = on_tk(lambda: next(c for c in kids if c.winfo_class() == "TEntry"))
            on_tk(lambda: entry.insert(0, NOTE[lang]))
            time.sleep(0.3)
            shot("2-note.png")
            click(find(t["ok"]))
            time.sleep(1.0)
            click(find(t["stop"]))
            until(lambda: app.rec is None)
            time.sleep(0.8)
            click(find(t["add_claude"]))
            end = time.time() + 1
            while time.time() < end and not on_tk(lambda: app.busy):
                time.sleep(0.05)
            until(lambda: not app.busy, 90)
            time.sleep(0.3)
            shot("3-done.png")
        finally:
            root.after(0, root.destroy)

    threading.Thread(target=drive, daemon=True).start()
    root.mainloop()


def compose(lang: str, shots: Path, out: Path) -> None:
    def crop(name):
        im = Image.open(shots / name).convert("RGB")
        return im.crop(im.point(lambda v: 255 if v > 8 else 0).convert("L").getbbox())

    ims = [crop("1-home.png"), crop("2-note.png"), crop("3-done.png")]
    found = [f for f in FONTS[lang] if Path(f).exists()]
    if not found:
        raise SystemExit(f"no font for {lang}: install one of {', '.join(FONTS[lang])}")
    font = ImageFont.truetype(found[0], 17)
    pad, gap, lab = 20, 22, 30
    text_w = max(font.getlength(text) for text in LABELS[lang])
    width = round(max(max(i.width for i in ims) + 4, text_w + 2)) + 2 * pad
    height = pad + sum(lab + i.height + 4 + gap for i in ims) + pad - gap
    page = Image.new("RGB", (width, height), (244, 245, 247))
    draw = ImageDraw.Draw(page)
    y = pad
    for text, im in zip(LABELS[lang], ims, strict=True):
        draw.text((pad + 2, y), text, fill=(40, 44, 52), font=font)
        y += lab
        frame = (pad, y, pad + im.width + 3, y + im.height + 3)
        draw.rectangle(frame, outline=(30, 30, 30), width=2)
        page.paste(im, (pad + 2, y + 2))
        y += im.height + 4 + gap
    page.save(out, optimize=True)
    print(out, page.size)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=("en", "ja"), default="en")
    ap.add_argument("-o", "--output", type=Path)
    args = ap.parse_args()
    out = args.output or ROOT / "docs" / "demo" / ("app.png" if args.lang == "en" else "app-ja.png")
    work = Path(tempfile.mkdtemp(prefix="stepcap-app-"))
    HOME.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(HOME)  # the recorder subprocess and the skill install use it
    os.environ.setdefault("STEPCAP_THEME", "light")
    os.chdir(work)
    try:
        capture(args.lang, work)
        compose(args.lang, work, out.resolve() if out.is_absolute() else ROOT / out)
    finally:
        os.chdir(ROOT)
        shutil.rmtree(work, ignore_errors=True)
        shutil.rmtree(HOME / ".claude", ignore_errors=True)


if __name__ == "__main__":
    main()
