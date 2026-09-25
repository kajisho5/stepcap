from __future__ import annotations

import copy
import json

import pytest

from stepcap.cli import main
from stepcap.simulate import simulate
from stepcap.skill.frontmatter import parse
from stepcap.skill.run import SkillError, SkillOptions, run_skill


@pytest.fixture
def runs(tmp_path, spec):
    """Three recordings of the same task: B skipped a step, C did one more."""
    a = copy.deepcopy(spec)
    a["accessibility"] = True
    b = copy.deepcopy(a)
    b["events"][2]["text"] = "Website relaunch"
    del b["events"][3]  # no "Private project"
    c = copy.deepcopy(a)
    c["events"][2]["text"] = "Hiring 2027"
    c["events"].insert(5, {"kind": "click", "screen": "board", "target": "c3"})
    paths = []
    for name, sp in zip("ABC", (a, b, c), strict=True):
        simulate(sp, tmp_path / name, record_typing=True)
        paths.append(tmp_path / name)
    return paths


def _skill(tmp_path, runs, **kw):
    res = run_skill(runs[0], SkillOptions(tmp_path / "skills", also=tuple(runs[1:]), **kw))
    return res, (tmp_path / "skills" / res.name / "SKILL.md").read_text("utf-8")


def test_optional_steps_values_and_extra_steps(tmp_path, runs):
    res, text = _skill(tmp_path, runs)
    assert res.ok, res.problems
    assert res.recordings == [str(p) for p in runs]
    meta, body = parse(text)
    assert meta["metadata"]["recordings"] == "3"
    assert "(from 3 recordings)" in meta["description"]
    assert "typed in the recordings: `Q3 launch plan`, `Website relaunch`, `Hiring 2027`" in body
    step4 = body.split("\n4. ")[1].split("\n5. ")[0]
    assert "Private project" in step4 and "Optional: done in 2 of 3 recordings" in step4
    assert body.count("Optional:") == 1
    diff = body.split("## Differences between recordings")[1].split("## Notes")[0]
    assert "1. `A`, 2. `B`, 3. `C`" in diff
    assert '- Recording 3, after step 5: **Click "Collect quotes"**' in diff
    assert len(res.info["coverage_others"]) == 2


def test_same_values_everywhere_hint_fixed(tmp_path, spec):
    a = copy.deepcopy(spec)
    for name in "AB":
        simulate(a, tmp_path / name, record_typing=True)
    _, text = _skill(tmp_path, [tmp_path / "A", tmp_path / "B"])
    assert "the same in all 2 recordings: `Q3 launch plan` (maybe a fixed value)" in text
    assert "Optional:" not in text
    assert "The other recordings did no step that recording 1 did not." in text


def test_one_recording_is_unchanged(tmp_path, runs):
    res = run_skill(runs[0], SkillOptions(tmp_path / "one"))
    text = (tmp_path / "one" / res.name / "SKILL.md").read_text("utf-8")
    assert "from one recording" in text and "Differences between recordings" not in text
    assert "recordings:" not in text.split("---")[1]
    assert res.recordings == [str(runs[0])]


def test_same_recording_twice_is_refused(tmp_path, runs):
    with pytest.raises(SkillError, match="given twice"):
        run_skill(runs[0], SkillOptions(tmp_path / "s", also=(runs[0],)))


def test_cli_several_sessions(tmp_path, runs, capsys):
    out = tmp_path / "cli"
    assert main(["skill", *map(str, runs), "-o", str(out), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["recordings"] == [str(p) for p in runs] and data["ok"]
    assert main(["skill", *map(str, runs), "-o", str(tmp_path / "cli2")]) == 0
    assert "from 3 recordings" in capsys.readouterr().out
