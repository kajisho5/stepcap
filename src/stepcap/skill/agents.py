"""Let the user's own coding agent rewrite the draft (``--agent claude|codex``).

stepcap itself sends nothing anywhere: it runs the agent CLI that is already
installed on this machine, in the skill folder, after showing exactly which
files the agent will be able to read. Where the agent sends them is up to the
agent's own configuration.

Non-interactive invocations (checked 2026-09-24):
  claude -p PROMPT --permission-mode acceptEdits --allowedTools Read,Edit,Write
  codex exec --sandbox workspace-write --skip-git-repo-check -C DIR [--image a,b] PROMPT
"""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import resources
from pathlib import Path
from typing import Any

from stepcap.redact import redact_obj
from stepcap.skill import frontmatter

AGENTS = ("claude", "codex")
CONTEXT_DIR = "_context"
INSTRUCTIONS = "INSTRUCTIONS.md"
CONTEXT_FILES = (INSTRUCTIONS, "steps.json", "events.jsonl")
MAX_IMAGES = 20  # images attached to codex exec (it also reads files in its sandbox)
SHORT_PROMPT = (
    f"Read {CONTEXT_DIR}/{INSTRUCTIONS} in the current folder and follow it: rewrite SKILL.md "
    "into a reusable skill. Edit only SKILL.md."
)
_STEP_FIELDS = (
    "id",
    "kind",
    "title",
    "description",
    "click_type",
    "keys",
    "direction",
    "window_title",
    "app_name",
    "input",
    "event_id",
)


class AgentError(Exception):
    pass


def find_cli(agent: str) -> str | None:
    return shutil.which(agent)


def missing_cli_message(agent: str) -> str:
    product = {"claude": "Claude Code", "codex": "the Codex CLI"}[agent]
    return (
        f"the {agent!r} command was not found on PATH. Install {product} and log in, "
        "or run with --agent none to write the draft without an agent."
    )


def refine_prompt() -> str:
    return resources.files("stepcap").joinpath("prompts/skill_refine.md").read_text("utf-8")


def write_context(skill_dir: Path, doc: dict[str, Any], events: list[dict[str, Any]]) -> Path:
    """Write the redacted inputs for the agent into SKILL_DIR/_context/."""
    ctx = skill_dir / CONTEXT_DIR
    ctx.mkdir(parents=True, exist_ok=True)
    (ctx / INSTRUCTIONS).write_text(refine_prompt(), encoding="utf-8")
    slim = {
        "title": doc.get("title"),
        "lang": doc.get("lang"),
        "steps": [{k: s[k] for k in _STEP_FIELDS if k in s} for s in doc.get("steps", [])],
    }
    (ctx / "steps.json").write_text(
        json.dumps(redact_obj(slim), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with open(ctx / "events.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for ev in events:
            fh.write(json.dumps(redact_obj(ev), ensure_ascii=False) + "\n")
    return ctx


def shared_files(skill_dir: Path) -> list[Path]:
    return sorted(p for p in skill_dir.rglob("*") if p.is_file())


def command(agent: str, exe: str, skill_dir: Path) -> list[str]:
    if agent == "claude":
        return [
            exe,
            "-p",
            SHORT_PROMPT,
            "--permission-mode",
            "acceptEdits",
            "--allowedTools",
            "Read,Edit,Write",
        ]
    if agent == "codex":
        cmd = [exe, "exec", "--sandbox", "workspace-write", "--skip-git-repo-check"]
        cmd += ["-C", str(skill_dir)]
        images = sorted((skill_dir / "references").glob("*.png"))[:MAX_IMAGES]
        if images:
            cmd += ["--image", ",".join(str(p) for p in images)]
        return [*cmd, SHORT_PROMPT]
    raise AgentError(f"unknown agent {agent!r}; use none, claude or codex")


def run(cmd: list[str], skill_dir: Path) -> None:
    try:
        proc = subprocess.run(cmd, cwd=skill_dir, check=False)
    except OSError as exc:
        raise AgentError(f"could not start {cmd[0]}: {exc}") from exc
    if proc.returncode != 0:
        raise AgentError(f"{Path(cmd[0]).name} exited with code {proc.returncode}")


def cleanup(skill_dir: Path) -> None:
    shutil.rmtree(skill_dir / CONTEXT_DIR, ignore_errors=True)


def mark_refined(md: Path, agent: str) -> None:
    """Set ``metadata.status`` to ``refined by <agent>`` (left alone if unreadable)."""
    try:
        fields, body = frontmatter.parse(md.read_text(encoding="utf-8"))
    except (frontmatter.FrontmatterError, OSError):
        return
    meta = fields.get("metadata")
    if not isinstance(meta, dict):
        return
    meta["status"] = f"refined by {agent}"
    md.write_text(frontmatter.dump(fields) + body, encoding="utf-8", newline="\n")
