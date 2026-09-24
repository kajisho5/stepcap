from PIL import Image, ImageDraw

from stepcap.build.detect import detect_box

W, H = 1440, 900


def page(color="white"):
    return Image.new("RGB", (W, H), color)


def test_filled_button_with_label():
    img = page()
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((600, 400, 780, 444), 8, fill="#3355ff")
    d.text((640, 412), "Create project", fill="white")
    assert detect_box(img, 690, 421) == [600, 400, 181, 45]


def test_white_button_with_thin_antialiased_border_on_white():
    big = Image.new("RGB", (W * 4, H * 4), "white")
    ImageDraw.Draw(big).rounded_rectangle((2400, 1600, 2700, 1740), 24, outline="#e1e4ea", width=4)
    img = big.resize((W, H), Image.Resampling.LANCZOS)  # 1 px anti-aliased border
    box = detect_box(img, 660, 417)
    assert box is not None
    x, y, w, h = box
    assert 600 <= x <= 603 and 400 <= y <= 403 and 70 <= w <= 76 and 30 <= h <= 36


def test_wide_input_field():
    img = page()
    ImageDraw.Draw(img).rounded_rectangle((200, 300, 1100, 348), 8, outline="#d7dbe2", width=2)
    box = detect_box(img, 650, 324)
    assert box is not None and box[2] > 880


def test_checkbox():
    img = page()
    ImageDraw.Draw(img).rounded_rectangle((500, 500, 524, 524), 5, outline="#6a7280", width=2)
    assert detect_box(img, 512, 512) == [502, 502, 21, 21]


def test_open_page_background_is_rejected():
    assert detect_box(page(), 700, 450) is None


def test_text_on_page_is_rejected_even_inside_a_letter_hole():
    img = page()
    d = ImageDraw.Draw(img)
    d.ellipse((600, 400, 640, 450), outline="black", width=6)  # a big letter "o"
    d.rectangle((650, 400, 656, 450), fill="black")
    assert detect_box(img, 620, 425) is None  # inside the hole
    assert detect_box(img, 653, 425) is None  # on the stroke


def test_large_panel_is_rejected():
    img = page("#f1f3f6")
    ImageDraw.Draw(img).rectangle((100, 100, 1300, 800), fill="white", outline="#d7dbe2")
    assert detect_box(img, 700, 450) is None


def test_click_outside_image():
    assert detect_box(page(), -1, 5) is None
    assert detect_box(page(), W, 5) is None
