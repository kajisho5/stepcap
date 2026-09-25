"""`stepcap share`: a password-protected copy of guide.html (or checklist.html).

The whole page is encrypted with AES-256-GCM; the key is derived from the
password with PBKDF2-HMAC-SHA256 (600,000 iterations, random 16-byte salt).
The output is still one self-contained HTML file: it shows a password field
and decrypts in the browser with the standard WebCrypto API, so it works
offline and needs no server. Wrong passwords fail the GCM authentication.

There is deliberately no "expires on" option: a standalone file cannot enforce
it (anyone could edit the date out). Share the password over another channel.
"""

from __future__ import annotations

import base64
import html
import os
from pathlib import Path

ITERATIONS = 600_000  # OWASP (2023) recommendation for PBKDF2-HMAC-SHA256
SALT_BYTES = 16
NONCE_BYTES = 12
MIN_PASSWORD = 8
MARKER = "stepcap-protected-v1"


class ShareError(Exception):
    pass


def _key(password: str, salt: bytes, iterations: int = ITERATIONS) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def encrypt(page: str, password: str) -> dict[str, str | int]:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(password) < MIN_PASSWORD:
        raise ShareError(f"use a password of at least {MIN_PASSWORD} characters")
    salt, nonce = os.urandom(SALT_BYTES), os.urandom(NONCE_BYTES)
    data = AESGCM(_key(password, salt)).encrypt(nonce, page.encode("utf-8"), MARKER.encode())
    b64 = lambda b: base64.b64encode(b).decode("ascii")  # noqa: E731
    return {"salt": b64(salt), "iv": b64(nonce), "data": b64(data), "iter": ITERATIONS}


def decrypt(blob: dict[str, str | int], password: str) -> str:
    """For tests and for recovering a page with Python."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    raw = {k: base64.b64decode(str(blob[k])) for k in ("salt", "iv", "data")}
    key = _key(password, raw["salt"], int(blob["iter"]))
    try:
        plain = AESGCM(key).decrypt(raw["iv"], raw["data"], MARKER.encode())
    except Exception as exc:  # cryptography.exceptions.InvalidTag
        raise ShareError("wrong password or damaged file") from exc
    return plain.decode("utf-8")


TEXTS = {
    "en": {
        "title": "Protected guide",
        "prompt": "This guide is password protected.",
        "label": "Password",
        "open": "Open",
        "wrong": "Wrong password.",
        "nocrypto": "This browser cannot decrypt the page (WebCrypto is not available).",
    },
    "ja": {
        "title": "保護された手順書",
        "prompt": "この手順書はパスワードで保護されています。",
        "label": "パスワード",
        "open": "開く",
        "wrong": "パスワードが違います。",
        "nocrypto": "このブラウザではページを復号できません（WebCrypto が使えません）。",
    },
}

_PAGE = """<!doctype html>
<html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="stepcap share ({marker})">
<title>{title}</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;margin:0;min-height:100vh;display:grid;place-items:center;
background:#f4f5f7;color:#222}}
@media (prefers-color-scheme:dark){{body{{background:#16181c;color:#eee}}
input{{background:#23262b;color:#eee;border-color:#444}}}}
form{{max-width:22rem;padding:1.5rem}}input{{font:inherit;padding:.5rem;width:100%;box-sizing:border-box;
border:1px solid #bbb;border-radius:6px}}
button{{font:inherit;margin-top:.75rem;padding:.5rem 1.25rem}}
#err{{color:#c33;min-height:1.5em}}
</style></head><body>
<form id="f"><p>{prompt}</p><label>{label}<br>
<input id="pw" type="password" autocomplete="current-password" autofocus required></label>
<button type="submit">{open}</button><p id="err" role="alert"></p></form>
<script id="payload" type="application/json">{payload}</script>
<script>
(function () {{
  const P = JSON.parse(document.getElementById("payload").textContent);
  const b = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const err = document.getElementById("err");
  document.getElementById("f").addEventListener("submit", async function (e) {{
    e.preventDefault();
    if (!window.crypto || !crypto.subtle) {{ err.textContent = {nocrypto}; return; }}
    const pw = new TextEncoder().encode(document.getElementById("pw").value);
    try {{
      const base = await crypto.subtle.importKey("raw", pw, "PBKDF2", false, ["deriveKey"]);
      const key = await crypto.subtle.deriveKey(
        {{ name: "PBKDF2", salt: b(P.salt), iterations: P.iter, hash: "SHA-256" }},
        base, {{ name: "AES-GCM", length: 256 }}, false, ["decrypt"]);
      const plain = await crypto.subtle.decrypt(
        {{ name: "AES-GCM", iv: b(P.iv), additionalData: new TextEncoder().encode("{marker}") }},
        key, b(P.data));
      const page = new TextDecoder().decode(plain);
      document.open(); document.write(page); document.close();
    }} catch (x) {{ err.textContent = {wrong}; }}
  }});
}})();
</script></body></html>
"""


def protect(page: str, password: str, lang: str = "en") -> str:
    import json

    t = TEXTS.get(lang, TEXTS["en"])
    payload = json.dumps(encrypt(page, password)).replace("</", "<\\/")
    return _PAGE.format(
        lang=lang,
        marker=MARKER,
        title=html.escape(t["title"]),
        prompt=html.escape(t["prompt"]),
        label=html.escape(t["label"]),
        open=html.escape(t["open"]),
        payload=payload,
        wrong=json.dumps(t["wrong"]),
        nocrypto=json.dumps(t["nocrypto"]),
    )


def share(
    session: Path, out: Path, password: str, which: str = "guide", lang: str | None = None
) -> Path:
    """Build if needed, then write the protected copy of guide.html / checklist.html."""
    from stepcap.build.pipeline import CHECKLIST_HTML, GUIDE_HTML, BuildOptions, run_build
    from stepcap.session import read_json

    session, out = Path(session), Path(out)
    name = {"guide": GUIDE_HTML, "checklist": CHECKLIST_HTML}.get(which)
    if name is None:
        raise ShareError("which must be guide or checklist")
    if not (session / name).is_file():
        run_build(session, BuildOptions(lang=lang))
    if lang is None:
        steps = session / "steps.json"
        lang = (read_json(steps).get("lang") if steps.is_file() else None) or "en"
    if out.resolve() == (session / name).resolve():
        raise ShareError("write the protected copy to another file, not over the original")
    page = (session / name).read_text(encoding="utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(protect(page, password, lang), encoding="utf-8")
    return out
