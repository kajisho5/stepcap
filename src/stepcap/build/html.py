"""guide.html: one self-contained file (images inlined as base64).

Includes a table of contents, light/dark themes (follows the OS, with a
toggle) and print CSS, so "Print > Save as PDF" is the v0.1 PDF path.
No external requests of any kind.
"""

from __future__ import annotations

import base64
from html import escape
from typing import Any

from stepcap.build import naming

CSS = """
:root{--bg:#ffffff;--fg:#1b1d22;--muted:#5d6370;--line:#e3e5ea;--card:#f7f8fa;
--accent:#e8401a;--accent-fg:#ffffff;--shadow:0 1px 2px rgba(0,0,0,.06),0 4px 16px rgba(0,0,0,.06);
color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15171b;--fg:#e8eaee;
--muted:#9aa1ad;--line:#2b2f37;--card:#1d2026;--accent:#ff6a3d;--accent-fg:#15171b;
--shadow:0 1px 2px rgba(0,0,0,.4);color-scheme:dark}}
:root[data-theme="dark"]{--bg:#15171b;--fg:#e8eaee;--muted:#9aa1ad;--line:#2b2f37;--card:#1d2026;
--accent:#ff6a3d;--accent-fg:#15171b;--shadow:0 1px 2px rgba(0,0,0,.4);color-scheme:dark}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.6 system-ui,-apple-system,
"Segoe UI",Roboto,"Hiragino Sans","Yu Gothic UI","Noto Sans JP",sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:24px 16px 64px;display:grid;
grid-template-columns:minmax(0,1fr);gap:24px}
@media (min-width:1000px){.wrap{grid-template-columns:260px minmax(0,1fr)}
.toc{position:sticky;top:16px;align-self:start;max-height:calc(100vh - 32px);overflow:auto}}
header.top{grid-column:1/-1;display:flex;gap:16px;align-items:flex-start;
justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:16px}
h1{font-size:1.9rem;line-height:1.25;margin:0 0 4px}
.meta{color:var(--muted);margin:0;font-size:.9rem}
button.theme{border:1px solid var(--line);background:var(--card);color:var(--fg);
border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit;font-size:.85rem}
.toc{border:1px solid var(--line);border-radius:12px;padding:12px 14px;background:var(--card)}
.toc h2{font-size:.8rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
margin:0 0 8px}
.toc ol{margin:0;padding-left:1.4em;font-size:.9rem}
.toc li{margin:2px 0}
.toc a{color:var(--fg);text-decoration:none}
.toc a:hover{color:var(--accent);text-decoration:underline}
.step{border:1px solid var(--line);border-radius:14px;padding:18px;margin:0 0 20px;
background:var(--bg);box-shadow:var(--shadow);scroll-margin-top:16px}
.step h2{display:flex;gap:12px;align-items:center;font-size:1.2rem;line-height:1.35;margin:0 0 8px}
.num{flex:none;display:inline-grid;place-items:center;min-width:2em;height:2em;padding:0 .5em;
border-radius:1em;background:var(--accent);color:var(--accent-fg);font-weight:700;font-size:.9rem}
.desc{margin:0 0 12px;white-space:pre-line}
figure{margin:0}
figure img{display:block;max-width:100%;height:auto;border-radius:8px;border:1px solid var(--line)}
figure.thumb{margin-top:10px;max-width:320px}
figcaption{color:var(--muted);font-size:.8rem;margin-top:6px;overflow-wrap:anywhere}
footer{grid-column:1/-1;color:var(--muted);font-size:.8rem;border-top:1px solid var(--line);
padding-top:12px}
@media print{
:root,:root[data-theme="dark"]{--bg:#fff;--fg:#000;--muted:#444;--line:#ccc;--card:#fff;
--accent:#e8401a;--accent-fg:#fff;--shadow:none;color-scheme:light}
body{font-size:11pt}
.wrap{display:block;max-width:none;padding:0}
button.theme{display:none}
.toc{position:static;max-height:none;border:none;padding:0;margin-bottom:12pt;
break-after:page}
.step{break-inside:avoid;page-break-inside:avoid;box-shadow:none;border:none;padding:0 0 12pt;
margin:0 0 12pt;border-bottom:1px solid var(--line);border-radius:0}
figure img{max-height:16cm;width:auto;object-fit:contain}
a{color:inherit;text-decoration:none}
}
"""

JS = """
(function(){var r=document.documentElement,b=document.getElementById('theme');
try{var s=localStorage.getItem('stepcap-theme');if(s)r.setAttribute('data-theme',s);}catch(e){}
if(!b)return;b.addEventListener('click',function(){
var cur=r.getAttribute('data-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
var next=cur==='dark'?'light':'dark';r.setAttribute('data-theme',next);
try{localStorage.setItem('stepcap-theme',next);}catch(e){}});})();
"""


def data_uri(data: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def render(doc: dict[str, Any], images: list[dict[str, Any]], meta_line: str, version: str) -> str:
    lang = doc.get("lang", "en")
    title = doc.get("title") or naming.text(lang, "default_title")
    toc, sections = [], []
    for n, (step, img) in enumerate(zip(doc["steps"], images, strict=True), 1):
        st_title = step.get("title") or ""
        toc.append(f'<li><a href="#step-{n}">{escape(st_title)}</a></li>')
        parts = [
            f'<section class="step" id="step-{n}">',
            f'<h2><span class="num">{n}</span><span>{escape(st_title)}</span></h2>',
        ]
        desc = (step.get("description") or "").strip()
        if desc:
            parts.append(f'<p class="desc">{escape(desc)}</p>')
        alt = escape(naming.heading(n, st_title, lang))
        if img.get("main_bytes"):
            w, h = img["main_size"]
            parts.append(
                f'<figure><img src="{data_uri(img["main_bytes"], img["mime"])}" alt="{alt}" '
                f'width="{w}" height="{h}" loading="lazy">'
            )
            win = step.get("window_title") or step.get("app_name")
            if win:
                parts.append(
                    f"<figcaption>{escape(naming.text(lang, 'window'))}: {escape(win)}</figcaption>"
                )
            parts.append("</figure>")
        if img.get("thumb_bytes"):
            w, h = img["thumb_size"]
            label = escape(naming.text(lang, "full_screen"))
            parts.append(
                f'<figure class="thumb"><img src="{data_uri(img["thumb_bytes"], img["mime"])}" '
                f'alt="{label} ({n})" width="{w}" height="{h}" loading="lazy">'
                f"<figcaption>{label}</figcaption></figure>"
            )
        parts.append("</section>")
        sections.append("\n".join(parts))

    return f"""<!doctype html>
<html lang="{escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="stepcap {escape(version)}">
<title>{escape(title)}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header class="top"><div><h1>{escape(title)}</h1><p class="meta">{escape(meta_line)}</p></div>
<button class="theme" id="theme" type="button" aria-label="{escape(naming.text(lang, "toggle_theme"))}">◐</button></header>
<nav class="toc" aria-label="{escape(naming.text(lang, "contents"))}"><h2>{escape(naming.text(lang, "contents"))}</h2><ol>
{chr(10).join(toc)}
</ol></nav>
<main>
{chr(10).join(sections)}
</main>
<footer>{escape(naming.text(lang, "generated", version=version))}</footer>
</div>
<script>{JS}</script>
</body>
</html>
"""
