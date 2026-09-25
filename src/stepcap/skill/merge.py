"""One skill from several recordings of the same task (RM-068).

The first recording is the base: its steps, screenshots and wording make the skill.
Every other recording is aligned with it the same way `stepcap diff` does (in order, by
what each step did). The draft then says

- which base steps were done in only some recordings (optional steps),
- which values were typed into the same field in each recording (real examples of an
  input instead of one),
- which steps other recordings did that the base did not (listed with their position).

No step is invented and none is dropped: the base run stays the reference, the other
runs only add what varies.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stepcap import diff
from stepcap.build.steps import STEP_KINDS


@dataclass
class Extra:
    recording: int  # 2, 3, ... (1 is the base)
    after: int  # base step number it came after (0 = before the first step)
    step: dict[str, Any]


@dataclass
class Variants:
    sources: list[str]  # folder names, base first
    seen: dict[str, int] = field(default_factory=dict)  # base step id -> recordings with it
    values: dict[str, list[str]] = field(default_factory=dict)  # base step id -> typed values
    extra: list[Extra] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.sources)


def _steps(doc: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in doc["steps"] if s.get("kind") in STEP_KINDS]


def analyse(
    base: tuple[Path, dict[str, Any], list[dict[str, Any]]],
    others: list[tuple[Path, dict[str, Any], list[dict[str, Any]]]],
) -> Variants:
    """``base`` / ``others`` are (session folder, steps.json, redacted events)."""
    path_a, doc_a, ev_a = base
    sa = _steps(doc_a)
    ka = [diff.key(s) for s in sa]
    typed_a = diff.typed_values(ev_a)
    v = Variants([Path(path_a).name] + [Path(p).name for p, _, _ in others])
    v.seen = {s["id"]: 1 for s in sa}
    for s in sa:
        if s.get("kind") == "type" and s.get("event_id") in typed_a:
            v.values[s["id"]] = [typed_a[s["event_id"]]]
    for n, (_, doc_b, ev_b) in enumerate(others, 2):
        sb = _steps(doc_b)
        kb = [diff.key(s) for s in sb]
        typed_b = diff.typed_values(ev_b)
        matcher = difflib.SequenceMatcher(a=ka, b=kb, autojunk=False)
        for op, i1, i2, j1, j2 in matcher.get_opcodes():
            if op == "equal":
                for i, j in zip(range(i1, i2), range(j1, j2), strict=True):
                    v.seen[sa[i]["id"]] += 1
                    text = typed_b.get(sb[j].get("event_id"))
                    if sa[i].get("kind") == "type" and text is not None:
                        v.values.setdefault(sa[i]["id"], []).append(text)
            elif op in ("insert", "replace"):
                v.extra += [Extra(n, i1, sb[j]) for j in range(j1, j2)]
    return v
