"""JSON Schemas (draft 2020-12) of the files in a session folder.

- ``session``:  session.json (metadata of one recording)
- ``event``:    one line of events.jsonl
- ``steps``:    steps.json (the editable guide)
- ``terminal``: one line of terminal.jsonl (`stepcap shell`)

They document the format for other tools; stepcap itself does not need a
validator at run time. Unknown keys are allowed so newer versions can add fields.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NAMES = ("session", "event", "steps", "terminal")
DIR = Path(__file__).parent


def path(name: str) -> Path:
    if name not in NAMES:
        raise ValueError(f"unknown schema {name!r}; use one of {', '.join(NAMES)}")
    return DIR / f"{name}.schema.json"


def load(name: str) -> dict[str, Any]:
    return json.loads(path(name).read_text(encoding="utf-8"))
