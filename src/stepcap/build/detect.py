"""Find the bounds of the UI element under a click, from the screenshot alone.

Heuristic, OS independent, no extra dependencies: flood-fill the element's
surface colour from the click point inside a search window and take the
bounding box of the filled area. Buttons, input fields, checkboxes, list rows
and cards have a uniform fill surrounded by a border or a different colour,
so the fill stops at their edge.

The result is only returned when it looks like a control; otherwise ``None``
and the caller falls back to the ring marker. Rejected when the fill:
- leaks to the edge of the search window (no enclosing edge found),
- is too small (a text glyph) or too large (the page background),
- covers too little of its own bounding box (not a rectangle-ish shape).
"""

from __future__ import annotations

from collections import Counter

from PIL import Image, ImageChops, ImageDraw

# Search window around the click, as a multiple of the image's short side.
WINDOW_W = 1.3
WINDOW_H = 0.16
COLOR_TOLERANCE = 18  # Pillow floodfill thresh: summed |dR|+|dG|+|dB| (low: 1px AA borders)
MIN_SIDE = 0.012  # of the short side (~13 px on 1080p)
MAX_AREA = 0.06  # of the image area
MIN_FILL_RATIO = 0.45  # filled pixels / box, label glyphs excluded
MIN_SOLIDITY = 0.88  # shape with holes filled / box: rectangles ~0.95, round glyph holes ~0.78
_SENTINEL = (255, 0, 254)


def _seeds(win: Image.Image, cx: int, cy: int) -> list[tuple[int, int]]:
    """Points of the dominant colour around the click, nearest first.

    The click often lands on a label glyph, so the fill starts from the
    surrounding surface colour instead of the exact pixel under the cursor.
    """
    px = win.load()
    r = 4
    near = [
        (x, y)
        for y in range(max(0, cy - r), min(win.height, cy + r + 1))
        for x in range(max(0, cx - r), min(win.width, cx + r + 1))
    ]
    common = Counter(px[x, y] for x, y in near).most_common(1)[0][0]
    pts = [p for p in near if px[p[0], p[1]] == common]
    return sorted(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)


def _solidity(mask: Image.Image) -> float:
    """Share of the bounding box covered by the region once its holes are filled.

    Holes (label text inside a button) do not count against the shape, so a
    button scores ~1.0 while the round inside of a letter "o" scores ~0.78.
    """
    padded = Image.new("L", (mask.width + 2, mask.height + 2), 0)
    padded.paste(mask, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128)  # everything outside the shape
    outside = padded.histogram()[128] - (2 * padded.width + 2 * padded.height - 4)
    return 1.0 - outside / (mask.width * mask.height)


def _fill(win: Image.Image, seed: tuple[int, int]) -> Image.Image:
    filled = win.copy()
    ImageDraw.floodfill(filled, seed, _SENTINEL, thresh=COLOR_TOLERANCE)
    return ImageChops.difference(filled, win).convert("L").point(lambda v: 255 if v else 0)


def detect_box(img: Image.Image, x: int, y: int) -> list[int] | None:
    """Return ``[left, top, width, height]`` in image pixels, or ``None``."""
    w, h = img.size
    if not (0 <= x < w and 0 <= y < h):
        return None
    short = min(w, h)
    ww, wh = round(short * WINDOW_W), round(short * WINDOW_H)
    left, top = max(0, x - ww // 2), max(0, y - wh // 2)
    right, bottom = min(w, x + ww // 2), min(h, y + wh // 2)
    win = img.crop((left, top, right, bottom)).convert("RGB")
    cx, cy = x - left, y - top
    seeds = _seeds(win, cx, cy)
    if not seeds or win.getpixel(seeds[0]) == _SENTINEL:
        return None

    def leaks(bbox: tuple[int, int, int, int]) -> bool:
        x0, y0, x1, y1 = bbox
        return (
            (x0 == 0 and left > 0)
            or (y0 == 0 and top > 0)
            or (x1 == win.width and right < w)
            or (y1 == win.height and bottom < h)
        )

    # Fill from the nearest seed. Seeds of the same colour that ended up outside
    # that region belong to another surface: typically the click hit a letter and
    # the first seed sat inside a glyph (the hole of an "o"). Fill those too; if
    # any region leaks into open space, the click was on text over a page
    # background, not on a control, so give up.
    regions = []
    covered = Image.new("L", win.size, 0)
    for seed in seeds:
        if covered.getpixel(seed):
            continue
        mask = _fill(win, seed)
        covered.paste(255, mask=mask)
        bbox = mask.getbbox()
        if bbox is None:
            continue
        if leaks(bbox):
            return None
        regions.append((mask, bbox))
    if not regions:
        return None
    mask, (x0, y0, x1, y1) = max(regions, key=lambda r: (r[1][2] - r[1][0]) * (r[1][3] - r[1][1]))
    bw, bh = x1 - x0, y1 - y0
    if min(bw, bh) < MIN_SIDE * short or bw * bh > MAX_AREA * w * h:
        return None
    if mask.histogram()[255] / (bw * bh) < MIN_FILL_RATIO:
        return None
    if _solidity(mask.crop((x0, y0, x1, y1))) < MIN_SOLIDITY:
        return None
    if not (x0 <= cx < x1 and y0 <= cy < y1):
        return None
    return [left + x0, top + y0, bw, bh]
