"""`stepcap skill` / `stepcap export`: orchestration, independent of argparse."""

from __future__ import annotations

import shlex
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from PIL import Image

from stepcap.build import annotate
from stepcap.build import steps as steps_mod
from stepcap.build.pipeline import (
    CHECKLIST_HTML,
    GUIDE_HTML,
    GUIDE_MD,
    IMAGES_DIR,
    BuildOptions,
    BuildResult,
    load_or_create_steps,
    run_build,
)
from stepcap.redact import redact_obj
from stepcap.session import STEPS_FILE, SessionError, load_session, write_json
from stepcap.skill import agents, draft, registry
from stepcap.skill import install as install_mod
from stepcap.skill.validate import MAX_NAME, NAME_RE, validate_skill

REF_DIR = "references"
REF_WIDTH = 1280
EXPORT_FORMATS = ("guide", "skill", "both")


class SkillError(Exception):
    pass


@dataclass
class SkillOptions:
    out_dir: Path
    name: str | None = None
    agent: str = "none"
    install: str = "none"
    scope: str = "user"
    force: bool = False
    yes: bool = False
    dry_run: bool = False
    cwd: Path | None = None  # base for --scope project (default: current directory)
    home: Path | None = None  # base for --scope user (default: home directory)


@dataclass
class SkillResult:
    session: str
    name: str
    skill_dir: str
    steps: int
    files: list[str] = field(default_factory=list)
    agent: str = "none"
    agent_command: list[str] = field(default_factory=list)
    shared_files: list[str] = field(default_factory=list)
    installed_to: str | None = None
    problems: list[str] = field(default_factory=list)
    info: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["ok"] = self.ok
        return d


Confirm = Callable[[str], bool]


def _check_out(path: Path, force: bool, what: str) -> None:
    if path.exists() and not path.is_dir():
        raise SkillError(f"{path} exists and is not a directory")
    if path.exists() and any(path.iterdir()) and not force:
        raise SkillError(f"{path} already exists; not overwriting (use --force to replace {what})")


def _inside(child: Path, parent: Path) -> bool:
    child, parent = child.resolve(), parent.resolve()
    return child == parent or parent in child.parents


def _load(session: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    meta, doc = load_or_create_steps(session, BuildOptions(), BuildResult("", 0))
    write_json(session / STEPS_FILE, doc)  # keep migrations / first-time steps.json
    _, events = load_session(session)
    return meta, doc, [redact_obj(ev) for ev in events]


def _references(session: Path, doc: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any], int]]:
    """step id -> (relative path, step, number) for steps with a screenshot."""
    refs = {}
    for n, s in enumerate(doc["steps"], 1):
        if s.get("screenshot"):
            refs[s["id"]] = (f"{REF_DIR}/step-{n:02d}.png", s, n)
    return refs


def _write_references(session: Path, doc: dict[str, Any], refs, skill_dir: Path) -> list[str]:
    written = []
    loaded: dict[str, Image.Image] = {}
    (skill_dir / REF_DIR).mkdir(parents=True, exist_ok=True)
    for rel, s, n in refs.values():
        sid = s["screenshot"]
        if sid not in loaded:
            loaded.clear()
            loaded[sid] = Image.open(steps_mod.ensure_work_copy(session, sid)).convert("RGB")
        img, _ = annotate.render(
            loaded[sid],
            s,
            n,
            REF_WIDTH,
            None,
            doc.get("marker") or "box",
            bool(doc.get("spotlight")),
            bool(doc.get("auto_arrows", True)),
        )
        (skill_dir / rel).write_bytes(annotate.encode(img, "png", 85))
        written.append(rel)
    return written


