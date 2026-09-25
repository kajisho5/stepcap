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


def test_mask_rects_paints_the_bar_out_of_a_retina_shot():
    from PIL import Image

    from stepcap.capture.events import Monitor
    from stepcap.capture.screenshot import mask_rects

    img = Image.new("RGB", (400, 200), "white")  # 2x pixels for a 200x100 pt monitor
    for x in range(200, 300):  # the bar: grey with dark "text" inside its rectangle
        for y in range(20, 50):
            img.putpixel((x, y), (0, 0, 0) if y == 30 else (90, 90, 90))
    mon = Monitor(2, 100, 0, 200, 100)
    out = mask_rects(img, mon, [(200.0, 10.0, 50.0, 15.0), (-500.0, 0.0, 50.0, 50.0)])
    inside = {out.getpixel((x, y)) for x in range(200, 300) for y in range(20, 50)}
    assert inside == {(255, 255, 255)}  # the colour around it: the bar is gone
    assert out.getpixel((199, 30)) == (255, 255, 255) and out.getpixel((300, 30)) == (255, 255, 255)
    whole = Image.new("RGB", (10, 10), (90, 90, 90))  # nothing around it: its own average
    assert mask_rects(whole, Monitor(1, 0, 0, 10, 10), [(0, 0, 10, 10)]).getpixel((5, 5)) == (
        90,
        90,
        90,
    )
    assert mask_rects(img, mon, []) is img


def test_undo_marks_then_removes_the_newest_step(tmp_path):
    import json

    from stepcap.session import EVENTS_FILE, EventWriter, load_session

    rec = make(tmp_path)
    rec.writer = EventWriter(tmp_path / EVENTS_FILE)
    (tmp_path / "raw").mkdir()
    for sid in (1, 2, 3):
        shot = f"raw/{sid:04d}.png"
        (tmp_path / shot).write_bytes(b"png")
        rec.writer.write(
            {
                "id": sid,
                "kind": "click",
                "ts": sid,
                "screenshot": shot,
                "button": "left",
                "click_type": "single",
            }
        )
        rec.counts["click"] = rec.counts.get("click", 0) + 1
        rec.step_log.append((sid, "click", shot))
    rec.writer.write({"seq": 4, "kind": "url", "ts": 3.5, "url": "https://example.com"})
    rec._undo_last()
    rec._undo_last()
    assert rec.counts == {"click": 1} and [s for s, _ in rec.undone] == [3, 2]

    # before the end (e.g. after a crash) the markers already hide the steps
    _, events = load_session(tmp_path)
    assert [ev.get("id") for ev in events if "id" in ev] == [1]

    rec.writer.close()
    rec._drop_undone()
    lines = [json.loads(line) for line in (tmp_path / EVENTS_FILE).read_text().splitlines()]
    assert [ev.get("id") or ev["kind"] for ev in lines] == [1, "url"]
    assert sorted(p.name for p in (tmp_path / "raw").iterdir()) == ["0001.png"]

    rec.step_log.clear()
    rec._undo_last()  # nothing left to undo: no error, no marker
    assert rec.counts == {"click": 1}
