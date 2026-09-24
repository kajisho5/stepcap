"""Draw click markers (double ring + numbered badge) on screenshots.

Markers are drawn on small supersampled patches and composited, which gives
anti-aliased shapes without upscaling the whole screenshot.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from stepcap.build.naming import format_keys

ACCENT = (255, 76, 32)  # vivid orange-red: readable on light and dark UIs
WHITE = (255, 255, 255)
DARK = (20, 20, 24)
SS = 4  # supersampling factor
THUMB_WIDTH = 480
ZOOM_ASPECT = 10 / 16  # height / width of the zoom crop
MARKERS = ("box", "ring")
BOX_KINDS = ("click", "type")  # steps whose target element can be framed
SPOTLIGHT_ALPHA = 110  # 0-255 darkness outside the target with --spotlight
SMALL_TARGET = 2.6  # frames whose longest side is below this many ring radii get an arrow

_font_cache: dict[int, Any] = {}


def font(size: int):
    size = max(8, int(size))
    if size not in _font_cache:
        try:
            _font_cache[size] = ImageFont.load_default(size=size)
        except TypeError:  # Pillow < 10.1
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]


@dataclass(frozen=True)
class MarkerStyle:
    radius: int
    line: int
    badge: int

    @classmethod
    def for_image(cls, w: int, h: int) -> MarkerStyle:
        r = min(64, max(16, round(min(w, h) * 0.032)))
        return cls(radius=r, line=max(3, round(r / 6)), badge=max(12, round(r * 0.62)))


def _patch(size: tuple[int, int]) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (size[0] * SS, size[1] * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img)


def _paste(base: Image.Image, patch: Image.Image, origin: tuple[int, int]) -> None:
    small = patch.resize((patch.width // SS, patch.height // SS), Image.Resampling.LANCZOS)
    base.alpha_composite(
        small,
        dest=(max(0, origin[0]), max(0, origin[1])),
        source=(max(0, -origin[0]), max(0, -origin[1])),
    )


def _ring(d: ImageDraw.ImageDraw, cx: float, cy: float, st: MarkerStyle, scale: float = 1.0):
    """Double ring: dark halo, accent ring, thin white inner line."""
    r = st.radius * scale * SS
    lw = st.line * scale * SS
    halo = lw * 0.5
    d.ellipse(
        (cx - r - halo, cy - r - halo, cx + r + halo, cy + r + halo),
        outline=(*DARK, 90),
        width=round(lw + 2 * halo),
    )
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*ACCENT, 255), width=round(lw))
    inner = r - lw * 1.6
    d.ellipse(
        (cx - inner, cy - inner, cx + inner, cy + inner),
        outline=(*WHITE, 235),
        width=max(1, round(lw * 0.45)),
    )
    dot = max(2 * SS, lw * 0.45)
    d.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=(*ACCENT, 255))


def _badge_center(x: int, y: int, st: MarkerStyle, w: int, h: int, has_point: bool):
    b = st.badge
    if not has_point:
        return b + 12, b + 12
    off = (st.radius + b * 0.55) / math.sqrt(2)
    bx, by = x + off, y - off
    bx = min(max(bx, b + 2), w - b - 2)
    by = min(max(by, b + 2), h - b - 2)
    return round(bx), round(by)


def draw_badge(img: Image.Image, cx: int, cy: int, n: int, st: MarkerStyle) -> None:
    b = st.badge
    label = str(n)
    extra = max(0, len(label) - 2) * b * 0.5
    size = (round(2 * b + 8 + extra), 2 * b + 8)
    patch, d = _patch(size)
    pad = 4 * SS
    d.rounded_rectangle(
        (pad, pad, patch.width - pad, patch.height - pad),
        radius=b * SS,
        fill=(*ACCENT, 255),
        outline=(*WHITE, 255),
        width=max(2, b // 6) * SS,
    )
    f = font(round(b * 1.15) * SS)
    d.text((patch.width / 2, patch.height / 2 + SS), label, font=f, fill=(*WHITE, 255), anchor="mm")
    _paste(img, patch, (cx - size[0] // 2, cy - size[1] // 2))


def draw_ring(img: Image.Image, x: int, y: int, st: MarkerStyle, scale: float = 1.0) -> None:
    r = math.ceil((st.radius + st.line * 2) * scale) + 4
    patch, d = _patch((2 * r, 2 * r))
    _ring(d, r * SS, r * SS, st, scale)
    _paste(img, patch, (x - r, y - r))


def box_rect(box: list[int], st: MarkerStyle, w: int, h: int) -> tuple[int, int, int, int]:
    """Outer rectangle of the highlight frame: the element box plus a small gap."""
    pad = st.line + 3
    x, y, bw, bh = box
    return max(0, x - pad), max(0, y - pad), min(w - 1, x + bw + pad), min(h - 1, y + bh + pad)


def draw_box(img: Image.Image, box: list[int], st: MarkerStyle) -> None:
    """Double frame around an element: dark halo, accent line, thin white inner line."""
    x0, y0, x1, y1 = box_rect(box, st, img.width, img.height)
    m = st.line * 2
    patch, d = _patch((x1 - x0 + 2 * m, y1 - y0 + 2 * m))
    lw = st.line * SS
    radius = min(st.radius * 0.35, (y1 - y0) / 2) * SS
    r = (m * SS, m * SS, (x1 - x0 + m) * SS, (y1 - y0 + m) * SS)
    halo = round(lw * 0.5)
    d.rounded_rectangle(
        (r[0] - halo, r[1] - halo, r[2] + halo, r[3] + halo),
        radius + halo,
        outline=(*DARK, 90),
        width=round(lw + 2 * halo),
    )
    d.rounded_rectangle(r, radius, outline=(*ACCENT, 255), width=round(lw))
    inset = round(lw * 1.1)
    d.rounded_rectangle(
        (r[0] + inset, r[1] + inset, r[2] - inset, r[3] - inset),
        max(0, radius - inset),
        outline=(*WHITE, 220),
        width=max(1, round(lw * 0.4)),
    )
    _paste(img, patch, (x0 - m, y0 - m))


def draw_arrow(
    img: Image.Image,
    p1: tuple[int, int],
    p2: tuple[int, int],
    st: MarkerStyle,
    start_gap: float = 0.0,
    end_gap: float = 0.0,
) -> None:
    (x1, y1), (x2, y2) = p1, p2
    length = math.hypot(x2 - x1, y2 - y1)
    if length < 1:
        return
    ux, uy = (x2 - x1) / length, (y2 - y1) / length
    sx, sy = x1 + ux * start_gap, y1 + uy * start_gap
    ex, ey = x2 - ux * end_gap, y2 - uy * end_gap
    margin = st.radius + 8
    left, top = round(min(sx, ex) - margin), round(min(sy, ey) - margin)
    right, bottom = round(max(sx, ex) + margin), round(max(sy, ey) + margin)
    patch, d = _patch((right - left, bottom - top))

    def P(px: float, py: float) -> tuple[float, float]:
        return ((px - left) * SS, (py - top) * SS)

    lw = st.line * SS
    head = st.radius * 0.75
    bx, by = ex - ux * head, ey - uy * head
    nx, ny = -uy, ux
    for color, width in (((*DARK, 90), lw * 2), ((*ACCENT, 255), lw)):
        d.line([P(sx, sy), P(bx, by)], fill=color, width=round(width))
    tri = [
        P(ex, ey),
        P(bx + nx * head * 0.6, by + ny * head * 0.6),
        P(bx - nx * head * 0.6, by - ny * head * 0.6),
    ]
    d.polygon(tri, fill=(*ACCENT, 255), outline=(*WHITE, 255))
    _paste(img, patch, (left, top))


def draw_pill(img: Image.Image, label: str, cx: int, cy: int, st: MarkerStyle) -> None:
    f = font(round(st.badge * 1.5) * SS)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = tmp.textbbox((0, 0), label, font=f)
    tw, th = (bbox[2] - bbox[0]) / SS, (bbox[3] - bbox[1]) / SS
    w, h = round(tw + st.badge * 1.6), round(th + st.badge * 1.1)
    cx = min(max(cx, w // 2 + 4), img.width - w // 2 - 4)
    cy = min(max(cy, h // 2 + 4), img.height - h // 2 - 4)
    patch, d = _patch((w, h))
    d.rounded_rectangle(
        (0, 0, patch.width - 1, patch.height - 1),
        radius=h * SS // 2,
        fill=(*DARK, 225),
        outline=(*ACCENT, 255),
        width=2 * SS,
    )
    d.text((patch.width / 2, patch.height / 2), label, font=f, fill=(*WHITE, 255), anchor="mm")
    _paste(img, patch, (cx - w // 2, cy - h // 2))


def _pt(p: dict[str, Any] | None) -> tuple[int, int] | None:
    if not p or "img_x" not in p:
        return None
    return int(p["img_x"]), int(p["img_y"])


def step_box(step: dict[str, Any], marker: str = "box") -> list[int] | None:
    """The element box to frame for this step, or None (ring / no marker)."""
    box = step.get("box")
    if marker != "box" or step.get("kind") not in BOX_KINDS or not box or len(box) != 4:
        return None
    return [int(v) for v in box]


def spotlight(img: Image.Image, rect: tuple[int, int, int, int], round_: bool = False) -> None:
    """Dim everything outside ``rect`` so the target stands out."""
    x0, y0, x1, y1 = rect
    hole = Image.new("L", (img.width * 2, img.height * 2), SPOTLIGHT_ALPHA)
    d = ImageDraw.Draw(hole)
    r = (x0 * 2, y0 * 2, x1 * 2, y1 * 2)
    if round_:
        d.ellipse(r, fill=0)
    else:
        d.rounded_rectangle(r, radius=12, fill=0)
    alpha = hole.resize(img.size, Image.Resampling.LANCZOS)
    shade = Image.new("RGBA", img.size, (*DARK, 0))
    shade.putalpha(alpha)
    img.alpha_composite(shade)


def _exit_point(rect, cx: float, cy: float, dx: float, dy: float) -> tuple[float, float]:
    """Where the ray from (cx, cy) along (dx, dy) leaves ``rect``."""
    x0, y0, x1, y1 = rect
    ts = []
    if dx:
        ts.append(((x1 if dx > 0 else x0) - cx) / dx)
    if dy:
        ts.append(((y1 if dy > 0 else y0) - cy) / dy)
    t = min(t for t in ts if t >= 0) if ts else 0
    return cx + dx * t, cy + dy * t


def auto_arrow(rect, st: MarkerStyle, w: int, h: int) -> tuple[tuple[int, int], tuple[int, int]]:
    """Arrow (tail, head) pointing at a small frame from the side facing the image centre."""
    x0, y0, x1, y1 = rect
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = w / 2 - cx, h / 2 - cy
    norm = math.hypot(dx, dy)
    dx, dy = (dx / norm, dy / norm) if norm > 1 else (-0.7071, 0.7071)
    # prefer a diagonal: it reads as "pointing at" and avoids covering labels on the row
    dx, dy = math.copysign(max(abs(dx), 0.5), dx), math.copysign(max(abs(dy), 0.5), dy)
    norm = math.hypot(dx, dy)
    dx, dy = dx / norm, dy / norm
    hx, hy = _exit_point(rect, cx, cy, dx, dy)
    gap = st.line * 2
    head = (hx + dx * gap, hy + dy * gap)
    length = st.radius * 3.2
    tail = (head[0] + dx * length, head[1] + dy * length)
    m = st.badge + 4
    tail = (min(max(tail[0], m), w - m), min(max(tail[1], m), h - m))
    return (round(tail[0]), round(tail[1])), (round(head[0]), round(head[1]))


def _manual_arrows(step: dict[str, Any]) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    out = []
    for a in step.get("arrows") or []:
        if isinstance(a, (list, tuple)) and len(a) == 4:
            x1, y1, x2, y2 = (int(v) for v in a)
            out.append(((x1, y1), (x2, y2)))
    return out


def annotate(
    src: Image.Image,
    step: dict[str, Any],
    n: int,
    marker: str = "box",
    spot: bool = False,
    auto_arrows: bool = True,
) -> Image.Image:
    """Return a new RGB image with the marker(s) and badge ``n`` for ``step``.

    ``marker="box"`` frames the clicked element when ``step["box"]`` is known
    (auto-detected or drawn in ``stepcap edit``) and falls back to the ring;
    ``marker="ring"`` always draws the ring. ``spot`` dims everything but the
    target. ``auto_arrows`` adds an arrow pointing at small frames (checkboxes,
    icons); arrows drawn in ``stepcap edit`` (``step["arrows"]``) are always drawn.
    """
    img = src.convert("RGBA")
    st = MarkerStyle.for_image(img.width, img.height)
    kind = step.get("kind")
    point = _pt(step.get("point"))
    box = step_box(step, marker)
    # keys and notes are not tied to a pointer position: no ring, badge in the corner
    has_point = point is not None and kind not in ("manual", "key")
    rect = box_rect(box, st, img.width, img.height) if (has_point and box) else None

    if spot and has_point and kind != "drag":
        if rect is not None:
            spotlight(img, rect)
        else:
            r = st.radius * 2.2
            spotlight(
                img,
                (
                    round(point[0] - r),
                    round(point[1] - r),
                    round(point[0] + r),
                    round(point[1] + r),
                ),
                round_=True,
            )

    arrow_tail = None
    if kind == "drag" and _pt(step.get("from")) and _pt(step.get("to")):
        p1, p2 = _pt(step["from"]), _pt(step["to"])
        draw_arrow(img, p1, p2, st, start_gap=st.radius, end_gap=st.radius * 0.55)
        draw_ring(img, *p1, st)
        draw_ring(img, *p2, st, scale=0.55)
        point = p1
    elif rect is not None:
        draw_box(img, box, st)
        small = max(rect[2] - rect[0], rect[3] - rect[1]) < SMALL_TARGET * st.radius
        if auto_arrows and small:
            arrow_tail, head = auto_arrow(rect, st, img.width, img.height)
            draw_arrow(img, arrow_tail, head, st)
    elif has_point:
        draw_ring(img, *point, st)
        if kind == "scroll":
            direction = step.get("direction", "down")
            vec = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}[direction]
            gap = st.radius + st.line * 2
            start = (point[0] + vec[0] * gap, point[1] + vec[1] * gap)
            end = (point[0] + vec[0] * gap * 3, point[1] + vec[1] * gap * 3)
            draw_arrow(img, start, end, st)
    for tail, head in _manual_arrows(step):
        draw_arrow(img, tail, head, st)
    if kind == "key" and step.get("keys"):
        draw_pill(img, format_keys(step["keys"]), img.width // 2, img.height - st.badge * 3, st)

    b = st.badge
    if arrow_tail is not None:
        # the number sits where the arrow starts, pointing at the target
        bx = round(min(max(arrow_tail[0], b + 2), img.width - b - 2))
        by = round(min(max(arrow_tail[1], b + 2), img.height - b - 2))
    elif rect is not None and kind != "drag":
        x0, y0, x1, y1 = rect
        # on the top-right corner; small targets get it outside so it does not cover them
        out = b * 0.9 if min(x1 - x0, y1 - y0) < 3 * b else 0
        bx = round(min(max(x1 + out, b + 2), img.width - b - 2))
        by = round(min(max(y0 - out, b + 2), img.height - b - 2))
    else:
        bx, by = _badge_center(*(point or (0, 0)), st, img.width, img.height, has_point)
    draw_badge(img, bx, by, n, st)
    return img.convert("RGB")


def zoom_box(step: dict[str, Any], size: tuple[int, int], zoom: int) -> tuple[int, int, int, int]:
    """Crop box of ``zoom`` px width (16:10) centred on the marker, clamped to the image."""
    w, h = size
    cw = min(zoom, w)
    ch = min(round(zoom * ZOOM_ASPECT), h)
    pts = [p for p in (_pt(step.get("point")), _pt(step.get("from")), _pt(step.get("to"))) if p]
    box = step_box(step)
    if box:
        pts = [(box[0], box[1]), (box[0] + box[2], box[1] + box[3])]
    if pts:
        cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
        cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
    else:
        cx, cy = w / 2, h / 2
    left = round(min(max(cx - cw / 2, 0), w - cw))
    top = round(min(max(cy - ch / 2, 0), h - ch))
    return left, top, left + cw, top + ch


def fit_width(img: Image.Image, max_width: int | None) -> Image.Image:
    if max_width and img.width > max_width:
        h = round(img.height * max_width / img.width)
        return img.resize((max_width, h), Image.Resampling.LANCZOS)
    return img


def render(
    src: Image.Image,
    step: dict[str, Any],
    n: int,
    width: int | None = None,
    zoom: int | None = None,
    marker: str = "box",
    spot: bool = False,
    auto_arrows: bool = True,
) -> tuple[Image.Image, Image.Image | None]:
    """Return (main image, optional full-screen thumbnail)."""
    full = annotate(src, step, n, marker, spot, auto_arrows)
    if zoom and zoom < full.width:
        crop = full.crop(zoom_box(step, full.size, zoom))
        return fit_width(crop, width), fit_width(full, THUMB_WIDTH)
    return fit_width(full, width), None


FORMATS = {
    "webp": ("WEBP", "image/webp"),
    "jpeg": ("JPEG", "image/jpeg"),
    "png": ("PNG", "image/png"),
}


def encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    buf = io.BytesIO()
    if fmt == "webp":
        img.save(buf, "WEBP", quality=quality, method=4)
    elif fmt == "jpeg":
        img.save(buf, "JPEG", quality=quality, optimize=True, subsampling=0)
    elif fmt == "png":
        img.save(buf, "PNG", optimize=False, compress_level=6)
    else:
        raise ValueError(f"unknown image format {fmt!r}")
    return buf.getvalue()


def extension(fmt: str) -> str:
    return {"webp": "webp", "jpeg": "jpg", "png": "png"}[fmt]