def run_skill(session: Path, opt: SkillOptions, confirm: Confirm | None = None) -> SkillResult:
    session = Path(session)
    try:
        refiners, installers = agents.refiners(), install_mod.installers()
    except registry.RegistryError as exc:
        raise SkillError(str(exc)) from exc
    if opt.agent not in ("none", *refiners):
        raise SkillError(
            f"unknown --agent {opt.agent!r}; use none or {', '.join(refiners)} (see stepcap agents)"
        )
    if opt.install not in ("none", *installers):
        raise SkillError(
            f"unknown --install {opt.install!r}; use none or {', '.join(installers)} "
            "(see stepcap agents)"
        )
    if opt.name is not None and (len(opt.name) > MAX_NAME or not NAME_RE.match(opt.name)):
        raise SkillError(
            f"--name {opt.name!r}: use 1-{MAX_NAME} characters of a-z, 0-9 and single hyphens"
        )
    meta, doc, events = _load(session)
    name = opt.name or draft.choose_name(doc)
    skill_dir = Path(opt.out_dir) / name
    if _inside(session, skill_dir):
        raise SkillError(f"{skill_dir} contains the session folder; choose another -o directory")
    _check_out(skill_dir, opt.force, "it")
    target = None
    if opt.install != "none":
        try:
            target = install_mod.target_dir(opt.install, opt.scope, name, opt.cwd, opt.home)
            install_mod.check_target(target, opt.force)
        except install_mod.InstallError as exc:
            raise SkillError(str(exc)) from exc

    refs = _references(session, doc)
    res = SkillResult(
        session=str(session),
        name=name,
        skill_dir=str(skill_dir),
        steps=len(doc["steps"]),
        agent=opt.agent,
        dry_run=opt.dry_run,
        installed_to=str(target) if target else None,
    )
    res.files = ["SKILL.md", *(r[0] for r in refs.values())]
    exe = None
    if opt.agent != "none":
        exe = agents.find_cli(opt.agent)
        res.agent_command = agents.command(opt.agent, exe or opt.agent, skill_dir)
        res.shared_files = sorted(
            [*res.files, *(f"{agents.CONTEXT_DIR}/{f}" for f in agents.CONTEXT_FILES)]
        )
    if opt.dry_run:
        if opt.agent != "none" and exe is None:
            raise SkillError(agents.missing_cli_message(opt.agent))
        return res
    if opt.agent != "none" and exe is None:
        raise SkillError(agents.missing_cli_message(opt.agent))

    if skill_dir.exists():
        if any(skill_dir.iterdir()) and not (skill_dir / "SKILL.md").is_file():
            raise SkillError(f"{skill_dir} is not a skill folder; refusing to replace it")
        shutil.rmtree(skill_dir)
    skill_dir.mkdir(parents=True)
    _write_references(session, doc, refs, skill_dir)
    rel_refs = {sid: r[0] for sid, r in refs.items()}
    text = draft.render(doc, events, meta, name, rel_refs)
    (skill_dir / "SKILL.md").write_text(text, encoding="utf-8", newline="\n")

    if opt.agent != "none" and exe is not None:
        agents.write_context(skill_dir, doc, events)
        listing = "\n".join(f"  {skill_dir / f}" for f in res.shared_files)
        question = (
            f"{opt.agent} will be able to read these files (secrets already masked):\n{listing}\n"
            f"Command: {shlex.join(res.agent_command)}\nRun it?"
        )
        try:
            if not opt.yes and not (confirm and confirm(question)):
                raise SkillError("cancelled; the draft SKILL.md was kept (no agent was run)")
            draft_copy = skill_dir.parent / f"{name}.draft.md"
            draft_copy.write_text(text, encoding="utf-8", newline="\n")
            try:
                agents.run(res.agent_command, skill_dir)
            except agents.AgentError as exc:
                raise SkillError(f"{exc}; the draft is in {draft_copy}") from exc
            agents.mark_refined(skill_dir / "SKILL.md", opt.agent)
        finally:
            agents.cleanup(skill_dir)

    res.problems, res.info = validate_skill(skill_dir)
    if res.ok and target is not None:
        install_mod.install(skill_dir, target, opt.force)
    elif target is not None:
        res.installed_to = None
    return res


# ------------------------------------------------------------------------ export
@dataclass
class ExportResult:
    session: str
    out_dir: str
    format: str
    guide_dir: str | None = None
    guide_files: list[str] = field(default_factory=list)
    skill: dict[str, Any] | None = None
    dry_run: bool = False

    @property
    def ok(self) -> bool:
        return self.skill is None or bool(self.skill.get("ok"))

    def to_dict(self) -> dict[str, Any]:
        d = dict(self.__dict__)
        d["ok"] = self.ok
        return d


def _copy_guide(session: Path, dest: Path) -> list[str]:
    dest.mkdir(parents=True, exist_ok=True)
    files = []
    for name in (GUIDE_MD, GUIDE_HTML, CHECKLIST_HTML):
        if (session / name).is_file():
            shutil.copyfile(session / name, dest / name)
            files.append(name)
    if (session / IMAGES_DIR).is_dir():
        shutil.copytree(session / IMAGES_DIR, dest / IMAGES_DIR)
        files += [f"{IMAGES_DIR}/{p.name}" for p in sorted((dest / IMAGES_DIR).iterdir())]
    return files


def run_export(
    session: Path,
    fmt: str,
    out_dir: Path,
    skill_opt: SkillOptions,
    build_opt: BuildOptions | None = None,
    confirm: Confirm | None = None,
) -> ExportResult:
    if fmt not in EXPORT_FORMATS:
        raise SkillError(f"unknown format {fmt!r}; use guide, skill or both")
    session, out_dir = Path(session), Path(out_dir)
    if _inside(session, out_dir):
        raise SkillError(f"{out_dir} contains the session folder; choose another -o directory")
    res = ExportResult(str(session), str(out_dir), fmt, dry_run=skill_opt.dry_run)
    guide_dir = out_dir / "guide"
    if fmt in ("guide", "both"):
        _check_out(guide_dir, skill_opt.force, "it")
        res.guide_dir = str(guide_dir)
    if fmt in ("skill", "both"):
        skill_opt.out_dir = out_dir / "skill"
        # checks (existing folders, agent CLI, install target) before anything is written
        checked = run_skill(session, replace(skill_opt, dry_run=True), confirm)
        if skill_opt.dry_run:
            res.skill = checked.to_dict()
    if skill_opt.dry_run:
        if fmt in ("guide", "both"):
            res.guide_files = [GUIDE_MD, f"{IMAGES_DIR}/", GUIDE_HTML, CHECKLIST_HTML]
        return res
    if fmt in ("guide", "both"):
        run_build(session, build_opt or BuildOptions())
        if guide_dir.exists():
            shutil.rmtree(guide_dir)
        res.guide_files = _copy_guide(session, guide_dir)
    if fmt in ("skill", "both"):
        res.skill = run_skill(session, skill_opt, confirm).to_dict()
    return res


def ask(question: str) -> bool:
    if not sys.stdin.isatty():
        raise SkillError("cannot ask for confirmation (stdin is not a terminal); pass --yes")
    print(question, end=" [y/N] ", file=sys.stderr, flush=True)
    return input().strip().lower() in ("y", "yes")


__all__ = ["SessionError", "SkillError", "SkillOptions", "ask", "run_export", "run_skill"]
