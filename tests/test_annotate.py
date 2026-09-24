import pytest
from PIL import Image

from stepcap.build import annotate


def blank(w=1440, h=900):
    return Image.new("RGB", (w, h), "white")


def is_accent(px, tol=40):
    return all(abs(a - b) <= tol for a, b in zip(px[:3], annotate.ACCENT, strict=True))


def accent_pixels(img, box):
    raw = img.crop(box).convert("RGB").tobytes()
    return sum(1 for i in range(0, len(raw), 3) if is_accent(raw[i : i + 3]))


def test_ring_and_badge_are_drawn_at_the_click():
    step = {"kind": "click", "point": {"x": 400, "y": 300, "img_x": 400, "img_y": 300}}
    out = annotate.annotate(blank(), step, 7)
    assert out.size == (1440, 900) and out.mode == "RGB"
    st = annotate.MarkerStyle.for_image(1440, 900)
    r = st.radius
    # ring: accent pixels on the circle, none far away
    assert accent_pixels(out, (400 - r - 6, 300 - 6, 400 - r + 6, 300 + 6)) > 5
    assert accent_pixels(out, (0, 600, 300, 900)) == 0
    # badge: up and right of the ring
    bx, by = annotate._badge_center(400, 300, st, 1440, 900, True)
    assert bx > 400 and by < 300
    assert accent_pixels(out, (bx - st.badge, by - st.badge, bx + st.badge, by + st.badge)) > 50


def test_badge_is_clamped_inside_the_image_at_the_edge():
    st = annotate.MarkerStyle.for_image(1440, 900)
    bx, by = annotate._badge_center(1439, 0, st, 1440, 900, True)
    assert st.badge <= bx <= 1440 - st.badge and st.badge <= by <= 900 - st.badge
    out = annotate.annotate(
        blank(), {"kind": "click", "point": {"x": 0, "y": 0, "img_x": 1439, "img_y": 0}}, 1
    )
    assert out.size == (1440, 900)


@pytest.mark.parametrize("kind", ["drag", "scroll", "key", "manual", "type"])
def test_all_kinds_render(kind):
    step = {
        "kind": kind,
        "point": {"img_x": 500, "img_y": 400},
        "direction": "down",
        "keys": "ctrl+s",
        "from": {"img_x": 500, "img_y": 400},
        "to": {"img_x": 900, "img_y": 450},
    }
    out = annotate.annotate(blank(), step, 12)
    assert out.size == (1440, 900)
    assert accent_pixels(out, (0, 0, 1440, 900)) > 50


def test_zoom_box_centred_and_clamped():
    step = {"point": {"img_x": 700, "img_y": 450}}
    assert annotate.zoom_box(step, (1440, 900), 800) == (300, 200, 1100, 700)
    step = {"point": {"img_x": 5, "img_y": 890}}
    assert annotate.zoom_box(step, (1440, 900), 800) == (0, 400, 800, 900)


def test_render_zoom_returns_thumbnail_and_width_limit():
    step = {"kind": "click", "point": {"img_x": 700, "img_y": 450}}
    main, thumb = annotate.render(blank(2880, 1800), step, 1, width=1600, zoom=800)
    assert main.size == (800, 500)
    assert thumb is not None and thumb.width == annotate.THUMB_WIDTH
    main, thumb = annotate.render(blank(2880, 1800), step, 1, width=1600)
    assert main.size == (1600, 1000) and thumb is None


@pytest.mark.parametrize(
    ("fmt", "magic"), [("webp", b"RIFF"), ("jpeg", b"\xff\xd8"), ("png", b"\x89PNG")]
)
def test_encode(fmt, magic):
    assert annotate.encode(blank(64, 64), fmt, 80).startswith(magic)
