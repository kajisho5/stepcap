import pytest

from stepcap.build import naming


def ev(**kw):
    base = {"kind": "click", "click_type": "single", "window_title": "Settings", "app_name": "x"}
    base.update(kw)
    return base


@pytest.mark.parametrize(
    ("event", "en", "ja"),
    [
        (ev(), 'Click in "Settings"', "「Settings」でクリック"),
        (ev(click_type="double"), 'Double-click in "Settings"', "「Settings」でダブルクリック"),
        (ev(click_type="right"), 'Right-click in "Settings"', "「Settings」で右クリック"),
        (ev(kind="type"), 'Type into "Settings"', "「Settings」に入力"),
        (ev(kind="drag"), 'Drag in "Settings"', "「Settings」でドラッグ"),
        (
            ev(kind="scroll", direction="down"),
            'Scroll down in "Settings"',
            "「Settings」で下へスクロール",
        ),
        (
            ev(kind="key", keys="ctrl+shift+s"),
            'Press Ctrl+Shift+S in "Settings"',
            "「Settings」で Ctrl+Shift+S を押す",
        ),
        (
            ev(kind="manual", note="Check the total\nIt should be 42"),
            "Check the total",
            "Check the total",
        ),
    ],
)
def test_templates(event, en, ja):
    assert naming.auto_title(event, "en") == en
    assert naming.auto_title(event, "ja") == ja


def test_without_window_name():
    e = ev(window_title=None, app_name=None)
    assert naming.auto_title(e, "en") == "Click"
    assert naming.auto_title(e, "ja") == "クリック"
    assert naming.auto_title(ev(window_title="", app_name="Finder"), "en") == 'Click in "Finder"'


def test_long_title_is_truncated_and_whitespace_collapsed():
    t = naming.auto_title(ev(window_title="A  very\tlong " + "x" * 200), "en")
    assert t.startswith('Click in "A very long x')
    assert len(t) <= len('Click in ""') + naming.MAX_WINDOW_LABEL
    assert t.endswith('…"')


def test_descriptions():
    masked = ev(kind="type", chars=12, enter=True, masked=True)
    assert naming.auto_description(masked, "en") == (
        "Typed 12 characters and pressed Enter (content not recorded)."
    )
    assert "12 文字" in naming.auto_description(masked, "ja")
    shown = ev(kind="type", chars=5, enter=False, masked=False, text="hello")
    assert naming.auto_description(shown, "en") == 'Typed "hello".'
    note = ev(kind="manual", note="Title\nline 2\nline 3")
    assert naming.auto_description(note, "en") == "line 2\nline 3"
    assert naming.auto_description(ev(), "en") == ""


def test_heading_and_lang_check():
    assert naming.heading(3, "Do it", "en") == "Step 3 — Do it"
    assert naming.heading(3, "実行", "ja") == "手順 3 — 実行"
    with pytest.raises(ValueError):
        naming.check_lang("fr")
