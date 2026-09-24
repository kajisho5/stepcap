from stepcap.capture.events import Monitor, is_sensitive_title, pick_monitor


def test_single_click_waits_for_double_click_window(harness):
    h = harness()
    h.click(0.0, 100, 200)
    assert h.events == []  # still inside the double-click window
    h.proc.tick(0.05 + 0.2)
    assert len(h.events) == 1
    ev = h.events[0]
    assert ev["kind"] == "click" and ev["click_type"] == "single" and ev["button"] == "left"
    assert (ev["x"], ev["y"], ev["rel_x"], ev["rel_y"]) == (100, 200, 100, 200)
    assert ev["window_title"] == "Editor - Notes" and ev["app_name"] == "notes"
    assert ev["screenshot"] == "raw/0001.png"
    assert ev["monitor"] == {"index": 1, "left": 0, "top": 0, "width": 1920, "height": 1080}


def test_fast_second_click_becomes_double_click(harness):
    h = harness()
    h.click(0.0, 100, 200)
    h.click(0.05 + 0.1, 101, 201)  # 100 ms between release and next press
    evs = h.done()
    assert [e["click_type"] for e in evs] == ["double"]
    assert len(h.captures) == 1  # no second screenshot for the second click


def test_slow_second_click_is_two_clicks(harness):
    h = harness()
    h.click(0.0, 100, 200)
    h.click(0.05 + 0.3, 100, 200)
    assert [e["click_type"] for e in h.done()] == ["single", "single"]


def test_double_click_window_is_configurable(harness):
    h = harness(double_click_s=0.5)
    h.click(0.0, 100, 200)
    h.click(0.05 + 0.3, 100, 200)
    assert [e["click_type"] for e in h.done()] == ["double"]


def test_right_and_middle_click_emit_immediately(harness):
    h = harness()
    h.click(0.0, 10, 10, button="right")
    assert h.events[-1]["click_type"] == "right"
    h.click(1.0, 10, 10, button="middle")
    assert h.events[-1]["click_type"] == "middle"


def test_drag_over_threshold(harness):
    h = harness()
    h.proc.on_mouse(0.0, 100, 100, "left", True)
    h.proc.on_mouse(0.5, 400, 300, "left", False)
    (ev,) = h.done()
    assert ev["kind"] == "drag"
    assert (ev["from"]["x"], ev["from"]["y"]) == (100, 100)
    assert (ev["to"]["x"], ev["to"]["y"]) == (400, 300)


def test_small_move_is_still_a_click(harness):
    h = harness()
    h.proc.on_mouse(0.0, 100, 100, "left", True)
    h.proc.on_mouse(0.1, 105, 104, "left", False)
    assert [e["kind"] for e in h.done()] == ["click"]


def test_scroll_is_aggregated(harness):
    h = harness()
    for i in range(6):
        h.proc.on_scroll(i * 0.05, 500, 500, 0, -1)
    (ev,) = h.done()
    assert ev["kind"] == "scroll" and ev["direction"] == "down" and ev["amount"] == 6
    assert len(h.captures) == 1


def test_scroll_direction_change_or_pause_splits(harness):
    h = harness()
    h.proc.on_scroll(0.0, 1, 1, 0, -1)
    h.proc.on_scroll(0.1, 1, 1, 0, 1)  # direction change
    h.proc.on_scroll(5.0, 1, 1, 0, 1)  # long pause
    evs = h.done()
    assert [e["direction"] for e in evs] == ["down", "up", "up"]


def test_typing_is_masked_by_default(harness):
    h = harness()
    h.click(0.0, 300, 300)
    h.type(1.0, "secret words")
    h.proc.on_key(2.0, "enter")
    _click, typed = h.done()
    assert typed["kind"] == "type"
    assert typed["chars"] == 12 and typed["enter"] is True and typed["masked"] is True
    assert "text" not in typed
    assert "secret" not in repr(h.events)


def test_record_typing_stores_text_and_backspace(harness):
    h = harness(record_typing=True)
    h.type(0.0, "helo")
    h.proc.on_key(0.3, "backspace")
    h.type(0.4, "lo")
    (ev,) = h.done()
    assert ev["text"] == "hello" and ev["chars"] == 5 and ev["masked"] is False


