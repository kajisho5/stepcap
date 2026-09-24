"""SKILL.md must follow the Agent Skills spec (agentskills.io/specification)."""

import re
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "stepcap" / "SKILL.md"


def frontmatter():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    block = text.split("---\n", 2)[1]
    fields = {}
    for line in block.splitlines():
        m = re.match(r"^([a-z][a-z0-9_-]*):\s*(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2)
    return fields


def test_frontmatter():
    f = frontmatter()
    assert f["name"] == SKILL.parent.name == "stepcap"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", f["name"]) and len(f["name"]) <= 64
    assert 1 <= len(f["description"]) <= 1024
    assert len(f.get("compatibility", "")) <= 500
    assert len(SKILL.read_text(encoding="utf-8").splitlines()) < 500
