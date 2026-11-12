"""Load a recording for skill work: meta, steps.json and redacted events.

Kept apart from ``run`` so that ``coverage`` (used by ``run``) can load a
recording without importing ``run`` (no import cycle).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from stepcap.build.pipeline import BuildOptions, BuildResult, load_or_create_steps
from stepcap.redact import redact_obj
from stepcap.session import STEPS_FILE, load_session, write_json


def load_recording(
    session: Path, dry_run: bool = False, warnings: list[str] | None = None
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """(session meta, steps.json, redacted events) - creates steps.json if needed.

    Screenshots not checked yet are read for secrets on screen and blurred, except with
    ``dry_run``; the build's warnings (e.g. screenshots not checked) go to ``warnings``.
    """
    built = BuildResult("", 0)
    meta, doc = load_or_create_steps(session, BuildOptions(dry_run=dry_run), built)
    if warnings is not None:
        warnings.extend(built.warnings)
    write_json(session / STEPS_FILE, doc)  # keep migrations / first-time steps.json
    _, events = load_session(session)
    return meta, doc, [redact_obj(ev) for ev in events]
