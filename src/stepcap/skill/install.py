"""Copy a generated skill to where an agent loads skills from.

The folders come from ``registry``: Claude Code ``~/.claude/skills/<name>/``,
Codex and the shared folder ``~/.agents/skills/<name>/`` (also read by Gemini
CLI and Cursor), Gemini CLI ``~/.gemini/skills``, Cursor ``~/.cursor/skills``,
plus any agent in the user's agents.toml. ``--scope project`` uses the same
path under the current directory.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from stepcap.skill import registry

SCOPES = ("user", "project")


class InstallError(Exception):
    pass


def installers() -> list[str]:
    return [n for n, spec in registry.load().items() if spec.can_install]


def target_dir(
    agent: str, scope: str, name: str, cwd: Path | None = None, home: Path | None = None
) -> Path:
    try:
        spec = registry.get(agent)
    except registry.RegistryError as exc:
        raise InstallError(str(exc)) from exc
    if scope not in SCOPES:
        raise InstallError(f"unknown scope {scope!r}; use user or project")
    raw = spec.user_dir if scope == "user" else spec.project_dir
    if not raw:
        raise InstallError(f"{spec.label} ({agent}) has no {scope} skills folder")
    if scope == "user":
        if raw.startswith("~"):
            path = (home or Path.home()) / raw[1:].lstrip("/\\")
        else:
            path = Path(raw)
            if not path.is_absolute():
                raise InstallError(f"{agent}: user_dir must start with ~ or be absolute")
    else:
        path = (cwd or Path.cwd()) / raw
    return path / name


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
