"""checklist.html: a printable A4 checklist of the steps.

One compact row per step (tick box, number, a small crop around the target,
title, description, notes column) plus date / operator / location fields and
a sign-off line, so it can be printed and ticked on site. Single file, no
external requests, same data as guide.html.
"""

from __future__ import annotations

from html import escape
from typing import Any

from stepcap.build import naming
from stepcap.build.html import data_uri

THUMB_WIDTH = 300  # px, about 5 cm when printed
THUMB_ZOOM = 720  # source px around the target shown in the thumbnail

CSS = """
:root{--fg:#15171b;--muted:#5d6370;--line:#c9cdd4;--accent:#e8401a;--bg:#fff;color-scheme:light}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:12pt/1.45 system-ui,-apple-system,
"Segoe UI",Roboto,"Hiragino Sans","Yu Gothic UI","Noto Sans JP",sans-serif}
.page{max-width:190mm;margin:0 auto;padding:12mm 0 16mm}
@media screen{.page{padding:24px 16px 48px}}
header h1{font-size:18pt;line-height:1.25;margin:0 0 2pt}
header .meta{color:var(--muted);font-size:9pt;margin:0 0 8pt}
.fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6pt 14pt;margin:0 0 10pt}
.field{display:flex;gap:6pt;align-items:flex-end;font-size:10pt;white-space:nowrap}
.field span{flex:1;border-bottom:1px solid var(--fg);min-height:14pt}
table{width:100%;border-collapse:collapse;table-layout:fixed}
th{white-space:nowrap;font-size:9pt;color:var(--muted);text-align:left;font-weight:600;border-bottom:1.5pt solid var(--fg);
padding:3pt 4pt}
td{border-bottom:1px solid var(--line);padding:5pt 4pt;vertical-align:top}
tr{break-inside:avoid;page-break-inside:avoid}
col.c-box{width:13mm}col.c-num{width:9mm}col.c-img{width:52mm}col.c-notes{width:30mm}
.box{display:inline-block;width:5.5mm;height:5.5mm;border:1.5pt solid var(--fg);border-radius:1mm}
.num{font-weight:700;color:var(--accent)}
td img{display:block;width:100%;height:auto;border:1px solid var(--line);border-radius:2pt}
.title{font-weight:600;margin:0}
.desc{margin:2pt 0 0;color:var(--muted);font-size:10pt;white-space:pre-line}
.win{margin:2pt 0 0;color:var(--muted);font-size:8.5pt;overflow-wrap:anywhere}
footer{margin-top:12pt;display:flex;justify-content:space-between;gap:16pt;font-size:10pt}
footer .field{flex:1}
.print{margin:0 0 10pt}
.print button{font:inherit;font-size:10pt;padding:4pt 10pt;border:1px solid var(--line);
background:#f6f7f9;border-radius:4pt;cursor:pointer}
@media print{.print{display:none}.page{padding:0}@page{size:A4;margin:12mm}}
@media (max-width:600px){.fields{grid-template-columns:1fr}col.c-img{width:30%}col.c-notes{width:0}
.notes,.notes-h{display:none}}
"""


def render(doc: dict[str, Any], thumbs: list[dict[str, Any]], meta_line: str, version: str) -> str:
    lang = doc.get("lang", "en")
    t = lambda key, **kw: escape(naming.text(lang, key, **kw))  # noqa: E731
    title = doc.get("title") or naming.text(lang, "default_title")
    rows = []
    for n, (step, th) in enumerate(zip(doc["steps"], thumbs, strict=True), 1):
        img = ""
        if th.get("bytes"):
            w, h = th["size"]
            img = (
                f'<img src="{data_uri(th["bytes"], th["mime"])}" width="{w}" height="{h}" '
                f'alt="{escape(naming.heading(n, step.get("title") or "", lang))}">'
            )
        desc = (step.get("description") or "").strip()
        win = step.get("window_title") or step.get("app_name")
        if win and win in (step.get("title") or ""):
            win = None  # the automatic title already names the window
        rows.append(
            "<tr>"
            '<td><span class="box" role="img" aria-label="□"></span></td>'
            f'<td class="num">{n}</td>'
            f"<td>{img}</td>"
            f'<td><p class="title">{escape(step.get("title") or "")}</p>'
            + (f'<p class="desc">{escape(desc)}</p>' if desc else "")
            + (f'<p class="win">{escape(win)}</p>' if win else "")
            + '</td><td class="notes"></td></tr>'
        )
    return f"""<!doctype html>
<html lang="{escape(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="stepcap {escape(version)}">
<title>{escape(title)} — {t("checklist")}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page">
<p class="print"><button type="button" onclick="window.print()">{t("cl_print")}</button></p>
<header><h1>{escape(title)}</h1><p class="meta">{t("checklist")} · {escape(meta_line)}</p></header>
<div class="fields">
<div class="field">{t("cl_date")}<span></span></div>
<div class="field">{t("cl_operator")}<span></span></div>
<div class="field">{t("cl_place")}<span></span></div>
</div>
<table>
<colgroup><col class="c-box"><col class="c-num"><col class="c-img"><col><col class="c-notes"></colgroup>
<thead><tr><th>{t("cl_done")}</th><th>#</th><th></th><th>{t("cl_step")}</th><th class="notes-h">{t("cl_notes")}</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
<footer><div class="field">{t("cl_checked_by")}<span></span></div><div class="field">{t("cl_date")}<span></span></div></footer>
</div>
</body>
</html>
"""
