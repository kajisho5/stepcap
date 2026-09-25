"""Create a GitHub issue (label `roadmap`) for every `planned` row in ROADMAP.md.

The plan is ROADMAP.md itself; issues are opened only for items under discussion, so
by default this script only lists what it would create. `--create` really creates
them (rows whose "RM-NNN" already appears in an issue title, open or closed, are
skipped). Needs the GitHub CLI (`gh auth login`) for --create.

    python scripts/roadmap_to_issues.py              # list only (same as --dry-run)
    python scripts/roadmap_to_issues.py --create     # create the missing issues
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROADMAP_URL = "https://github.com/kajisho5/stepcap/blob/main/ROADMAP.md"
ROW = re.compile(r"^\|\s*(RM-\d{3})\s*\|\s*(\w[\w-]*)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$")


def planned_rows(path: Path) -> list[tuple[str, str, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = ROW.match(line)
        if m and m.group(2) == "planned":
            rows.append((m.group(1), m.group(3), m.group(4)))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="list only (the default)")
    ap.add_argument("--create", action="store_true", help="really create the issues")
    ap.add_argument("--roadmap", default=str(Path(__file__).resolve().parents[1] / "ROADMAP.md"))
    args = ap.parse_args()
    args.dry_run = args.dry_run or not args.create
    rows = planned_rows(Path(args.roadmap))
    existing = set()
    if not args.dry_run:
        subprocess.run(
            [
                "gh",
                "label",
                "create",
                "roadmap",
                "--color",
                "5319e7",
                "--description",
                "Planned work from ROADMAP.md",
                "--force",
            ],
            check=True,
        )
        out = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "--label",
                "roadmap",
                "--state",
                "all",
                "--limit",
                "500",
                "--json",
                "title",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        existing = {
            m.group(0) for t in json.loads(out) for m in [re.search(r"RM-\d{3}", t["title"])] if m
        }
    for rid, area, item in rows:
        title = f"[{rid}] {item}"
        if rid in existing:
            print(f"skip   {title}")
            continue
        body = (
            f"Roadmap item **{rid}** (area: `{area}`) from {ROADMAP_URL}.\n\n"
            "Status: planned. Discuss scope and approach here before opening a PR."
        )
        print(f"{'would create' if args.dry_run else 'create'} {title}")
        if not args.dry_run:
            subprocess.run(
                [
                    "gh",
                    "issue",
                    "create",
                    "--title",
                    title,
                    "--body",
                    body,
                    "--label",
                    "roadmap",
                ],
                check=True,
            )
    if args.dry_run:
        print("(nothing created; pass --create to open these issues)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
