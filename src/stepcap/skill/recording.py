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
    session: Path,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """(session meta, steps.json, redacted events) - creates steps.json if needed."""
    meta, doc = load_or_create_steps(session, BuildOptions(), BuildResult("", 0))
    write_json(session / STEPS_FILE, doc)  # keep migrations / first-time steps.json
    _, events = load_session(session)
    return meta, doc, [redact_obj(ev) for ev in events]
