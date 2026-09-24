"""`stepcap skill` / `stepcap export` (addon acceptance criteria 4-7)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from stepcap.build.pipeline import BuildOptions, run_build
from stepcap.cli import main
from stepcap.session import read_json, write_json
from stepcap.simulate import simulate
from stepcap.skill import agents, frontmatter
from stepcap.skill.draft import choose_name, slugify
from stepcap.skill.run import SkillError, SkillOptions, run_export, run_skill
from stepcap.skill.validate import estimate_tokens, validate_skill

GH = "ghp_" + "Z9y8X7w6V5u4T3s2R1q0P9o8N7m6L5k4J3i2"


def _no_notes(spec):
    spec = json.loads(json.dumps(spec))
    spec["events"] = [e for e in spec["events"] if e["kind"] != "manual"]
    return spec


def test_agent_none_writes_valid_skill_with_references(demo_session, tmp_path):
    res = run_skill(demo_session, SkillOptions(out_dir=tmp_path / "out"))
    skill = Path(res.skill_dir)
    assert res.ok, res.problems
    assert skill.parent == tmp_path / "out" and skill.name == res.name
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    fields, body = frontmatter.parse(text)
    assert fields["name"] == skill.name
    assert 1 <= len(fields["description"]) <= 1024
    for section in ("## Goal", "## Inputs", "## Steps", "## Notes for the agent"):
        assert section in body
    refs = sorted(p.name for p in (skill / "references").iterdir())
    assert refs and all(r.endswith(".png") for r in refs)
    for r in refs:
        assert f"references/{r}" in body
    assert "{{input_1}}" in body  # the typed project name is an input
    assert "Check that the card" in body.split("## Inputs")[0]  # F7 note -> Goal
    assert validate_skill(skill)[0] == []


def test_goal_is_todo_without_notes(tmp_path, spec):
    simulate(_no_notes(spec), tmp_path / "s")
    res = run_skill(tmp_path / "s", SkillOptions(out_dir=tmp_path / "out"))
    body = (Path(res.skill_dir) / "SKILL.md").read_text(encoding="utf-8")
    goal = body.split("## Goal", 1)[1].split("## Inputs", 1)[0]
    assert "TODO" in goal
    assert res.ok


def test_recorded_typing_is_redacted_and_can_be_literal(tmp_path, spec):
    spec = json.loads(json.dumps(spec))
    typed = next(e for e in spec["events"] if e["kind"] == "type")
    typed["text"] = f"key {GH}"
    simulate(spec, tmp_path / "s", record_typing=True)
    assert GH not in (tmp_path / "s" / "events.jsonl").read_text(encoding="utf-8")
    res = run_skill(tmp_path / "s", SkillOptions(out_dir=tmp_path / "a"))
    body = (Path(res.skill_dir) / "SKILL.md").read_text(encoding="utf-8")
    assert GH not in body and "[REDACTED:github-token]" in body and res.ok

    # the person unticks "variable" in stepcap edit -> the literal (redacted) value is used
    doc = read_json(tmp_path / "s" / "steps.json")
    step = next(s for s in doc["steps"] if s["kind"] == "type")
    step["input"] = {"name": "api_key", "variable": False}
    write_json(tmp_path / "s" / "steps.json", doc)
    res = run_skill(tmp_path / "s", SkillOptions(out_dir=tmp_path / "b"))
    body = (Path(res.skill_dir) / "SKILL.md").read_text(encoding="utf-8")
    assert "{{api_key}}" not in body and "Enter `key [REDACTED:github-token]`" in body


def test_refuses_to_overwrite_and_force_replaces(demo_session, tmp_path):
    opt = SkillOptions(out_dir=tmp_path / "out", name="demo-skill")
    run_skill(demo_session, opt)
    with pytest.raises(SkillError, match="already exists"):
        run_skill(demo_session, opt)
    opt.force = True
    assert run_skill(demo_session, opt).ok


def test_bad_name_is_rejected(demo_session, tmp_path):
    with pytest.raises(SkillError, match="--name"):
        run_skill(demo_session, SkillOptions(out_dir=tmp_path, name="Bad_Name"))


def test_install_project_scope_and_no_overwrite(demo_session, tmp_path):
    proj = tmp_path / "proj"
    opt = SkillOptions(
        out_dir=tmp_path / "out", name="acme", install="claude", scope="project", cwd=proj
    )
    res = run_skill(demo_session, opt)
    assert res.installed_to == str(proj / ".claude" / "skills" / "acme")
    assert (proj / ".claude" / "skills" / "acme" / "SKILL.md").is_file()
    opt.out_dir = tmp_path / "out2"
    with pytest.raises(SkillError, match="already exists"):
        run_skill(demo_session, opt)
    assert not (tmp_path / "out2").exists()  # nothing written before the check


def test_install_codex_user_scope(demo_session, tmp_path):
    home = tmp_path / "home"
    res = run_skill(
        demo_session,
        SkillOptions(out_dir=tmp_path / "out", name="acme", install="codex", home=home),
    )
    assert (home / ".agents" / "skills" / "acme" / "SKILL.md").is_file()
    assert res.installed_to.endswith(str(Path(".agents") / "skills" / "acme"))


def test_export_both(demo_session, tmp_path):
    res = run_export(demo_session, "both", tmp_path / "dist", SkillOptions(out_dir=tmp_path))
    assert res.ok
    guide = tmp_path / "dist" / "guide"
    assert (guide / "guide.md").is_file() and (guide / "guide.html").is_file()
    assert (guide / "checklist.html").is_file() and any((guide / "images").iterdir())
    skills = list((tmp_path / "dist" / "skill").iterdir())
    assert len(skills) == 1 and (skills[0] / "SKILL.md").is_file()


def test_export_refuses_output_inside_session(demo_session):
    with pytest.raises(SkillError, match="session"):
        run_export(demo_session, "both", demo_session, SkillOptions(out_dir=demo_session))
    with pytest.raises(SkillError, match="session"):
        run_skill(demo_session, SkillOptions(out_dir=demo_session.parent, name=demo_session.name))


def test_agent_dry_run_lists_files_and_runs_nothing(demo_session, tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "find_cli", lambda a: "/usr/bin/" + a)
    monkeypatch.setattr(agents, "run", lambda *a: pytest.fail("agent must not run"))
    opt = SkillOptions(out_dir=tmp_path / "o", agent="claude", dry_run=True)
    res = run_skill(demo_session, opt)
    assert "SKILL.md" in res.shared_files and "_context/events.jsonl" in res.shared_files
    assert res.agent_command[:2] == ["/usr/bin/claude", "-p"]
    assert not (tmp_path / "o").exists()


def test_agent_missing_cli_is_a_clear_error(demo_session, tmp_path, monkeypatch):
    monkeypatch.setattr(agents, "find_cli", lambda a: None)
    with pytest.raises(SkillError, match=r"not found on PATH.*--agent none"):
        run_skill(demo_session, SkillOptions(out_dir=tmp_path / "o", agent="codex"))
    assert not (tmp_path / "o").exists()


FAKE_AGENT = """
import pathlib, sys
p = pathlib.Path("SKILL.md")
assert pathlib.Path("_context/INSTRUCTIONS.md").is_file()
assert pathlib.Path("_context/events.jsonl").is_file()
head, body = p.read_text(encoding="utf-8").split("\\n---\\n", 1)
p.write_text(head + "\\n---\\n# Refined\\n\\n## Goal\\n\\nDo it.\\n", encoding="utf-8")
"""


def test_agent_run_with_confirmation(demo_session, tmp_path, monkeypatch):
    script = tmp_path / "fake_agent.py"
    script.write_text(FAKE_AGENT, encoding="utf-8")
    monkeypatch.setattr(agents, "find_cli", lambda a: sys.executable)
    monkeypatch.setattr(agents, "command", lambda agent, exe, d: [exe, str(script)])
    asked = []
    opt = SkillOptions(out_dir=tmp_path / "o", agent="claude", name="acme")
    with pytest.raises(SkillError, match="cancelled"):
        run_skill(demo_session, opt, confirm=lambda q: asked.append(q) or False)
    assert "events.jsonl" in asked[0]
    assert not (tmp_path / "o" / "acme" / "_context").exists()  # context removed

    opt.force = True
    res = run_skill(demo_session, opt, confirm=lambda q: True)
    skill = tmp_path / "o" / "acme"
    assert res.ok, res.problems
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    assert "# Refined" in text and 'status: "refined by claude"' in text
    assert not (skill / "_context").exists()
    assert (tmp_path / "o" / "acme.draft.md").is_file()


def test_validator_catches_problems(tmp_path):
    d = tmp_path / "my-skill"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: other-name\ndescription: >\n  Folded\n  text.\n---\n"
        f"See [x](references/missing.png) and [y](../outside.md). Token {GH}\n" + "line\n" * 500,
        encoding="utf-8",
    )
    problems, _ = validate_skill(d)
    joined = "\n".join(problems)
    assert "must equal the folder name" in joined
    assert "missing.png' does not exist" in joined
    assert "outside the skill folder" in joined
    assert "secret (github-token)" in joined
    assert "lines" in joined


def test_frontmatter_parser_variants():
    fields, body = frontmatter.parse(
        "---\nname: a-b\ndescription: 'it''s'\nlicense: MIT  # comment\n"
        'metadata:\n  author: "x"\n  version: 1.0\nwhen: |\n  one\n  two\n---\nBody\n'
    )
    assert fields == {
        "name": "a-b",
        "description": "it's",
        "license": "MIT",
        "metadata": {"author": "x", "version": "1.0"},
        "when": "one\ntwo",
    }
    assert body == "Body\n"
    with pytest.raises(frontmatter.FrontmatterError):
        frontmatter.parse("no frontmatter")


def test_names_and_token_estimate():
    assert slugify("Create a project!") == "create-a-project"
    assert slugify("プロジェクト作成") == ""
    assert choose_name({"title": "プロジェクト作成", "steps": [{"app_name": "Acme Tasks"}]}) == (
        "acme-tasks"
    )
    assert choose_name({"title": "", "steps": []}) == "recorded-procedure"
    assert estimate_tokens("abcd" * 10) == 10 and estimate_tokens("日本語") == 3


def test_old_format_1_steps_json_is_migrated(demo_session):
    run_build(demo_session, BuildOptions(formats=("md",)))
    doc = read_json(demo_session / "steps.json")
    for s in doc["steps"]:
        s.pop("input", None)
    doc["format"] = 1
    write_json(demo_session / "steps.json", doc)
    res = run_build(demo_session, BuildOptions(formats=("md",)))
    assert res.steps_json == "kept"
    doc = read_json(demo_session / "steps.json")
    assert doc["format"] == 2
    typed = [s for s in doc["steps"] if s["kind"] == "type"]
    assert typed and typed[0]["input"] == {"name": "input_1", "variable": True}


def test_cli_skill_and_export(demo_session, tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["skill", str(demo_session), "-o", "out", "--name", "acme", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] and data["name"] == "acme"
    assert main(["skill", str(demo_session), "-o", "out", "--name", "acme"]) == 1
    assert "already exists" in capsys.readouterr().err
    assert main(["export", str(demo_session), "--format", "both", "-o", "dist"]) == 0
    out = capsys.readouterr().out
    assert "Guide dist" in out and "valid" in out
    rc = main(["skill", str(demo_session), "-o", "o2", "--agent", "claude", "--dry-run"])
    assert rc in (0, 1)  # 1 when the claude CLI is not installed


def test_cli_check_skill(demo_session, tmp_path, capsys):
    res = run_skill(demo_session, SkillOptions(out_dir=tmp_path, name="acme"))
    assert main(["check-skill", res.skill_dir]) == 0
    assert "valid" in capsys.readouterr().out
    md = Path(res.skill_dir) / "SKILL.md"
    md.write_text(md.read_text(encoding="utf-8") + f"\n{GH}\n", encoding="utf-8")
    assert main(["check-skill", res.skill_dir, "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert not data["ok"] and "github-token" in data["problems"][0]


SAMPLE = Path(__file__).resolve().parents[1] / "docs" / "demo" / "sample"


def test_committed_sample_skill_is_valid_and_links_resolve():
    skill = SAMPLE / "skill" / "create-project-move-card"
    problems, info = validate_skill(skill)
    assert problems == [] and info["links"] == 12
    refined = (SAMPLE / "SKILL.refined-by-claude.md").read_text(encoding="utf-8")
    frontmatter.parse(refined)
    links = re.findall(r"\]\(([^)]+)\)", refined)
    assert len(links) >= 12
    for link in links:
        assert (SAMPLE / link).exists(), link
    assert (SAMPLE / "guide" / "guide.md").is_file()
    assert (SAMPLE / "guide" / "guide.html").is_file()
