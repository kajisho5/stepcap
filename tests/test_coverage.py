"""Check a skill against its recording (RM-067)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stepcap.cli import main
from stepcap.gui import controller as ctl
from stepcap.simulate import simulate
from stepcap.skill import coverage
from stepcap.skill.run import SkillOptions, load_recording, run_skill

SAMPLE = Path(__file__).parent.parent / "docs" / "demo" / "sample"


@pytest.fixture
def rich_session(tmp_path, spec):
    spec = json.loads(json.dumps(spec))
    spec["accessibility"] = True
    spec["screens"]["home"]["url"] = "https://tasks.example.com/projects?x=1"
    spec["events"].append({"kind": "terminal", "command": "git status --short", "exit": 0})
    out = tmp_path / "s"
    simulate(spec, out, record_urls=True)
    return out


def test_draft_covers_everything(rich_session, tmp_path):
    res = run_skill(rich_session, SkillOptions(out_dir=tmp_path / "o", name="demo"))
    cov = res.info["coverage"]
    assert cov["score"] == 1.0, [i for i in cov["items"] if not i["found"]]
    kinds = {i["kind"] for i in cov["items"]}
    assert kinds == {"app", "element", "input", "url", "command", "note"}
    url = next(i for i in cov["items"] if i["kind"] == "url")
    assert url["value"] == "tasks.example.com" and url["steps"] == [1]


def test_rewrite_that_drops_things_is_reported(rich_session):
    _, doc, events = load_recording(rich_session)
    skill = """---
name: demo
description: Create a project in Acme Tasks.
---
# Create a project
1. Click "+ New project", type {{project_name}} into "Project name", click Create.
2. Open tasks.example.com if needed.
"""
    cov = coverage.check(skill, doc, events)
    missing = {(i.kind, i.value) for i in cov.missing}
    assert ("element", "Private project") in missing
    assert ("command", "git status --short") in missing
    assert any(k == "note" for k, _ in missing)
    assert ("element", "+ New project") not in missing  # found without the "+"
    assert ("input", "project_name") not in missing
    assert 0 < cov.score < 1


def test_matching_rules():
    doc = {
        "steps": [
            {
                "id": "s1",
                "event_id": 1,
                "kind": "manual",
                "title": "照明卓の電源が入っているか確認",
            },
            {
                "id": "s2",
                "event_id": 2,
                "kind": "click",
                "app_name": "Mixer",
                "element": {"name": "  Scene   1 "},
            },
        ]
    }
    events = [{"seq": 2, "kind": "terminal", "command": "ssh mixer reboot now"}]
    # a note rephrased slightly, the command's first words, case / width differences
    text = "まず照明卓の電源が入っているかを確認する。"
    text += "MIXER で ＳＣＥＮＥ 1 を押す。`ssh mixer` で再起動"
    cov = coverage.check(text, doc, events)
    assert cov.score == 1.0, cov.missing
    assert coverage.check("nothing", doc, events).found == 0


def test_real_claude_rewrite_sample(spec):
    """The committed skill written by a real `--agent claude` run."""
    import tempfile

    spec = json.loads(json.dumps(spec))
    spec["accessibility"] = True
    with tempfile.TemporaryDirectory() as d:
        simulate(spec, Path(d) / "s")
        _, doc, events = load_recording(Path(d) / "s")
    text = (SAMPLE / "SKILL.refined-by-claude.md").read_text(encoding="utf-8")
    cov = coverage.check(text, doc, events)
    assert cov.score >= 0.8
    assert [i.value for i in cov.missing] == ["Book venue"]  # the example card was generalised


def test_cli_check_skill_with_session(rich_session, tmp_path, capsys):
    run_skill(rich_session, SkillOptions(out_dir=tmp_path / "o", name="demo"))
    skill = tmp_path / "o" / "demo"
    assert main(["check-skill", str(skill), "--session", str(rich_session)]) == 0
    assert "recording coverage:" in capsys.readouterr().out
    md = skill / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8").replace("Private project", "privacy"), "utf-8")
    assert main(["check-skill", str(skill), "--session", str(rich_session)]) == 0
    out = capsys.readouterr().out
    assert "not mentioned: element 'Private project' (step 4)" in out
    code = main(
        ["check-skill", str(skill), "--session", str(rich_session), "--min-coverage", "1", "--json"]
    )
    assert code == 1
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is False and data["coverage"]["score"] < 1
    with pytest.raises(SystemExit):
        main(["check-skill", str(skill), "--min-coverage", "2"])


def test_gui_note():
    from types import SimpleNamespace

    item = {"kind": "element", "value": "Book venue", "found": False, "steps": [6]}
    res = SimpleNamespace(info={"coverage": {"found": 8, "total": 9, "items": [item]}})
    assert "8" in ctl.coverage_note(res, ctl.TEXTS["en"])
    assert "Book venue" in ctl.coverage_note(res, ctl.TEXTS["ja"])
    assert ctl.coverage_note(SimpleNamespace(info={}), ctl.TEXTS["en"]) == ""
