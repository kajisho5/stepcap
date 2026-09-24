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


def test_box_marker_frames_the_element_and_ring_mode_ignores_it():
    step = {"kind": "click", "point": {"img_x": 700, "img_y": 420}, "box": [600, 400, 200, 44]}
    boxed = annotate.annotate(blank(), step, 3)
    st = annotate.MarkerStyle.for_image(1440, 900)
    # frame on the left edge of the box, no ring around the click point
    assert accent_pixels(boxed, (590, 405, 600, 440)) > 10
    assert accent_pixels(boxed, (700 - st.radius - 4, 416, 700 - st.radius + 4, 424)) == 0
    ringed = annotate.annotate(blank(), step, 3, marker="ring")
    assert accent_pixels(ringed, (590, 405, 600, 440)) == 0
    assert accent_pixels(ringed, (700 - st.radius - 6, 414, 700 - st.radius + 6, 426)) > 5


def test_box_only_for_click_and_type_steps():
    assert annotate.step_box({"kind": "click", "box": [1, 2, 3, 4]}) == [1, 2, 3, 4]
    assert annotate.step_box({"kind": "type", "box": [1, 2, 3, 4]}) == [1, 2, 3, 4]
    assert annotate.step_box({"kind": "scroll", "box": [1, 2, 3, 4]}) is None
    assert annotate.step_box({"kind": "click", "box": None}) is None
    assert annotate.step_box({"kind": "click", "box": [1, 2, 3, 4]}, "ring") is None


def test_small_box_badge_sits_outside():
    step = {"kind": "click", "point": {"img_x": 512, "img_y": 512}, "box": [502, 502, 21, 21]}
    out = annotate.annotate(blank(), step, 4)
    # the checkbox itself stays visible (not covered by the badge)
    assert accent_pixels(out, (506, 506, 519, 519)) == 0


def test_zoom_centres_on_box():
    step = {"kind": "click", "point": {"img_x": 10, "img_y": 10}, "box": [900, 600, 100, 40]}
    left, top, right, bottom = annotate.zoom_box(step, (1440, 900), 400)
    assert left <= 900 and right >= 1000 and top <= 600 and bottom >= 640


def luminance(img, box):
    raw = img.crop(box).convert("L").tobytes()
    return sum(raw) / len(raw)


def test_spotlight_dims_outside_the_target_only():
    step = {"kind": "click", "point": {"img_x": 700, "img_y": 420}, "box": [600, 400, 200, 44]}
    plain = annotate.annotate(blank(), step, 1)
    lit = annotate.annotate(blank(), step, 1, spot=True)
    assert luminance(lit, (0, 700, 300, 900)) < luminance(plain, (0, 700, 300, 900)) - 40
    assert luminance(lit, (640, 410, 760, 434)) > 250  # inside the frame stays bright
    ring_step = {"kind": "click", "point": {"img_x": 700, "img_y": 420}}
    lit_ring = annotate.annotate(blank(), ring_step, 1, spot=True)
    assert luminance(lit_ring, (708, 416, 713, 424)) > 240  # inside the ring, off the dot
    assert luminance(lit_ring, (0, 0, 200, 200)) < 200


def test_auto_arrow_only_for_small_targets():
    small = {"kind": "click", "point": {"img_x": 512, "img_y": 512}, "box": [502, 502, 21, 21]}
    big = {"kind": "click", "point": {"img_x": 700, "img_y": 420}, "box": [600, 400, 200, 44]}
    st = annotate.MarkerStyle.for_image(1440, 900)
    rect = annotate.box_rect(small["box"], st, 1440, 900)
    tail, head = annotate.auto_arrow(rect, st, 1440, 900)
    # points at the target from the side facing the image centre (up and right here)
    assert tail[0] > head[0] and tail[1] < head[1]
    with_arrow = annotate.annotate(blank(), small, 1)
    without = annotate.annotate(blank(), small, 1, auto_arrows=False)
    mid = ((tail[0] + head[0]) // 2, (tail[1] + head[1]) // 2)
    probe = (mid[0] - 4, mid[1] - 4, mid[0] + 4, mid[1] + 4)
    assert accent_pixels(with_arrow, probe) > 5 and accent_pixels(without, probe) == 0
    big_out = annotate.annotate(blank(), big, 1)
    assert accent_pixels(big_out, (820, 460, 900, 520)) == 0  # no arrow near a big button


def test_hand_drawn_arrows_are_always_drawn():
    step = {"kind": "manual", "arrows": [[100, 100, 400, 300]]}
    out = annotate.annotate(blank(), step, 1)
    assert accent_pixels(out, (240, 190, 260, 210)) > 5
    assert annotate.annotate(blank(), {"kind": "manual", "arrows": [[1, 2]]}, 1).size == (
        1440,
        900,
    )
