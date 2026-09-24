"""Check a skill folder against the Agent Skills spec and stepcap's own rules.

Spec: https://agentskills.io/specification (name / description limits, name
must equal the folder name, SKILL.md < 500 lines, body < ~5000 tokens).
stepcap adds: every relative link resolves inside the folder, and no text file
contains a secret pattern (see ``stepcap.redact``).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from stepcap.redact import leak_kinds
from stepcap.skill import frontmatter

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_LINES = 500  # "Keep your main SKILL.md under 500 lines"
MAX_TOKENS = 5000  # "< 5000 tokens recommended" for the body
TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".csv", ".html", ".sh", ".py"}
_LINK = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_SRC = re.compile(r"""\b(?:src|href)\s*=\s*["']([^"']+)["']""")


def estimate_tokens(text: str) -> int:
    """Rough upper estimate: ~4 ASCII characters per token, 1 token per other character."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return ascii_chars // 4 + (len(text) - ascii_chars)


def _local_links(body: str) -> list[str]:
    out = []
    for m in [*_LINK.finditer(body), *_SRC.finditer(body)]:
        target = m.group(1).split("#", 1)[0]
        if not target or re.match(r"^[a-z][a-z0-9+.\-]*:", target, re.I) or target.startswith("/"):
            continue
        out.append(target)
    return out


def validate_skill(skill_dir: Path) -> tuple[list[str], dict[str, Any]]:
    """Return (problems, info). No problems = valid."""
    skill_dir = Path(skill_dir)
    problems: list[str] = []
    info: dict[str, Any] = {}
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return [f"{md} does not exist"], info
    text = md.read_text(encoding="utf-8")
    try:
        fields, body = frontmatter.parse(text)
    except frontmatter.FrontmatterError as exc:
        return [f"SKILL.md frontmatter: {exc}"], info

    name = fields.get("name")
    info["name"] = name
    if not isinstance(name, str) or not name:
        problems.append("frontmatter: 'name' is missing")
    else:
        if len(name) > MAX_NAME or not NAME_RE.match(name):
            problems.append(
                f"frontmatter: name {name!r} must be 1-{MAX_NAME} characters of a-z, 0-9 and "
                "single hyphens, not starting or ending with a hyphen"
            )
        if name != skill_dir.name:
            problems.append(
                f"frontmatter: name {name!r} must equal the folder name {skill_dir.name!r}"
            )
    desc = fields.get("description")
    if not isinstance(desc, str) or not desc.strip():
        problems.append("frontmatter: 'description' is missing or empty")
    elif len(desc) > MAX_DESCRIPTION:
        problems.append(
            f"frontmatter: description is {len(desc)} characters (max {MAX_DESCRIPTION})"
        )
    comp = fields.get("compatibility")
    if comp is not None and (not isinstance(comp, str) or not 1 <= len(comp) <= MAX_COMPATIBILITY):
        problems.append(f"frontmatter: compatibility must be 1-{MAX_COMPATIBILITY} characters")
    if "metadata" in fields and not isinstance(fields["metadata"], dict):
        problems.append("frontmatter: metadata must be a mapping")

    lines = len(text.splitlines())
    tokens = estimate_tokens(body)
    info.update(lines=lines, tokens=tokens)
    if lines >= MAX_LINES:
        problems.append(f"SKILL.md has {lines} lines (keep it under {MAX_LINES})")
    if tokens > MAX_TOKENS:
        problems.append(f"SKILL.md body is about {tokens} tokens (keep it under {MAX_TOKENS})")

    root = skill_dir.resolve()
    links = _local_links(body)
    info["links"] = len(links)
    for target in links:
        p = (skill_dir / target).resolve()
        if root not in p.parents and p != root:
            problems.append(f"link {target!r} points outside the skill folder")
        elif not p.exists():
            problems.append(f"link {target!r} does not exist")

    for f in sorted(skill_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in TEXT_SUFFIXES:
            try:
                content = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            kinds = leak_kinds(content)
            if kinds:
                rel = f.relative_to(skill_dir).as_posix()
                problems.append(f"{rel} contains a secret ({', '.join(sorted(set(kinds)))})")
    return problems, info
