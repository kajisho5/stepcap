"""Command line interface."""

from __future__ import annotations

import argparse
import contextlib
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from stepcap import __version__
from stepcap.session import SessionError

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _err(msg: str) -> None:
    print(f"stepcap: error: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------- record
def cmd_record(args: argparse.Namespace) -> int:
    from stepcap.hotkeys import HotkeyError, check_distinct, parse_hotkey
    from stepcap.session import default_session_dir

    try:
        hk = (
            parse_hotkey(args.hotkey_stop),
            parse_hotkey(args.hotkey_pause),
            parse_hotkey(args.hotkey_manual),
        )
        check_distinct(*hk)
    except HotkeyError as exc:
        _err(str(exc))
        return EXIT_USAGE

    from stepcap.capture.recorder import RecorderError, RecordOptions, record

    opts = RecordOptions(
        out_dir=Path(args.output) if args.output else default_session_dir(),
        monitor=args.monitor,
        record_typing=args.record_typing,
        exclude_apps=tuple(args.exclude_app or ()),
        hotkey_stop=hk[0],
        hotkey_pause=hk[1],
        hotkey_manual=hk[2],
        note_prompt=args.note_prompt,
        double_click_ms=args.double_click_ms,
        record_urls=args.record_urls,
        keep_query=args.keep_query,
        record_clipboard=args.record_clipboard,
        dry_run=args.dry_run,
        as_json=args.json,
        control=args.control,
        element_names=not args.no_element_names,
        voice=args.voice,
        voice_model=args.voice_model,
        voice_language=args.voice_language,
        keep_audio=args.keep_audio,
    )
    if args.voice:
        from stepcap import voice

        gone = voice.missing()
        if "sounddevice" in gone:
            _err(f"--voice needs the microphone library: {voice.install_hint()}")
            return EXIT_FAIL
        if gone:
            _err(
                f"warning: speech-to-text is not installed ({', '.join(gone)}); the audio is kept "
                f"and can be transcribed later with `stepcap transcribe`. {voice.install_hint()}"
            )
    try:
        result = record(opts)
    except (RecorderError, SessionError) as exc:
        _err(str(exc))
        if args.control:
            from stepcap.capture.recorder import emit_status

            emit_status("error", message=str(exc))
        return EXIT_FAIL
    if args.json:
        _print_json(result)
    return EXIT_OK if result.get("ok", True) else EXIT_FAIL


# ---------------------------------------------------------------------------- build
def cmd_build(args: argparse.Namespace) -> int:
    from stepcap.build.pipeline import BuildOptions, parse_formats, run_build

    try:
        opts = BuildOptions(
            formats=parse_formats(args.formats),
            zoom=args.zoom,
            width=args.width or None,
            lang=args.lang,
            title=args.title,
            image_format=args.image_format,
            quality=args.quality,
            reset=args.reset,
            dry_run=args.dry_run,
            marker=args.marker,
            spotlight=args.spotlight,
            auto_arrows=args.auto_arrows,
        )
        res = run_build(Path(args.session), opts)
    except (SessionError, ValueError) as exc:
        _err(str(exc))
        return EXIT_FAIL
    if args.json:
        _print_json(res.to_dict())
        return EXIT_OK
    for w in res.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.dry_run:
        print(
            f"[dry-run] {res.steps} steps; would write: {', '.join(res.outputs)} "
            f"(steps.json: {res.steps_json})"
        )
        return EXIT_OK
    reuse = f", {res.reused_screenshots} reused screenshot(s)" if res.reused_screenshots else ""
    print(
        f"Built {res.steps} steps{reuse} in {res.session} "
        f"({len(res.written)} written, {len(res.unchanged)} unchanged; "
        f"steps.json {res.steps_json})"
    )
    for o in res.outputs:
        print(f"  {Path(res.session) / o}")
    return EXIT_OK


# ---------------------------------------------------------------------------- edit
def cmd_edit(args: argparse.Namespace) -> int:
    from stepcap.edit.server import serve

    try:
        return serve(
            Path(args.session), host=args.host, port=args.port, open_browser=not args.no_browser
        )
    except (SessionError, OSError) as exc:
        _err(str(exc))
        return EXIT_FAIL


# ---------------------------------------------------------------------------- simulate
def cmd_simulate(args: argparse.Namespace) -> int:
    from stepcap.simulate import load_spec, simulate

    try:
        spec = load_spec(Path(args.events))
        if args.dry_run:
            res = {"dry_run": True, "events_in": len(spec["events"]), "session": args.output}
        else:
            res = simulate(
                spec,
                Path(args.output),
                record_typing=args.record_typing,
                exclude_apps=tuple(args.exclude_app or ()),
                record_urls=args.record_urls,
                keep_query=args.keep_query,
                record_clipboard=args.record_clipboard,
            )
    except SessionError as exc:
        _err(str(exc))
        return EXIT_FAIL
    if args.json:
        _print_json(res)
    elif args.dry_run:
        print(f"[dry-run] {res['events_in']} scripted events -> {args.output}")
    else:
        print(
            f"Simulated session {res['session']}: {res['events']} events, "
            f"{res['screenshots']} screenshots"
        )
        print(f"Next: stepcap build {res['session']}")
    return EXIT_OK


# ---------------------------------------------------------------------------- skill
def _skill_options(args: argparse.Namespace, out_dir: Path):
    from stepcap.skill.run import SkillOptions

    return SkillOptions(
        out_dir=out_dir,
        name=args.name,
        agent=args.agent,
        install=getattr(args, "install", "none"),
        scope=getattr(args, "scope", "user"),
        force=args.force,
        yes=args.yes,
        dry_run=args.dry_run,
    )


def _print_skill(res: dict[str, Any], prefix: str = "") -> None:
    if res["dry_run"]:
        print(f"{prefix}[dry-run] skill {res['name']!r} -> {res['skill_dir']}")
        for f in res["files"]:
            print(f"{prefix}  would write {f}")
        if res["agent"] != "none":
            print(f"{prefix}  {res['agent']} would be able to read (secrets masked):")
            for f in res["shared_files"]:
                print(f"{prefix}    {f}")
            print(f"{prefix}  command: {shlex.join(res['agent_command'])}")
        if res["installed_to"]:
            print(f"{prefix}  would install to {res['installed_to']}")
        return
    info = res.get("info") or {}
    print(
        f"{prefix}Skill {res['name']!r}: {res['steps']} steps -> {res['skill_dir']} "
        f"({info.get('lines', '?')} lines, ~{info.get('tokens', '?')} tokens)"
    )
    for problem in res["problems"]:
        print(f"{prefix}  INVALID: {problem}", file=sys.stderr)
    if res["agent"] != "none":  # the draft always covers the recording; a rewrite may not
        _print_coverage(info.get("coverage") or {}, prefix)
    if res["installed_to"]:
        print(f"{prefix}  installed to {res['installed_to']}")
    elif res["ok"]:
        print(f"{prefix}  valid (Agent Skills spec + no secrets)")


def cmd_skill(args: argparse.Namespace) -> int:
    from stepcap.skill.run import SkillError, ask, run_skill

    try:
        res = run_skill(Path(args.session), _skill_options(args, Path(args.output)), ask)
    except (SkillError, SessionError, ValueError) as exc:
        _err(str(exc))
        return EXIT_FAIL
    data = res.to_dict()
    if args.json:
        _print_json(data)
    else:
        _print_skill(data)
    return EXIT_OK if res.ok else EXIT_FAIL


def cmd_export(args: argparse.Namespace) -> int:
    from stepcap.build.pipeline import BuildOptions
    from stepcap.skill.run import SkillError, ask, run_export

    out = Path(args.output)
    try:
        res = run_export(
            Path(args.session),
            args.format,
            out,
            _skill_options(args, out / "skill"),
            BuildOptions(lang=args.lang),
            ask,
        )
    except (SkillError, SessionError, ValueError) as exc:
        _err(str(exc))
        return EXIT_FAIL
    data = res.to_dict()
    if args.json:
        _print_json(data)
        return EXIT_OK if res.ok else EXIT_FAIL
    if res.guide_dir:
        tag = "[dry-run] would write" if res.dry_run else "Guide"
        print(f"{tag} {res.guide_dir}: {len(res.guide_files)} files")
    if res.skill:
        _print_skill(res.skill)
    return EXIT_OK if res.ok else EXIT_FAIL


def cmd_shell(args: argparse.Namespace) -> int:
    from stepcap.shell import run_shell

    try:
        res = run_shell(Path(args.session), args.shell)
    except SessionError as exc:
        _err(str(exc))
        return EXIT_FAIL
    if args.json:
        _print_json(res)
    return EXIT_OK


def _print_coverage(cov: dict[str, Any], prefix: str = "") -> None:
    if not cov.get("total"):
        return
    print(
        f"{prefix}  recording coverage: {cov['found']}/{cov['total']} "
        f"({cov['score']:.0%} of apps, elements, inputs, URLs, commands and notes mentioned)"
    )
    for item in cov["items"]:
        if not item["found"]:
            where = f" (step {', '.join(map(str, item['steps']))})" if item["steps"] else ""
            print(f"{prefix}    not mentioned: {item['kind']} {item['value']!r}{where}")


def cmd_check_skill(args: argparse.Namespace) -> int:
    from stepcap.skill import coverage
    from stepcap.skill.validate import validate_skill

    problems, info = validate_skill(Path(args.skill_dir))
    cov = None
    if args.session and not problems:
        try:
            cov = coverage.check_dir(Path(args.skill_dir), Path(args.session)).to_dict()
        except (SessionError, OSError, ValueError) as exc:
            _err(str(exc))
            return EXIT_FAIL
    low = cov is not None and args.min_coverage is not None and cov["score"] < args.min_coverage
    if args.json:
        data = {"skill_dir": args.skill_dir, "ok": not problems and not low, "problems": problems}
        data.update(info)
        if cov is not None:
            data["coverage"] = cov
        _print_json(data)
    elif problems:
        for problem in problems:
            print(f"INVALID: {problem}", file=sys.stderr)
    else:
        print(
            f"{args.skill_dir}: valid ({info.get('lines')} lines, ~{info.get('tokens')} tokens, "
            f"{info.get('links')} local links)"
        )
        if cov is not None:
            _print_coverage(cov)
        if low:
            print(
                f"coverage {cov['score']:.0%} is below --min-coverage {args.min_coverage:.0%}",
                file=sys.stderr,
            )
    return EXIT_FAIL if problems or low else EXIT_OK


def cmd_agents(args: argparse.Namespace) -> int:
    from stepcap.skill import registry

    path = registry.config_path()
    try:
        specs = registry.load()
    except registry.RegistryError as exc:
        _err(str(exc))
        return EXIT_FAIL
    rows = []
    for spec in specs.values():
        rows.append(
            {
                "name": spec.name,
                "label": spec.label,
                "user_dir": spec.user_dir,
                "project_dir": spec.project_dir,
                "also_read_by": list(spec.readers),
                "refine": list(spec.refine),
                "refine_cli_found": spec.executable() if spec.can_refine else None,
                "source": spec.source,
            }
        )
    if args.json:
        _print_json({"config": str(path), "config_exists": path.is_file(), "agents": rows})
        return EXIT_OK
    for r in rows:
        where = r["user_dir"] or "-"
        readers = f" (also {', '.join(r['also_read_by'])})" if r["also_read_by"] else ""
        if r["refine"]:
            found = "found" if r["refine_cli_found"] else "not installed"
            refine = f"--agent {r['name']}: {r['refine'][0]} {found}"
        else:
            refine = "install only"
        print(f"{r['name']:<8} {r['label']:<28} {where}{readers}; {refine}")
    state = "" if path.is_file() else " (not present; create it to add agents)"
    print(f"\nConfig: {path}{state}")
    return EXIT_OK


def cmd_transcribe(args: argparse.Namespace) -> int:
    from stepcap.voice import VoiceError, transcribe_session

    try:
        res = transcribe_session(Path(args.session), args.model, args.language, args.keep_audio)
    except (VoiceError, SessionError, OSError, RuntimeError, ValueError) as exc:
        _err(str(exc))
        return EXIT_FAIL
    if args.json:
        _print_json(res)
    else:
        print(f"{res['segments']} voice notes ({res['language'] or '?'}) -> {args.session}")
        for line in res["lines"]:
            print(f"  {line['ts']:>7.1f}s  {line['text']}")
    return EXIT_OK


def cmd_mcp(args: argparse.Namespace) -> int:
    from stepcap.mcp_server import ToolError, serve

    try:
        serve([Path(r) for r in args.root] if args.root else None)
    except ToolError as exc:
        _err(str(exc))
        return EXIT_FAIL
    return EXIT_OK


def cmd_schema(args: argparse.Namespace) -> int:
    from stepcap import schemas

    if args.path:
        print(schemas.path(args.name) if args.name else schemas.DIR)
        return EXIT_OK
    names = [args.name] if args.name else list(schemas.NAMES)
    if len(names) == 1:
        _print_json(schemas.load(names[0]))
    else:
        _print_json({n: schemas.load(n) for n in names})
    return EXIT_OK


# ---------------------------------------------------------------------------- app
def cmd_app(args: argparse.Namespace) -> int:
    try:
        from stepcap.gui.app import main as app_main
    except ImportError as exc:  # tkinter is optional on some Linux Pythons
        _err(
            f"the window needs tkinter ({exc}). Install it (e.g. sudo apt install python3-tk) "
            "or use the release binary; the command line works without it."
        )
        return EXIT_FAIL
    return app_main(args.lang)


# ---------------------------------------------------------------------------- doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    from stepcap import doctor

    return doctor.run(as_json=args.json)


# ---------------------------------------------------------------------------- parser
def _positive_int(v: str) -> int:
    n = int(v)
    if n <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return n


def _fraction(value: str) -> float:
    try:
        f = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a number between 0 and 1") from None
    if not 0 <= f <= 1:
        raise argparse.ArgumentTypeError("must be a number between 0 and 1")
    return f


def _skill_args(k: argparse.ArgumentParser) -> None:
    k.add_argument(
        "--name",
        help="skill name: a-z, 0-9 and hyphens (default: from the guide title or app name)",
    )
    k.add_argument(
        "--agent",
        default="none",
        metavar="AGENT",
        help="none: deterministic draft, no LLM (default). claude / codex / gemini or an agent "
        "from agents.toml: let your own agent CLI rewrite the draft into a general skill (asks "
        "first; stepcap itself sends nothing). See `stepcap agents`",
    )
    k.add_argument("--yes", action="store_true", help="do not ask before running the agent")
    k.add_argument("--force", action="store_true", help="replace existing output folders")
    k.add_argument("--dry-run", action="store_true", help="show what would be written / shared")
    k.add_argument("--json", action="store_true", help="machine-readable summary")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stepcap",
        description="Record desktop clicks once; get a step-by-step guide for people and an "
        "Agent Skill (SKILL.md) for any agent. Local: no cloud, no account, no network.",
    )
    p.add_argument("--version", action="version", version=f"stepcap {__version__}")
    sub = p.add_subparsers(dest="command", metavar="COMMAND")

    r = sub.add_parser("record", help="record clicks, drags, scrolls and typing")
    r.add_argument(
        "-o",
        "--output",
        metavar="SESSION_DIR",
        help="new session directory (default: ./stepcap-YYYYmmdd-HHMMSS)",
    )
    r.add_argument(
        "--monitor",
        choices=("active", "all"),
        default="active",
        help="capture the monitor under the cursor (default) or all monitors",
    )
    r.add_argument(
        "--record-typing",
        action="store_true",
        help="store typed text (default: only the number of characters). "
        "Always masked in password / login windows.",
    )
    r.add_argument(
        "--exclude-app",
        nargs="+",
        metavar="NAME",
        action="extend",
        help="never record (no screenshot) while an app/window whose name contains "
        "NAME is in front. Repeatable.",
    )
    r.add_argument("--hotkey-stop", default="F9", metavar="KEY", help="default: F9")
    r.add_argument("--hotkey-pause", default="F8", metavar="KEY", help="pause/resume (default: F8)")
    r.add_argument(
        "--hotkey-manual",
        default="F7",
        metavar="KEY",
        help="add a manual step with a note (default: F7)",
    )
    r.add_argument(
        "--note-prompt",
        choices=("auto", "gui", "terminal", "none"),
        default="auto",
        help="how F7 asks for the note (default: auto = dialog if available)",
    )
    r.add_argument(
        "--double-click-ms",
        type=_positive_int,
        default=150,
        metavar="MS",
        help="max gap between the two clicks of a double-click (default: 150)",
    )
    r.add_argument(
        "--record-urls",
        action="store_true",
        help="record the front browser tab's URL when it changes (Windows: Chrome, Edge, "
        "Firefox, Brave, Vivaldi, Opera via UI Automation; macOS: Safari, Chrome, Edge, Arc, "
        "asks for the Automation permission; not on Linux yet). Query strings are dropped.",
    )
    r.add_argument(
        "--keep-query",
        action="store_true",
        help="with --record-urls: keep ?query (token/password parameters are still masked)",
    )
    r.add_argument(
        "--record-clipboard",
        action="store_true",
        help="record copied text: length and the first 80 characters, secrets masked; "
        "nothing while a password/login window or an --exclude-app is in front",
    )
    r.add_argument(
        "--voice",
        action="store_true",
        help="record the microphone for voice notes and transcribe them on this computer "
        '(needs pip install "stepcap[voice]"; the speech model is downloaded once)',
    )
    r.add_argument(
        "--voice-model",
        default="base",
        choices=("tiny", "base", "small", "medium", "large-v3"),
        help="speech model size (default base; small is better for Japanese, slower)",
    )
    r.add_argument("--voice-language", metavar="LANG", help="e.g. ja or en (default: detect)")
    r.add_argument(
        "--keep-audio",
        action="store_true",
        help="keep audio.wav after transcribing (deleted by default)",
    )
    r.add_argument(
        "--dry-run", action="store_true", help="check permissions/hooks and exit without recording"
    )
    r.add_argument("--json", action="store_true", help="print a JSON summary when done")
    r.add_argument(
        "--no-element-names",
        action="store_true",
        help="do not ask the OS for the clicked element's name and frame "
        "(Windows UI Automation / macOS Accessibility); steps are then titled from the "
        "window name",
    )
    r.add_argument(
        "--control",
        action="store_true",
        help=argparse.SUPPRESS,  # JSON-lines protocol used by `stepcap app`
    )
    r.set_defaults(func=cmd_record)

    b = sub.add_parser("build", help="generate guide.md / guide.html / steps.json")
    b.add_argument("session", metavar="SESSION_DIR")
    b.add_argument(
        "-f",
        "--formats",
        default="md,html,checklist",
        help="comma list of md, html, checklist (printable A4 tick list); default: all three",
    )
    b.add_argument(
        "--zoom",
        type=_positive_int,
        metavar="PX",
        help="use a PX-wide crop around the click as main image + full thumbnail",
    )
    b.add_argument(
        "--width",
        type=int,
        default=1600,
        metavar="PX",
        help="max image width in the guide (default: 1600, 0 = original)",
    )
    b.add_argument("--lang", choices=("en", "ja"), help="language of automatic texts")
    b.add_argument("--title", help="guide title (saved to steps.json)")
    b.add_argument(
        "--image-format",
        choices=("webp", "jpeg", "png"),
        default="webp",
        help="image format for the guide (default: webp)",
    )
    b.add_argument("--quality", type=int, default=85, help="webp/jpeg quality 1-100 (default 85)")
    b.add_argument(
        "--marker",
        choices=("box", "ring"),
        help="box: frame the clicked button/field when it can be detected, else a ring "
        "(default); ring: always a ring. Saved in steps.json.",
    )
    b.add_argument(
        "--spotlight",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="dim everything except the clicked element (default: off). Saved in steps.json.",
    )
    b.add_argument(
        "--auto-arrows",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="add an arrow pointing at small targets such as checkboxes (default: on). "
        "Saved in steps.json.",
    )
    b.add_argument(
        "--reset",
        action="store_true",
        help="discard steps.json edits and recreate it from the recording",
    )
    b.add_argument("--dry-run", action="store_true", help="show what would be written")
    b.add_argument("--json", action="store_true", help="machine-readable summary")
    b.set_defaults(func=cmd_build)

    e = sub.add_parser("edit", help="local web UI: reorder, delete, rename, blur, rebuild")
    e.add_argument("session", metavar="SESSION_DIR")
    e.add_argument("--port", type=int, default=8765)
    e.add_argument(
        "--host",
        default="127.0.0.1",
        help="bind address (default 127.0.0.1; anything else prints a warning)",
    )
    e.add_argument("--no-browser", action="store_true", help="do not open a browser")
    e.set_defaults(func=cmd_edit)

    s = sub.add_parser("simulate", help="create a session from synthetic events (tests/demos)")
    s.add_argument("events", metavar="EVENTS.json")
    s.add_argument("-o", "--output", required=True, metavar="SESSION_DIR")
    s.add_argument("--record-typing", action="store_true")
    s.add_argument("--exclude-app", nargs="+", metavar="NAME", action="extend")
    s.add_argument("--record-urls", action="store_true", help="use each screen's 'url'")
    s.add_argument("--keep-query", action="store_true")
    s.add_argument("--record-clipboard", action="store_true", help="replay 'copy' events")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_simulate)

    k = sub.add_parser(
        "skill",
        help="write an Agent Skill (SKILL.md + references/) for Claude Code, Codex or any agent",
    )
    k.add_argument("session", metavar="SESSION_DIR")
    k.add_argument(
        "-o",
        "--output",
        required=True,
        metavar="OUT_DIR",
        help="parent folder; the skill is written to OUT_DIR/<name>/",
    )
    _skill_args(k)
    k.add_argument(
        "--install",
        default="none",
        metavar="AGENT",
        help="also copy the skill to where an agent loads skills from: claude (.claude/skills), "
        "agents (.agents/skills: Codex, Gemini CLI, Cursor), codex, gemini, cursor or an agent "
        "from agents.toml. See `stepcap agents`",
    )
    k.add_argument(
        "--scope",
        choices=("user", "project"),
        default="user",
        help="with --install: your home folder (user, default) or the current folder (project)",
    )
    k.set_defaults(func=cmd_skill)

    x = sub.add_parser("export", help="write the guide (for people) and/or the skill (for agents)")
    x.add_argument("session", metavar="SESSION_DIR")
    x.add_argument(
        "--format",
        choices=("guide", "skill", "both"),
        default="both",
        help="guide -> OUT_DIR/guide/, skill -> OUT_DIR/skill/<name>/ (default: both)",
    )
    x.add_argument("-o", "--output", required=True, metavar="OUT_DIR")
    x.add_argument("--lang", choices=("en", "ja"), help="language of automatic guide texts")
    _skill_args(x)
    x.set_defaults(func=cmd_export)

    h = sub.add_parser(
        "shell",
        help="open bash/zsh whose commands are added to a session (macOS/Linux)",
    )
    h.add_argument("session", metavar="SESSION_DIR", help="a session being (or already) recorded")
    h.add_argument("--shell", help="bash or zsh (default: $SHELL, else bash, else zsh)")
    h.add_argument("--json", action="store_true", help="print a JSON summary when the shell exits")
    h.set_defaults(func=cmd_shell)

    c = sub.add_parser(
        "check-skill",
        help="validate a skill folder (Agent Skills spec, links, size, secret patterns)",
    )
    c.add_argument("skill_dir", metavar="SKILL_DIR")
    c.add_argument(
        "--session",
        metavar="SESSION_DIR",
        help="also list what the recording showed but SKILL.md no longer mentions (apps, "
        "clicked elements, inputs, URLs, commands, notes)",
    )
    c.add_argument(
        "--min-coverage",
        type=_fraction,
        metavar="0-1",
        help="with --session: exit 1 if less than this share is mentioned (e.g. 0.8)",
    )
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_check_skill)

    t = sub.add_parser(
        "transcribe",
        help="turn a session's recorded audio (record --voice) into voice notes, locally",
    )
    t.add_argument("session", metavar="SESSION_DIR")
    t.add_argument(
        "--model", default="base", choices=("tiny", "base", "small", "medium", "large-v3")
    )
    t.add_argument("--language", metavar="LANG", help="e.g. ja or en (default: detect)")
    t.add_argument("--keep-audio", action="store_true", help="keep audio.wav afterwards")
    t.add_argument("--json", action="store_true")
    t.set_defaults(func=cmd_transcribe)

    m = sub.add_parser(
        "mcp",
        help="run an MCP server (stdio) so agents can read recordings and write skills",
    )
    m.add_argument(
        "--root",
        action="append",
        metavar="DIR",
        help="folder the agent may use (repeatable; default: ~/Documents/stepcap and the "
        "current folder)",
    )
    m.set_defaults(func=cmd_mcp)

    g = sub.add_parser(
        "agents",
        help="list the agents stepcap can install skills for or run (built-in + agents.toml)",
    )
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=cmd_agents)

    from stepcap.schemas import NAMES as schema_names

    j = sub.add_parser(
        "schema",
        help="print the JSON Schema of a session file (session, event, steps, terminal, voice)",
    )
    j.add_argument("name", nargs="?", choices=schema_names)
    j.add_argument("--path", action="store_true", help="print the schema file path instead")
    j.set_defaults(func=cmd_schema)

    a = sub.add_parser("app", help="open the stepcap window: start / stop recordings, edit, export")
    a.add_argument("--lang", choices=("en", "ja"), help="window language (default: system)")
    a.set_defaults(func=cmd_app)

    d = sub.add_parser("doctor", help="check permissions, hooks and screen capture")
    d.add_argument("--json", action="store_true")
    d.set_defaults(func=cmd_doctor)
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        # never crash on a cp932 / ascii console
        with contextlib.suppress(AttributeError, ValueError):
            stream.reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        if argv is None and getattr(sys, "frozen", False) and len(sys.argv) == 1:
            # the release binary was double-clicked: open the window
            return cmd_app(argparse.Namespace(lang=None))
        parser.print_help()
        print("\nTip: `stepcap app` opens a window to record without the terminal.")
        return EXIT_USAGE
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _err("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
