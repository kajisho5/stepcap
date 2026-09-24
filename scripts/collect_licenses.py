"""Write the license texts of every distribution bundled into the binaries.

    python scripts/collect_licenses.py out/THIRD_PARTY_LICENSES.txt

Uses the installed dist-info metadata of stepcap's runtime dependency tree, so it
matches exactly what PyInstaller bundled on this OS.
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

LICENSE_NAME = re.compile(r"(^|/)(LICEN[CS]E|COPYING|NOTICE)[^/]*$", re.IGNORECASE)


def requirement_names(dist: metadata.Distribution) -> list[str]:
    names = []
    for req in dist.requires or []:
        if "extra ==" in req:
            continue
        name = re.split(r"[\s;<>=!~\[(]", req, maxsplit=1)[0]
        marker = req.split(";", 1)[1] if ";" in req else ""
        if marker and not _marker_ok(marker):
            continue
        names.append(name)
    return names


def _marker_ok(marker: str) -> bool:
    try:
        from packaging.markers import Marker

        return Marker(marker).evaluate()
    except Exception:
        plat = sys.platform
        m = marker.replace(" ", "")
        if "sys_platform==" in m:
            return f'sys_platform=="{plat}"' in m or f"sys_platform=='{plat}'" in m
        if "insys_platform" in m:
            return "linux" in plat if '"linux"' in m or "'linux'" in m else True
        return 'python_version=="2.7"' not in m


def walk(root: str) -> list[metadata.Distribution]:
    seen: dict[str, metadata.Distribution] = {}
    todo = [root]
    while todo:
        name = todo.pop()
        key = name.lower().replace("_", "-")
        if key in seen:
            continue
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        seen[key] = dist
        todo += requirement_names(dist)
    return [seen[k] for k in sorted(seen)]


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "THIRD_PARTY_LICENSES.txt")
    parts = [
        "Third-party software bundled in the stepcap binary.\n"
        "LGPL components (pynput, python-xlib) are included unmodified; their source is\n"
        "available on PyPI. You may replace them by installing stepcap from PyPI instead.\n"
    ]
    for dist in walk("stepcap"):
        name, version = dist.metadata["Name"], dist.version
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        lic = lic.splitlines()[0] if lic else "see text below"
        parts.append(f"\n{'=' * 78}\n{name} {version} — {lic}\n{'=' * 78}\n")
        files = [f for f in dist.files or [] if LICENSE_NAME.search(str(f))]
        for f in files:
            try:
                parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}\n")
            except (OSError, UnicodeDecodeError):
                continue
        if not files:
            parts.append("(no license file in the distribution metadata)\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(parts), encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
