"""Write the license texts of every distribution bundled into the binaries.

    python scripts/collect_licenses.py out/THIRD_PARTY_LICENSES.txt [--extra voice]

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


def extra_names(dist: metadata.Distribution, extra: str) -> list[str]:
    """Requirements that only the ``extra`` (e.g. voice) adds."""
    names = []
    for req in dist.requires or []:
        if ";" in req and re.search(rf"extra\s*==\s*['\"]{re.escape(extra)}['\"]", req):
            names.append(re.split(r"[\s;<>=!~\[(]", req, maxsplit=1)[0])
    return names


def walk(root: str, extras: tuple[str, ...] = ()) -> list[metadata.Distribution]:
    seen: dict[str, metadata.Distribution] = {}
    todo = [root]
    for extra in extras:
        todo += extra_names(metadata.distribution(root), extra)
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
    args = sys.argv[1:]
    extras: tuple[str, ...] = ()
    if "--extra" in args:
        i = args.index("--extra")
        extras = (args[i + 1],)
        del args[i : i + 2]
    out = Path(args[0] if args else "THIRD_PARTY_LICENSES.txt")
    parts = [
        "Third-party software bundled in the stepcap binary.\n"
        "LGPL components (pynput, python-xlib) are included unmodified; their source is\n"
        "available on PyPI. You may replace them by installing stepcap from PyPI instead.\n"
    ]
    if "voice" in extras:
        parts.append(
            "The voice edition also bundles PyAV, whose wheels contain FFmpeg libraries\n"
            "(LGPL-2.1-or-later, shipped as shared libraries in av.libs / av/.dylibs); the\n"
            "FFmpeg source is available from https://ffmpeg.org and the PyAV project.\n"
        )
    for dist in walk("stepcap", extras):
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
