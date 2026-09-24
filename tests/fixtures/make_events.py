"""Print a demo EVENTS.json for `stepcap simulate`.

    python tests/fixtures/make_events.py > ev.json
    stepcap simulate ev.json -o demo

The scenario ("create a project in a task app") covers every step kind:
click, double-click, right-click, typing, key, drag, scroll and a manual note,
plus consecutive clicks on the same screen (screenshot reuse).
"""

from __future__ import annotations

import json
import sys

APP = "Acme Tasks"
SIDEBAR = ["Inbox", "Projects", "Reports", "Settings"]


def _board(card1_rect, card1_badge):
    return {
        "app": APP,
        "window_title": "Board - Acme Tasks",
        "sidebar": SIDEBAR,
        "sidebar_active": "Projects",
        "heading": "Q3 launch plan",
        "widgets": [
            {"type": "column", "id": "todo", "rect": [272, 140, 360, 600], "label": "To do"},
            {"type": "column", "id": "doing", "rect": [652, 140, 360, 600], "label": "In progress"},
            {"type": "column", "id": "done", "rect": [1032, 140, 360, 600], "label": "Done"},
            {
                "type": "card",
                "id": "c2",
                "rect": [288, 302, 328, 96],
                "label": "Book venue",
                "badge": "To do",
            },
            {
                "type": "card",
                "id": "c3",
                "rect": [288, 414, 328, 96],
                "label": "Collect quotes",
                "badge": "To do",
            },
            {
                "type": "card",
                "id": "c4",
                "rect": [1048, 190, 328, 96],
                "label": "Kickoff meeting",
                "badge": "Done",
            },
            {
                "type": "card",
                "id": "c1",
                "rect": card1_rect,
                "label": "Draft brief",
                "badge": card1_badge,
            },
        ],
    }


def make_events() -> dict:
    home = {
        "app": APP,
        "window_title": "Projects - Acme Tasks",
        "sidebar": SIDEBAR,
        "sidebar_active": "Projects",
        "heading": "Projects",
        "widgets": [
            {
                "type": "button",
                "id": "new",
                "label": "+ New project",
                "rect": [1220, 60, 188, 44],
                "primary": True,
            },
            {
                "type": "input",
                "id": "search",
                "placeholder": "Search projects",
                "rect": [272, 150, 360, 44],
            },
            {
                "type": "list",
                "id": "projects",
                "rect": [272, 214, 1136, 520],
                "items": [
                    "Website redesign",
                    "Q2 onboarding",
                    "Hiring pipeline",
                    "Office move",
                    "Customer survey",
                ],
            },
        ],
    }
    dialog = {
        "base": "home",
        "app": APP,
        "window_title": "New project - Acme Tasks",
        "dialog": {"title": "New project", "rect": [420, 190, 600, 480]},
        "widgets": [
            {
                "type": "input",
                "id": "name",
                "label": "Project name",
                "placeholder": "e.g. Q3 launch plan",
                "rect": [448, 300, 544, 48],
            },
            {
                "type": "select",
                "id": "template",
                "label": "Template",
                "value": "Kanban board",
                "rect": [448, 400, 544, 48],
            },
            {
                "type": "checkbox",
                "id": "private",
                "label": "Private project",
                "rect": [448, 480, 24, 24],
            },
            {"type": "button", "id": "cancel", "label": "Cancel", "rect": [700, 596, 140, 44]},
            {
                "type": "button",
                "id": "create",
                "label": "Create",
                "rect": [852, 596, 140, 44],
                "primary": True,
            },
        ],
    }
    board = _board([288, 190, 328, 96], "To do")
    board_menu = {
        "base": "board",
        "app": APP,
        "window_title": board["window_title"],
        "widgets": [
            {
                "type": "menu",
                "id": "menu",
                "rect": [470, 250, 210, 148],
                "items": ["Rename", "Move to...", "Duplicate", "Delete"],
            },
        ],
    }
    board_moved = _board([668, 190, 328, 96], "In progress")

    return {
        "title": "Create a project and move a card in Acme Tasks",
        "screen": {"width": 1440, "height": 900},
        "screens": {
            "home": home,
            "dialog": dialog,
            "board": board,
            "board_menu": board_menu,
            "board_moved": board_moved,
        },
        "events": [
            {"kind": "click", "screen": "home", "target": "new"},
            {"kind": "click", "screen": "dialog", "target": "name"},
            {"kind": "type", "screen": "dialog", "target": "name", "text": "Q3 launch plan"},
            {"kind": "click", "screen": "dialog", "target": "private"},
            {"kind": "click", "screen": "dialog", "target": "create"},
            {"kind": "double_click", "screen": "board", "target": "c2"},
            {"kind": "right_click", "screen": "board", "target": "c1"},
            {"kind": "key", "screen": "board_menu", "keys": "esc", "target": "c1"},
            {"kind": "drag", "screen": "board", "from": "c1", "to": [830, 238]},
            {"kind": "scroll", "screen": "board_moved", "target": "done", "dy": -3},
            {"kind": "key", "screen": "board_moved", "keys": "ctrl+s", "target": "doing"},
            {
                "kind": "manual",
                "screen": "board_moved",
                "note": "Check that the card shows “In progress”\n"
                "The card moves to the In progress column and the team is notified.",
            },
        ],
    }


if __name__ == "__main__":
    json.dump(make_events(), sys.stdout, ensure_ascii=True, indent=2)  # ASCII: safe on any console
    sys.stdout.write("\n")
