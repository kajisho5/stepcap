"""Recorder logic that does not need OS hooks (the hooks themselves are not unit tested)."""

from types import SimpleNamespace

from stepcap.capture.recorder import Recorder, RecordOptions, normalise_key


def key(name=None, char=None, vk=None):
    return SimpleNamespace(name=name, char=char, vk=vk)


def test_normalise_key():
    assert normalise_key(key(name="ctrl_l")) == "ctrl"
    assert normalise_key(key(name="alt_gr")) == "alt"
    assert normalise_key(key(name="f9")) == "f9"
    assert normalise_key(key(char="A")) == "A"
    assert normalise_key(key(char="\x13")) == "s"  # Ctrl+S on Windows
    assert normalise_key(key(vk=65)) == "a"
    assert normalise_key(key(vk=49)) == "1"
    assert normalise_key(key()) is None


def make(tmp_path):
    return Recorder(RecordOptions(out_dir=tmp_path), tmp_path)


def drain(rec):
    items = []
    while not rec.raw_q.empty():
        items.append(rec.raw_q.get())
    return items


def test_hotkeys_are_consumed(tmp_path):
    rec = make(tmp_path)
    rec.on_press(key(char="a"))
    rec.on_press(key(name="f7"))
    rec.on_press(key(name="f9"))
    items = drain(rec)
    assert [i[0] for i in items] == ["key", "manual", "stop"]
    assert rec.stopped.is_set()
    rec.on_click(1, 2, SimpleNamespace(name="left"), True)  # ignored after stop
    assert drain(rec) == []


def test_pause_drops_input_but_keeps_hotkeys(tmp_path, capsys):
    rec = make(tmp_path)
    rec.on_press(key(name="f8"))
    assert rec.paused.is_set()
    rec.on_click(1, 2, SimpleNamespace(name="left"), True)
    rec.on_scroll(1, 2, 0, -1)
    rec.on_press(key(char="x"))
    assert [i[0] for i in drain(rec)] == ["flush"]
    rec.on_release(key(name="f8"))
    rec.on_press(key(name="f8"))
    assert not rec.paused.is_set()
    rec.on_click(1, 2, SimpleNamespace(name="left"), True)
    assert [i[0] for i in drain(rec)] == ["mouse"]


def test_autorepeat_of_special_keys_is_ignored(tmp_path):
    rec = make(tmp_path)
    rec.on_press(key(name="enter"))
    rec.on_press(key(name="enter"))
    rec.on_release(key(name="enter"))
    rec.on_press(key(char="a"))
    rec.on_press(key(char="a"))
    presses = [i for i in drain(rec) if i[0] == "key" and i[3]]
    assert [p[2] for p in presses] == ["enter", "a", "a"]


def test_custom_hotkey_with_modifier(tmp_path):
    from stepcap.hotkeys import parse_hotkey

    rec = Recorder(
        RecordOptions(out_dir=tmp_path, hotkey_stop=parse_hotkey("ctrl+alt+q")), tmp_path
    )
    rec.on_press(key(name="f9"))
    assert not rec.stopped.is_set()
    rec.on_press(key(name="ctrl_l"))
    rec.on_press(key(name="alt_l"))
    rec.on_press(key(char="q"))
    assert rec.stopped.is_set()


def test_unknown_mouse_buttons_are_ignored(tmp_path):
    rec = make(tmp_path)
    rec.on_click(1, 2, SimpleNamespace(name="x1"), True)
    assert drain(rec) == []
