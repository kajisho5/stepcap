"""Agents from the built-in list and from agents.toml (`stepcap agents`)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from stepcap.cli import main
from stepcap.gui import controller as ctl
from stepcap.skill import agents, install, registry
from stepcap.skill.run import SkillError, SkillOptions, run_skill

FAKE_AGENT = """
import pathlib, sys
assert "_context/INSTRUCTIONS.md" in sys.argv[1]
p = pathlib.Path("SKILL.md")
head, body = p.read_text(encoding="utf-8").split("\\n---\\n", 1)
p.write_text(head + "\\n---\\n# Refined by my agent\\n\\n## Goal\\n\\nDo it.\\n", encoding="utf-8")
"""


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "agents.toml"
    monkeypatch.setenv(registry.CONFIG_ENV, str(path))
    return path


def test_builtins_without_config(config):
    specs = registry.load()
    assert list(specs) == ["claude", "codex", "gemini", "cursor", "agents"]
    assert specs["agents"].user_dir == "~/.agents/skills" and not specs["agents"].can_refine
    assert specs["gemini"].refine[:3] == ("gemini", "-p", "{prompt}")
    assert "auto_edit" in specs["gemini"].refine
    assert agents.refiners() == ["claude", "codex", "gemini"]
    assert install.installers() == ["claude", "codex", "gemini", "cursor", "agents"]


def test_install_folders(tmp_path, config):
    home, cwd = tmp_path / "h", tmp_path / "p"
    assert install.target_dir("claude", "user", "x", home=home) == home / ".claude/skills/x"
    assert install.target_dir("agents", "user", "x", home=home) == home / ".agents/skills/x"
    assert install.target_dir("codex", "project", "x", cwd=cwd) == cwd / ".agents/skills/x"
    assert install.target_dir("gemini", "user", "x", home=home) == home / ".gemini/skills/x"
    assert install.target_dir("cursor", "project", "x", cwd=cwd) == cwd / ".cursor/skills/x"
    with pytest.raises(install.InstallError, match="unknown agent"):
        install.target_dir("nope", "user", "x")


def test_commands_fill_placeholders(tmp_path, config):
    skill = tmp_path / "s"
    (skill / "references").mkdir(parents=True)
    cmd = agents.command("codex", "/bin/codex", skill)
    assert cmd[:2] == ["/bin/codex", "exec"] and "-C" in cmd and str(skill) in cmd
    assert not any(a.startswith("--image") for a in cmd)  # no screenshots -> no flag
    (skill / "references" / "step-01.png").write_bytes(b"x")
    cmd = agents.command("codex", "/bin/codex", skill)
    assert f"--image={skill / 'references' / 'step-01.png'}" in cmd
    assert cmd[-1] == agents.SHORT_PROMPT
    assert agents.command("gemini", "gemini", skill) == [
        "gemini",
        "-p",
        agents.SHORT_PROMPT,
        "--approval-mode",
        "auto_edit",
    ]
    with pytest.raises(agents.AgentError, match="no refine command"):
        agents.command("cursor", "cursor", skill)


def test_config_adds_and_overrides(tmp_path, config):
    config.write_text(
        """
[agents.myagent]
label = "My agent"
user_dir = "~/.myagent/skills"
project_dir = ".myagent/skills"
refine = ["myagent", "run", "--dir", "{skill_dir}", "{prompt}"]

[agents.claude]
refine = ["claude", "-p", "{prompt}", "--permission-mode", "plan"]
""",
        encoding="utf-8",
    )
    specs = registry.load()
    assert specs["myagent"].label == "My agent" and specs["myagent"].source == str(config)
    assert specs["claude"].user_dir == "~/.claude/skills"  # kept from the built-in
    assert specs["claude"].refine[-1] == "plan"
    home = tmp_path / "h"
    assert install.target_dir("myagent", "user", "x", home=home) == home / ".myagent/skills/x"
    cmd = agents.command("myagent", "/opt/myagent", tmp_path)
    assert cmd == ["/opt/myagent", "run", "--dir", str(tmp_path), agents.SHORT_PROMPT]
    assert ctl.custom_installers() == [("myagent", "My agent")]
    assert ctl.agent_label("myagent") == "My agent"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[agents.Bad_Name]\nuser_dir = '~/x'\n", "agent name"),
        ("[agents.x]\nlabel = 'X'\n", "needs user_dir"),
        ("[agents.x]\nrefine = ['x', 'go']\n", "must contain {prompt}"),
        ("[agents.x]\nrefine = 'x {prompt}'\n", "list of strings"),
        ("[agents.x]\nuser_dir = '~/x'\ncolour = 'red'\n", "unknown keys"),
        ("[agents\n", "agents.toml"),
    ],
)
def test_bad_config_is_reported(config, text, message):
    config.write_text(text, encoding="utf-8")
    with pytest.raises(registry.RegistryError, match=message):
        registry.load()
    assert main(["agents"]) == 1


def test_configured_agent_refines_and_installs(demo_session, tmp_path, config):
    script = tmp_path / "fake_agent.py"
    script.write_text(FAKE_AGENT, encoding="utf-8")
    config.write_text(
        f"""
[agents.myagent]
label = "My agent"
user_dir = "~/.myagent/skills"
refine = [{json.dumps(sys.executable)}, {json.dumps(str(script))}, "{{prompt}}"]
""",
        encoding="utf-8",
    )
    home = tmp_path / "home"
    opt = SkillOptions(
        out_dir=tmp_path / "o", name="acme", agent="myagent", install="myagent", yes=True, home=home
    )
    res = run_skill(demo_session, opt)
    assert res.ok, res.problems
    installed = home / ".myagent" / "skills" / "acme" / "SKILL.md"
    text = installed.read_text(encoding="utf-8")
    assert "# Refined by my agent" in text and 'status: "refined by myagent"' in text
    with pytest.raises(SkillError, match="unknown --agent 'nope'"):
        run_skill(demo_session, SkillOptions(out_dir=tmp_path / "o2", agent="nope"))
    with pytest.raises(SkillError, match="unknown --install 'nope'"):
        run_skill(demo_session, SkillOptions(out_dir=tmp_path / "o2", install="nope"))


def test_install_to_shared_folder_via_cli(demo_session, tmp_path, config, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    out = tmp_path / "out"
    code = main(
        ["skill", str(demo_session), "-o", str(out), "--name", "demo", "--install", "agents"]
    )
    assert code == 0
    assert (Path.home() / ".agents" / "skills" / "demo" / "SKILL.md").is_file()


def test_cli_agents_listing(config, capsys):
    assert main(["agents"]) == 0
    out = capsys.readouterr().out
    assert "Gemini CLI" in out and "install only" in out and str(config) in out
    assert main(["agents", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["config_exists"] is False
    names = [a["name"] for a in data["agents"]]
    assert names == ["claude", "codex", "gemini", "cursor", "agents"]


def test_config_path_defaults(monkeypatch, tmp_path):
    monkeypatch.delenv(registry.CONFIG_ENV, raising=False)
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(tmp_path))
        assert registry.config_path() == tmp_path / "stepcap" / "agents.toml"
    else:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert registry.config_path() == tmp_path / "stepcap" / "agents.toml"
        monkeypatch.delenv("XDG_CONFIG_HOME")
        assert registry.config_path() == Path.home() / ".config" / "stepcap" / "agents.toml"
