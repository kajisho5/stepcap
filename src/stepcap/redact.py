"""Replace secrets in text with ``[REDACTED:kind]``.

Applied to every string stepcap saves (events.jsonl, and everything derived
from it) and checked again before a skill is written. It only sees text:
secrets visible in screenshots must be blurred in ``stepcap edit``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

_SENSITIVE_PARAMS = (
    "password|passwd|pwd|pass|token|access_token|refresh_token|id_token|auth|api_key|apikey"
    "|secret|client_secret|key|sig|signature"
)

# (kind, pattern). Order matters: specific prefixes before generic ones.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # distinctive prefixes: no word boundary needed (a token glued to text is still caught)
    ("github-token", re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})")),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^/\s:@]+):([^/\s@]+)@")
_URL_PARAM = re.compile(rf"(?i)([?&;#](?:{_SENSITIVE_PARAMS})=)([^&#;\s]+)")
_CARD = re.compile(r"(?<![\d.])\d(?:[ \-]?\d){12,18}(?![\d.])")
# A date and time such as stepcap's own folder names (20260925-055333): 14 digits that
# pass the Luhn check about one time in ten. 14-digit cards start with 30, 36 or 38.
_STAMP = re.compile(
    r"(?:19|20)\d\d(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[ \-]?(?:[01]\d|2[0-3])[0-5]\d[0-5]\d"
)


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _card(m: re.Match[str]) -> str:
    if _STAMP.fullmatch(m.group(0)):
        return m.group(0)
    digits = re.sub(r"\D", "", m.group(0))
    if 13 <= len(digits) <= 19 and luhn_ok(digits) and len(set(digits)) > 1:
        return "[REDACTED:card]"
    return m.group(0)


def redact_text(text: str) -> str:
    """Return ``text`` with every detected secret replaced."""
    if not text:
        return text
    out = text
    for kind, pat in PATTERNS:
        out = pat.sub(f"[REDACTED:{kind}]", out)
    out = _URL_USERINFO.sub(r"\1:[REDACTED:url-password]@", out)
    out = _URL_PARAM.sub(r"\1[REDACTED:url-param]", out)
    return _CARD.sub(_card, out)


def leak_kinds(text: str) -> list[str]:
    """Category labels (e.g. ``"github-token"``) of secrets still present in ``text``.

    Only the fixed labels from ``PATTERNS`` are returned, never the matched text,
    so the result is safe to print. Empty list = clean.
    """
    if not text:
        return []
    found = [kind for kind, pat in PATTERNS if pat.search(text)]
    if any(not m.group(2).startswith("[REDACTED") for m in _URL_USERINFO.finditer(text)):
        found.append("url-password")
    if any(not m.group(2).startswith("[REDACTED") for m in _URL_PARAM.finditer(text)):
        found.append("url-param")
    if any(_card(m) != m.group(0) for m in _CARD.finditer(text)):
        found.append("card")
    return found


# Keys whose values are identifiers/paths written by stepcap itself, never user text.
_SKIP_KEYS = frozenset({"screenshot", "kind", "click_type", "button", "direction", "image"})


def redact_obj(obj: Any, fn: Callable[[str], str] = redact_text) -> Any:
    """Recursively redact every string value of a JSON-like object."""
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, list):
        return [redact_obj(v, fn) for v in obj]
    if isinstance(obj, dict):
        return {k: (v if k in _SKIP_KEYS else redact_obj(v, fn)) for k, v in obj.items()}
    return obj
