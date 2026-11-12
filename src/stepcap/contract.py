"""Machine-readable contract (`stepcap contract --json`), in the shape the AI Video Production OS
registry reads (skill_id, version, contract_version, provides, dependencies, not_provided)."""

from __future__ import annotations

from typing import Any

from stepcap import __version__, schemas, video
from stepcap.build import screen_blur

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
    {
        "tool_id": "stepcap/video",
        "description": "How-to MP4 from a recording: each step's guide image with its text burned "
        "in as a caption, through ffmpeg-skill (sequence, caption, then its check)",
        "argv": [
            "video",
            "<session_dir>",
            "[-o FILE.mp4]",
            "[--seconds 4]",
            "[--size 1920x1080]",
            "[--platform youtube]",
            "[--ffmpeg-skill DIR]",
            "--json",
        ],
        "writes": ["guide.mp4 (or -o)", "steps.json", "images/"],
        "requires": "ffmpeg-skill (optional dependency; exit 1 with a dependency error without it)",
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
            {"id": "guide.video", "lifecycle": "EXPERIMENTAL", "tool_id": "stepcap/video"},
        ],
        # Recording, OCR names and voice notes are local libraries; `stepcap video` delegates
        # to ffmpeg-skill and the on-screen secret check of every build to detection-skill.
        "dependencies": [
            {
                "skill_id": "ffmpeg-skill",
                "version_range": video.CONTRACT_RANGE,
                "range_of": "contract_version",
                "required": False,
                "used_by": ["stepcap/video"],
                "tools": [f"ffmpeg-skill/{t}" for t in video.TOOLS_USED],
                "located_by": ["--ffmpeg-skill"]
                + [f"${e}" for e in video.ENV_DIRS]
                + ["~/.claude/skills/ffmpeg-skill", "./vendor/ffmpeg-skill", "../ffmpeg-skill"],
            },
            {
                "skill_id": "detection-skill",
                "version_range": screen_blur.CONTRACT_RANGE,
                "range_of": "contract_version",
                "required": False,
                "used_by": ["stepcap/build", "stepcap/skill", "stepcap/video"],
                "tools": [f"detection/{t}" for t in screen_blur.TOOLS_USED],
                "purpose": "find passwords, API keys and tokens shown in screenshots, to blur "
                "them before export (skipped with a warning without it; build --no-secret-scan)",
                "located_by": [f"${screen_blur.ENV_COMMAND}", "detection on PATH"],
            },
        ],
        "not_provided": [
            "editing or encoding video itself (stepcap video delegates it to ffmpeg-skill)",
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
