"""Machine-readable contract (`stepcap contract --json`), in the shape the AI Video Production OS
registry reads (skill_id, version, contract_version, provides, dependencies, not_provided)."""

from __future__ import annotations

from typing import Any

from stepcap import __version__, schemas

SKILL_ID = "stepcap"
CONTRACT_VERSION = "1.0"

TOOLS = [
    {
        "tool_id": "stepcap/build",
        "description": "Generate guide.md / guide.html / checklist and steps.json from a recording",
        "argv": ["build", "<session_dir>", "[-f md,html,checklist]", "[--lang en|ja]", "--json"],
        "writes": ["guide.md", "guide.html", "checklist.html", "steps.json"],
    },
    {
        "tool_id": "stepcap/skill",
        "description": "Draft an Agent Skill (SKILL.md + references/) from one or more recordings",
        "argv": [
            "skill",
            "<session_dir>",
            "[<session_dir> ...]",
            "-o",
            "<out_dir>",
            "[--agent none]",
            "--json",
        ],
        "writes": ["<out_dir>/<name>/SKILL.md", "<out_dir>/<name>/references/"],
    },
]


def contract() -> dict[str, Any]:
    return {
        "skill_id": SKILL_ID,
        "id": SKILL_ID,
        "version": __version__,
        "contract_version": CONTRACT_VERSION,
        "provides": [
            {"id": "guide.build", "lifecycle": "EXPERIMENTAL", "tool_id": "stepcap/build"},
            {"id": "skill.draft", "lifecycle": "EXPERIMENTAL", "tool_id": "stepcap/skill"},
        ],
        # No Skill dependencies: recording, OCR and voice notes are local libraries.
        "dependencies": [],
        "not_provided": [
            "video export of a guide (planned, through ffmpeg-skill)",
            "editing or encoding video",
            "network access (an --agent rewrite runs your own agent CLI, after asking)",
        ],
        "tools": TOOLS,
        "schemas": list(schemas.NAMES),
        "execution": {
            "canonical_invocation": ["stepcap", "<command>", "...", "--json"],
            "network": False,
            "exit_codes": {"ok": 0, "fail": 1, "usage": 2},
        },
    }
