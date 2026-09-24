"""Command line interface."""

from __future__ import annotations

import argparse
import contextlib
import json
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
        dry_run=args.dry_run,
        as_json=args.json,
    )
    try:
        result = record(opts)
    except (RecorderError, SessionError) as exc:
        _err(str(exc))
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stepcap",
        description="Record desktop clicks and turn them into step-by-step guides. "
        "Local only: no cloud, no account, no network.",
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
        "--dry-run", action="store_true", help="check permissions/hooks and exit without recording"
    )
    r.add_argument("--json", action="store_true", help="print a JSON summary when done")
    r.set_defaults(func=cmd_record)

    b = sub.add_parser("build", help="generate guide.md / guide.html / steps.json")
    b.add_argument("session", metavar="SESSION_DIR")
    b.add_argument("-f", "--formats", default="md,html", help="comma list of md,html")
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
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_simulate)

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
        parser.print_help()
        return EXIT_USAGE
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _err("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
