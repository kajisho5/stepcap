"""Hotkey parsing and matching (pure logic, no OS hooks).

A hotkey spec is a ``+``-separated list: zero or more modifiers followed by one
key, e.g. ``F9``, ``ctrl+shift+s``, ``alt+F8``. Matching is case-insensitive.
"""

from __future__ import annotations

from dataclasses import dataclass

MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "alt": "alt",
    "option": "alt",
    "opt": "alt",
    "shift": "shift",
    "cmd": "cmd",
    "command": "cmd",
    "win": "cmd",
    "super": "cmd",
    "meta": "cmd",
}
KEY_ALIASES = {"escape": "esc", "return": "enter", "del": "delete", "spacebar": "space"}

NAMED_KEYS = frozenset(
    [
        "esc",
        "enter",
        "space",
        "tab",
        "delete",
        "insert",
        "home",
        "end",
        "page_up",
        "page_down",
        "pause",
        "scroll_lock",
        "print_screen",
    ]
)

DEFAULT_STOP = "F9"
DEFAULT_PAUSE = "F8"
DEFAULT_MANUAL = "F7"


class HotkeyError(ValueError):
    pass


@dataclass(frozen=True)
class Hotkey:
    key: str
    modifiers: frozenset[str] = frozenset()

    def matches(self, key: str, held_modifiers: set[str] | frozenset[str]) -> bool:
        return key.lower() == self.key and self.modifiers == frozenset(held_modifiers)

    def __str__(self) -> str:
        parts = [*sorted(self.modifiers), self.key]
        return "+".join(p.upper() if len(p) <= 3 and p.startswith("f") else p for p in parts)


def parse_hotkey(spec: str) -> Hotkey:
    tokens = [t.strip().strip("<>").lower() for t in spec.split("+")]
    if not tokens or any(not t for t in tokens):
        raise HotkeyError(f"invalid hotkey: {spec!r}")
    *mods, key = tokens
    modifiers = set()
    for m in mods:
        if m not in MODIFIER_ALIASES:
            raise HotkeyError(f"unknown modifier {m!r} in hotkey {spec!r}")
        modifiers.add(MODIFIER_ALIASES[m])
    if key in MODIFIER_ALIASES:
        raise HotkeyError(f"hotkey {spec!r} must end with a non-modifier key")
    key = KEY_ALIASES.get(key, key)
    is_fkey = key.startswith("f") and key[1:].isdigit()
    if len(key) > 1 and not is_fkey and key not in NAMED_KEYS:
        raise HotkeyError(f"unknown key {key!r} in hotkey {spec!r}")
    return Hotkey(key=key, modifiers=frozenset(modifiers))


def check_distinct(*hotkeys: Hotkey) -> None:
    if len(set(hotkeys)) != len(hotkeys):
        raise HotkeyError("stop / pause / manual hotkeys must all be different")
