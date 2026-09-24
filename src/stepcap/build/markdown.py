"""guide.md: plain CommonMark that pastes into GitHub, Notion and Confluence."""

from __future__ import annotations

import re
from typing import Any

from stepcap.build import naming

_MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|])")


def escape(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", text)


def escape_line_start(text: str) -> str:
    # Avoid turning a description line into a heading / list / quote by accident.
    return re.sub(r"^(\s*)([#>+\-]|\d+\.)", r"\1\\\2", text)


def render(doc: dict[str, Any], images: list[dict[str, Any]], meta_line: str) -> str:
    lang = doc.get("lang", "en")
    out = [
        f"# {escape(doc.get('title') or naming.text(lang, 'default_title'))}",
        "",
        f"_{escape(meta_line)}_",
        "",
    ]
    for n, (step, img) in enumerate(zip(doc["steps"], images, strict=True), 1):
        out.append(f"## {escape(naming.heading(n, step.get('title') or '', lang))}")
        out.append("")
        desc = (step.get("description") or "").strip()
        if desc:
            for line in desc.splitlines():
                out.append(escape_line_start(escape(line)) + "  " if line.strip() else "")
            out[-1] = out[-1].rstrip()
            out.append("")
        if img.get("main"):
            alt = escape(naming.heading(n, step.get("title") or "", lang))
            out.append(f"![{alt}]({img['main']})")
            out.append("")
        if img.get("thumb"):
            alt = escape(f"{naming.text(lang, 'full_screen')} ({n})")
            out.append(f"![{alt}]({img['thumb']})")
            out.append("")
    return "\n".join(out).rstrip() + "\n"
