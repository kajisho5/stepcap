from PIL import Image, ImageDraw

from stepcap.build.dedupe import DEFAULT_THRESHOLD, group_consecutive, similarity


def screen(color="white", size=(1440, 900)):
    img = Image.new("RGB", size, color)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, size[0], 40), fill="#dddddd")
    d.rectangle((300, 140, 700, 700), fill="#f1f3f6")
    return img


def test_identical_is_1():
    assert similarity(screen(), screen()) == 1.0


def test_small_change_is_same_screen():
    a, b = screen(), screen()
    ImageDraw.Draw(b).text((320, 160), "typed text", fill="black")
    assert similarity(a, b) > DEFAULT_THRESHOLD


def test_white_menu_over_light_ui_is_a_different_screen():
    a, b = screen(), screen()
    ImageDraw.Draw(b).rectangle((470, 250, 680, 400), fill="white", outline="#d7dbe2")
    assert similarity(a, b) < DEFAULT_THRESHOLD


def test_different_size_is_different():
    assert similarity(screen(size=(100, 100)), screen(size=(200, 100))) == 0.0


def test_group_consecutive_compares_with_run_base():
    imgs = {"1": screen(), "2": screen(), "3": screen("black"), "4": screen(), "5": screen()}
    ImageDraw.Draw(imgs["2"]).text((320, 160), "x", fill="black")
    mapping = group_consecutive(["1", "2", None, "3", "4", "5"], imgs.__getitem__)
    assert mapping == {"1": "1", "2": "1", "3": "3", "4": "4", "5": "4"}
