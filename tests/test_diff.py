from __future__ import annotations

import copy
import json

import pytest

from stepcap import diff
from stepcap.cli import main
from stepcap.simulate import simulate


@pytest.fixture
def pair(tmp_path, spec):
    """A = the demo; B = the same task, done differently."""
    a = copy.deepcopy(spec)
    a["accessibility"] = True  # element names as UIA / AX would give them (no OCR in tests)
    a["screens"]["home"]["url"] = "https://tasks.example.com/projects?tab=all"
    a["events"].append({"kind": "terminal", "command": "git pull", "exit": 0})
    b = copy.deepcopy(a)
    ev = b["events"]
    ev[2]["text"] = "Q4 plan"  # different value typed
    del ev[3]  # the "Private project" checkbox was not clicked
    ev.insert(5, {"kind": "click", "screen": "board", "target": "c3"})  # extra click
    b["screens"]["dialog"]["base"] = "board"  # the dialog now opens over another page
    b["events"][-1]["command"] = "git  pull --rebase"
    simulate(a, tmp_path / "A", record_typing=True, record_urls=True)
    simulate(b, tmp_path / "B", record_typing=True, record_urls=True)
    return tmp_path / "A", tmp_path / "B"


def test_key_ignores_position_and_wording():
    s1 = {"kind": "click", "click_type": "single", "element": {"name": "Save "}, "title": "x"}
    s2 = {"kind": "click", "click_type": "single", "element": {"name": "save"}, "title": "y"}
    assert diff.key(s1) == diff.key(s2)
    assert diff.key({"kind": "key", "keys": "Ctrl+S"}) == ("key", "ctrl+s")


def test_same_recording_is_identical(demo_session):
    d = diff.compare(demo_session, demo_session)
    assert d.identical
    assert d.count("same") == len(d.changes) > 5


def test_missing_extra_changed(pair):
    a, b = pair
    d = diff.compare(a, b)
    by = {c.status: [] for c in d.changes}
    for c in d.changes:
        by[c.status].append(c)
    assert [c.a.title for c in by["missing"]] == ['Click the "Private project" checkbox']
    assert [c.b.title for c in by["extra"]] == ['Click "Collect quotes"']
    notes = {c.a.title: c.notes for c in by["changed"]}
    assert any("a different value was typed" in n for n in notes.values())
    assert any("the screen looks different" in " ".join(n) for n in notes.values())
    assert not d.identical
    assert d.urls["both"] == ["tasks.example.com/projects"]
    assert d.commands == {"only_a": ["git pull"], "only_b": ["git pull --rebase"], "both": []}


def test_report_is_one_self_contained_file(pair):
    d = diff.compare(*pair)
    page = diff.report_html(d)
    assert "only in A" in page and "only in B" in page
    assert "data:image/jpeg;base64," in page
    assert 'src="raw/' not in page and "http" not in page.replace("tasks.example.com", "")


def test_cli_exit_codes_and_json(pair, tmp_path, capsys):
    a, b = pair
    report = tmp_path / "report.html"
    assert main(["diff", str(a), str(b), "-o", str(report)]) == 0
    out = capsys.readouterr().out
    assert '- 4. Click the "Private project" checkbox' in out and report.exists()
    assert main(["diff", str(a), str(b), "--fail-on", "missing"]) == 1
    assert main(["diff", str(a), str(a), "--fail-on", "any"]) == 0
    capsys.readouterr()
    assert main(["diff", str(a), str(b), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["summary"]["missing"] == 1 and data["summary"]["extra"] == 1
    assert data["identical"] is False


def test_cli_missing_session(tmp_path, capsys):
    assert main(["diff", str(tmp_path / "nope"), str(tmp_path / "nope2")]) == 1
    assert "error" in capsys.readouterr().err