def test_password_window_forces_mask_even_with_record_typing(harness):
    h = harness(record_typing=True)
    for title in ("Sign in - Bank", "パスワードの入力", "Bitwarden", "KeePassXC", "1Password 8"):
        h.window.title = title
        h.events.clear()
        h.type(0.0, "hunter2")
        h.proc.flush()
        (ev,) = h.events
        assert ev["masked"] is True and "text" not in ev, title


def test_sensitive_titles():
    assert is_sensitive_title("Enter your PASSWORD")
    assert is_sensitive_title("KeePass")
    assert not is_sensitive_title("Quarterly report.xlsx")
    assert not is_sensitive_title(None)


def test_tab_splits_typing_runs(harness):
    h = harness()
    h.type(0.0, "ab")
    h.proc.on_key(0.2, "tab")
    h.type(0.3, "cde")
    evs = h.done()
    assert [e["chars"] for e in evs] == [2, 3]


def test_modifier_combo_is_a_key_step_not_typing(harness):
    h = harness(record_typing=True)
    h.proc.on_key(0.0, "ctrl")
    h.proc.on_key(0.01, "s")
    h.proc.on_key(0.02, "ctrl", pressed=False)
    h.proc.on_key(0.1, "shift")
    h.proc.on_key(0.11, "A")  # shift alone is still typing
    h.proc.on_key(0.12, "shift", pressed=False)
    evs = h.done()
    assert evs[0]["kind"] == "key" and evs[0]["keys"] == "ctrl+s"
    assert evs[1]["kind"] == "type" and evs[1]["text"] == "A"


def test_enter_and_esc_outside_typing_are_steps_other_keys_ignored(harness):
    h = harness()
    for k in ("enter", "up", "f5", "esc", "page_down"):
        h.proc.on_key(0.0, k)
    assert [e.get("keys") for e in h.done()] == ["enter", "esc"]


def test_excluded_app_records_nothing(harness):
    h = harness(exclude_apps=("keepass",))
    h.window.app = "KeePassXC"
    h.click(0.0, 10, 10)
    h.type(1.0, "abc")
    h.proc.on_scroll(2.0, 10, 10, 0, -1)
    assert h.done() == []
    assert h.captures == []  # no screenshot either
    assert h.proc.excluded_count == 3
    h.window.app = "notes"
    h.click(5.0, 10, 10)
    assert len(h.done()) == 1


def test_exclude_matches_window_title_case_insensitive(harness):
    h = harness(exclude_apps=("Payroll",))
    h.window = type(h.window)("payroll - Chrome", "chrome")
    h.click(0.0, 1, 1)
    assert h.done() == []


def test_second_monitor_relative_coordinates_and_hidpi_scale(harness):
    mons = [Monitor(1, 0, 0, 1920, 1080), Monitor(2, 1920, -200, 1280, 800)]
    h = harness(monitors=mons)

    def capture(x, y, ts):
        m = pick_monitor(mons, x, y)
        from stepcap.capture.events import Shot

        return Shot(
            id="0001", path="raw/0001.png", monitor=m, width=m.width * 2, height=m.height * 2
        )  # retina: 2 image px per point

    h.proc.capture = capture
    h.click(0.0, 2000, 100)
    (ev,) = h.done()
    assert ev["monitor"]["index"] == 2
    assert (ev["rel_x"], ev["rel_y"]) == (80, 300)
    assert (ev["img_x"], ev["img_y"]) == (160, 600)
    assert ev["image_size"] == [2560, 1600]


def test_pick_monitor_falls_back_to_nearest():
    mons = [Monitor(1, 0, 0, 100, 100), Monitor(2, 100, 0, 100, 100)]
    assert pick_monitor(mons, 150, 50).index == 2
    assert pick_monitor(mons, 500, 50).index == 2
    assert pick_monitor(mons, -5, -5).index == 1


def test_manual_step_and_event_order(harness):
    h = harness()
    h.click(0.0, 5, 5)
    token = h.proc.manual_capture(1.0)
    h.proc.manual_commit(token, "  Check the result\nmore  ")
    evs = h.done()
    assert [e["kind"] for e in evs] == ["click", "manual"]
    assert evs[1]["note"] == "Check the result\nmore"
    assert [e["id"] for e in evs] == [1, 2]
