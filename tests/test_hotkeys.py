import pytest

from stepcap.hotkeys import HotkeyError, check_distinct, parse_hotkey


def test_parse_and_match():
    hk = parse_hotkey("F9")
    assert hk.key == "f9" and hk.modifiers == frozenset()
    assert hk.matches("f9", set()) and not hk.matches("f9", {"ctrl"})
    combo = parse_hotkey("Ctrl+Shift+S")
    assert combo.matches("s", {"ctrl", "shift"})
    assert parse_hotkey("<cmd>+escape").key == "esc"
    assert parse_hotkey("option+F8").modifiers == frozenset({"alt"})
    assert str(parse_hotkey("ctrl+f9")) == "ctrl+F9"


@pytest.mark.parametrize("bad", ["", "ctrl+", "ctrl", "hyper+a", "ctrl+banana"])
def test_invalid(bad):
    with pytest.raises(HotkeyError):
        parse_hotkey(bad)


def test_distinct():
    check_distinct(parse_hotkey("F9"), parse_hotkey("F8"), parse_hotkey("F7"))
    with pytest.raises(HotkeyError):
        check_distinct(parse_hotkey("F9"), parse_hotkey("f9"), parse_hotkey("F7"))
