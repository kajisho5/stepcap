import json

import pytest

from stepcap.session import SessionError, load_session
from stepcap.simulate import SimulationError, simulate


def test_session_layout(demo_session):
    meta, all_events = load_session(demo_session)
    assert meta["source"] == "simulate" and meta["format"] == 2
    # format 2: context events (app switches, ...) have no "id" and are not steps
    events = [e for e in all_events if "id" in e]
    context = [e for e in all_events if "id" not in e]
    assert meta["stats"]["events"] == len(events) == 12
    assert meta["stats"]["context_events"] == len(context) >= 1
    assert {e["kind"] for e in context} == {"app_switch"}
    assert (demo_session / "raw" / "0001.png").is_file()
    kinds = [e["kind"] for e in events]
    assert kinds == [
        "click",
        "click",
        "type",
        "click",
        "click",
        "click",
        "click",
        "key",
        "drag",
        "scroll",
        "key",
        "manual",
    ]
    clicks = [e["click_type"] for e in events if e["kind"] == "click"]
    assert clicks == ["single", "single", "single", "single", "double", "right"]
    for e in events:
        if e["screenshot"]:
            assert (demo_session / e["screenshot"]).is_file()


def test_typed_text_not_stored_by_default(demo_session):
    raw = (demo_session / "events.jsonl").read_text(encoding="utf-8")
    assert "Q3 launch" not in raw
    typed = [json.loads(line) for line in raw.splitlines() if '"type"' in line]
    assert typed[0]["chars"] == len("Q3 launch plan") and typed[0]["masked"] is True


def test_record_typing(tmp_path, spec):
    simulate(spec, tmp_path / "s", record_typing=True)
    assert '"text":"Q3 launch plan"' in (tmp_path / "s" / "events.jsonl").read_text("utf-8")


def test_exclude_app(tmp_path, spec):
    res = simulate(spec, tmp_path / "s", exclude_apps=("acme",))
    assert res["events"] == 1  # only the manual note (explicit), without a screenshot
    _, events = load_session(tmp_path / "s")
    assert events[0]["kind"] == "manual" and events[0]["screenshot"] is None


def test_refuses_non_empty_output(tmp_path, spec):
    (tmp_path / "s").mkdir()
    (tmp_path / "s" / "keep.txt").write_text("x")
    with pytest.raises(SessionError, match="not empty"):
        simulate(spec, tmp_path / "s")
    assert (tmp_path / "s" / "keep.txt").read_text() == "x"


@pytest.mark.parametrize(
    ("mutate", "msg"),
    [
        (lambda s: s["events"].append({"kind": "teleport", "screen": "home"}), "unknown kind"),
        (lambda s: s["events"].append({"kind": "click", "screen": "nope"}), "unknown screen"),
        (
            lambda s: s["events"].append({"kind": "click", "screen": "home", "target": "zz"}),
            "no widget",
        ),
    ],
)
def test_bad_spec(tmp_path, spec, mutate, msg):
    mutate(spec)
    with pytest.raises(SimulationError, match=msg):
        simulate(spec, tmp_path / "s")
