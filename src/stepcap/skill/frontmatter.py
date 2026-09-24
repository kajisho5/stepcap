"""Read and write the YAML frontmatter of a SKILL.md without a YAML dependency.

Supports what Agent Skills use: ``key: value`` pairs (plain, "double" or
'single' quoted), folded / literal block scalars (``>`` / ``|``) and one level
of nested mapping (``metadata:``). Anything else is reported as an error
rather than guessed.
"""

from __future__ import annotations

import json
import re
from typing import Any

_KEY = re.compile(r"^([A-Za-z0-9_-]+):(?:\s+(.*))?$")


class FrontmatterError(ValueError):
    pass


def quote(value: str) -> str:
    """A YAML double-quoted scalar (JSON strings are valid YAML)."""
    return json.dumps(value, ensure_ascii=False)


def dump(fields: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            lines += [f"  {k}: {quote(str(v))}" for k, v in value.items()]
        else:
            lines.append(f"{key}: {quote(str(value))}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _scalar(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise FrontmatterError(f"bad double-quoted value {raw!r}") from exc
        if not isinstance(value, str):
            raise FrontmatterError(f"bad double-quoted value {raw!r}")
        return value
    if raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'"):
            raise FrontmatterError(f"bad single-quoted value {raw!r}")
        return raw[1:-1].replace("''", "'")
    return re.sub(r"\s+#.*$", "", raw)


def split(text: str) -> tuple[list[str], str]:
    """Return (frontmatter lines, body)."""
    text = text.lstrip("﻿").replace("\r\n", "\n")
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise FrontmatterError("SKILL.md must start with a '---' frontmatter line")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], "\n".join(lines[i + 1 :])
    raise FrontmatterError("frontmatter is not closed with '---'")


def parse(text: str) -> tuple[dict[str, Any], str]:
    block, body = split(text)
    fields: dict[str, Any] = {}
    i = 0
    while i < len(block):
        line = block[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[0] in " \t":
            raise FrontmatterError(f"unexpected indentation: {line.strip()!r}")
        m = _KEY.match(line.rstrip())
        if not m:
            raise FrontmatterError(f"cannot read line {line.strip()!r}")
        key, raw = m.group(1), (m.group(2) or "").strip()
        i += 1
        children = []
        while i < len(block) and (not block[i].strip() or block[i][0] in " \t"):
            children.append(block[i])
            i += 1
        if raw in (">", "|", ">-", "|-", ">+", "|+"):
            parts = [c.strip() for c in children]
            joiner = " " if raw.startswith(">") else "\n"
            fields[key] = joiner.join(p for p in parts if p or joiner == "\n").strip()
        elif raw:
            if any(c.strip() for c in children):
                raise FrontmatterError(f"{key}: unexpected indented lines after a value")
            fields[key] = _scalar(raw)
        else:
            nested: dict[str, str] = {}
            for c in children:
                if not c.strip():
                    continue
                cm = _KEY.match(c.strip())
                if not cm:
                    raise FrontmatterError(f"{key}: cannot read {c.strip()!r}")
                nested[cm.group(1)] = _scalar(cm.group(2) or "")
            fields[key] = nested
    return fields, body
