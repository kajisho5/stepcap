"""Copy a generated skill to where an agent loads skills from.

Claude Code: ``~/.claude/skills/<name>/`` (user) or ``./.claude/skills/<name>/``
(project). Codex: ``~/.agents/skills/<name>/`` or ``./.agents/skills/<name>/``.
Sources: code.claude.com/docs/en/skills, learn.chatgpt.com/docs/build-skills.
"""

from __future__ import annotations

import shutil
from pathlib import Path

AGENTS = ("claude", "codex")
SCOPES = ("user", "project")
_SUBDIR = {"claude": Path(".claude") / "skills", "codex": Path(".agents") / "skills"}


class InstallError(Exception):
    pass


def target_dir(
    agent: str, scope: str, name: str, cwd: Path | None = None, home: Path | None = None
) -> Path:
    if agent not in AGENTS:
        raise InstallError(f"unknown agent {agent!r}; use claude or codex")
    if scope not in SCOPES:
        raise InstallError(f"unknown scope {scope!r}; use user or project")
    base = (home or Path.home()) if scope == "user" else (cwd or Path.cwd())
    return base / _SUBDIR[agent] / name


def check_target(target: Path, force: bool) -> None:
    if target.exists() and not force:
        raise InstallError(f"{target} already exists; not overwriting (use --force to replace it)")
    if target.exists() and not (target / "SKILL.md").is_file():
        raise InstallError(f"{target} exists and is not a skill folder; refusing to replace it")


def install(skill_dir: Path, target: Path, force: bool = False) -> Path:
    check_target(target, force)
    if target.exists():
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_dir, target)
    return target
