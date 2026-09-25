"""Which agents stepcap knows: where each loads skills from and how to run it.

Built in (checked 2026-09-25 against each tool's docs):

  claude  Claude Code  ~/.claude/skills, ./.claude/skills     code.claude.com/docs/en/skills
  codex   Codex        ~/.agents/skills, ./.agents/skills     learn.chatgpt.com/docs/build-skills
  gemini  Gemini CLI   ~/.gemini/skills, ./.gemini/skills     geminicli.com/docs/cli/skills/
  cursor  Cursor       ~/.cursor/skills, ./.cursor/skills     cursor.com/docs/skills
  agents  the shared ~/.agents/skills folder, read by Codex, Gemini CLI and Cursor

Add or change agents in an ``agents.toml`` (see ``config_path()``)::

    [agents.myagent]
    label = "My agent"
    user_dir = "~/.myagent/skills"        # --install myagent --scope user
    project_dir = ".myagent/skills"       # --install myagent --scope project
    refine = ["myagent", "run", "{prompt}"]   # --agent myagent (optional)

``refine`` runs in the skill folder after the user confirmed. Placeholders:
``{prompt}`` (short instruction that points at _context/INSTRUCTIONS.md),
``{skill_dir}`` and ``{images}`` (comma-separated annotated screenshots; an
argument containing it is left out when there are none). ``refine[0]`` is
looked up on PATH.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
PLACEHOLDERS = ("{prompt}", "{skill_dir}", "{images}")
CONFIG_ENV = "STEPCAP_AGENTS_FILE"


class RegistryError(Exception):
    pass


@dataclass(frozen=True)
class AgentSpec:
    name: str
    label: str
    user_dir: str | None = None
    project_dir: str | None = None
    refine: tuple[str, ...] = ()
    readers: tuple[str, ...] = field(default=())  # other tools that read this folder
    source: str = "built-in"

    @property
    def can_install(self) -> bool:
        return bool(self.user_dir or self.project_dir)

    @property
    def can_refine(self) -> bool:
        return bool(self.refine)

    def executable(self) -> str | None:
        return shutil.which(self.refine[0]) if self.refine else None


BUILTIN: dict[str, AgentSpec] = {
    a.name: a
    for a in (
        AgentSpec(
            "claude",
            "Claude Code",
            "~/.claude/skills",
            ".claude/skills",
            (
                "claude",
                "-p",
                "{prompt}",
                "--permission-mode",
                "acceptEdits",
                "--allowedTools",
                "Read,Edit,Write",
            ),
            readers=("Cursor",),
        ),
        AgentSpec(
            "codex",
            "Codex",
            "~/.agents/skills",
            ".agents/skills",
            (
                "codex",
                "exec",
                "--sandbox",
                "workspace-write",
                "--skip-git-repo-check",
                "-C",
                "{skill_dir}",
                "--image={images}",
                "{prompt}",
            ),
            readers=("Gemini CLI", "Cursor"),
        ),
        AgentSpec(
            "gemini",
            "Gemini CLI",
            "~/.gemini/skills",
            ".gemini/skills",
            ("gemini", "-p", "{prompt}", "--approval-mode", "auto_edit"),
        ),
        AgentSpec("cursor", "Cursor", "~/.cursor/skills", ".cursor/skills"),
        AgentSpec(
            "agents",
            "Shared Agent Skills folder",
            "~/.agents/skills",
            ".agents/skills",
            readers=("Codex", "Gemini CLI", "Cursor"),
        ),
    )
}


def config_path() -> Path:
    """``$STEPCAP_AGENTS_FILE``, else %APPDATA%\\stepcap\\agents.toml on Windows,
    else ``$XDG_CONFIG_HOME/stepcap/agents.toml`` (default ~/.config)."""
    env = os.environ.get(CONFIG_ENV)
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "stepcap" / "agents.toml"
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "stepcap" / "agents.toml"


def _spec_from(name: str, raw: object, base: AgentSpec | None, where: str) -> AgentSpec:
    if not NAME_RE.match(name) or name == "none":
        raise RegistryError(f"{where}: agent name {name!r}: use a-z, 0-9 and hyphens")
    if not isinstance(raw, dict):
        raise RegistryError(f"{where}: [agents.{name}] must be a table")
    unknown = set(raw) - {"label", "user_dir", "project_dir", "refine"}
    if unknown:
        raise RegistryError(f"{where}: [agents.{name}] unknown keys: {', '.join(sorted(unknown))}")
    for key in ("label", "user_dir", "project_dir"):
        if key in raw and not isinstance(raw[key], str):
            raise RegistryError(f"{where}: [agents.{name}] {key} must be a string")
    refine = raw.get("refine", base.refine if base else ())
    if not isinstance(refine, (list, tuple)) or not all(isinstance(a, str) for a in refine):
        raise RegistryError(f"{where}: [agents.{name}] refine must be a list of strings")
    if refine and not any("{prompt}" in a for a in refine):
        raise RegistryError(f"{where}: [agents.{name}] refine must contain {{prompt}}")
    spec = AgentSpec(
        name,
        raw.get("label", base.label if base else name),
        raw.get("user_dir", base.user_dir if base else None),
        raw.get("project_dir", base.project_dir if base else None),
        tuple(refine),
        base.readers if base else (),
        where,
    )
    if not spec.can_install and not spec.can_refine:
        raise RegistryError(f"{where}: [agents.{name}] needs user_dir, project_dir or refine")
    return spec


def load(path: Path | None = None) -> dict[str, AgentSpec]:
    """Built-in agents, updated / extended by the config file if it exists."""
    specs = dict(BUILTIN)
    path = path or config_path()
    if not path.is_file():
        return specs
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RegistryError(f"{path}: {exc}") from exc
    agents = data.get("agents", {})
    if not isinstance(agents, dict):
        raise RegistryError(f"{path}: [agents] must be a table")
    for name, raw in agents.items():
        specs[name] = _spec_from(name, raw, specs.get(name), str(path))
    return specs


def get(name: str, specs: dict[str, AgentSpec] | None = None) -> AgentSpec:
    specs = specs if specs is not None else load()
    if name not in specs:
        raise RegistryError(f"unknown agent {name!r}; known: {', '.join(sorted(specs))}")
    return specs[name]


def expand(
    spec: AgentSpec, exe: str, prompt: str, skill_dir: Path, images: list[Path]
) -> list[str]:
    """The refine command with placeholders filled in (``refine[0]`` -> ``exe``)."""
    joined = ",".join(str(p) for p in images)
    out = [exe]
    for arg in spec.refine[1:]:
        if "{images}" in arg and not images:
            continue
        out.append(
            arg.replace("{prompt}", prompt)
            .replace("{skill_dir}", str(skill_dir))
            .replace("{images}", joined)
        )
    return out
