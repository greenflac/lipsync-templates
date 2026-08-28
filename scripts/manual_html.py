"""Render docs/MANUAL_ru.md into the artifact page. The markdown stays the source."""

import html
import re
from pathlib import Path

SRC = Path("docs/MANUAL_ru.md")
DST = Path("build/manual.html")

CHIPS = {
    "ИЗМЕРЕНО": "measured",
    "РАСЧЁТ": "derived",
    "ВЫБРАНО": "chosen",
    "НЕПРОВЕРЕНО": "unverified",
    "DEBT": "debt",
}
VERDICTS = {
    "pass": "pass",
    "fail": "fail",
    "could not measure": "unmeasured",
}


def inline(text: str) -> str:
    out = html.escape(text)
    out = re.sub(r"`([^`]+)`", lambda m: f"<code>{m.group(1)}</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", lambda m: f"<strong>{m.group(1)}</strong>", out)
    out = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?!\*)", lambda m: f"<em>{m.group(1)}</em>", out)
    for word, cls in CHIPS.items():
        out = re.sub(
            rf"(?<!>){word}(?![^<]*</code>)",
            f'<span class="chip {cls}">{word}</span>',
            out,
        )
    for word, cls in VERDICTS.items():
        out = out.replace(f"<code>{word}</code>", f'<code class="v {cls}">{word}</code>')
    return out


def render(md: str) -> tuple[str, list]:
    lines = md.split("\n")
    body, toc = [], []
    i, n = 0, len(lines)
    sec = 0
    while i < n:
        ln = lines[i]
        if ln.startswith("```"):
            block = []
            i += 1
            while i < n and not lines[i].startswith("```"):
                block.append(html.escape(lines[i]))
                i += 1
            i += 1
            body.append(
                '<div class="scroll"><pre><code>' + "\n".join(block) + "</code></pre></div>"
            )
            continue
        if ln.strip() == "---":
            body.append("<hr />")
            i += 1
            continue
        if ln.startswith("# "):
            body.append(f"<h1>{inline(ln[2:])}</h1>")
            i += 1
            continue
        if ln.startswith("## "):
            sec += 1
            title = ln[3:]
            num, _, rest = title.partition(". ")
            slug = f"s{sec}"
            toc.append((num if num.isdigit() else "", rest or title, slug))
            label = f'<span class="num">{num}</span>' if num.isdigit() else ""
            body.append(f'<h2 id="{slug}">{label}<span>{inline(rest or title)}</span></h2>')
            i += 1
            continue
        if ln.startswith("### "):
            body.append(f"<h3>{inline(ln[4:])}</h3>")
            i += 1
            continue
        if ln.startswith("|"):
            rows = []
            while i < n and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            align = []
            if len(cells) > 1 and all(set(c) <= set("-: ") and c for c in cells[1]):
                for c in cells[1]:
                    align.append("right" if c.endswith(":") and not c.startswith(":") else "left")
                head, data = cells[0], cells[2:]
            else:
                head, data = cells[0], cells[1:]
                align = ["left"] * len(head)
            th = "".join(
                f'<th style="text-align:{align[k] if k < len(align) else "left"}">{inline(c)}</th>'
                for k, c in enumerate(head)
            )
            trs = []
            for row in data:
                tds = "".join(
                    f'<td style="text-align:{align[k] if k < len(align) else "left"}">{inline(c)}</td>'
                    for k, c in enumerate(row)
                )
                trs.append(f"<tr>{tds}</tr>")
            body.append(
                '<div class="scroll"><table><thead><tr>'
                + th
                + "</tr></thead><tbody>"
                + "".join(trs)
                + "</tbody></table></div>"
            )
            continue
        if re.match(r"^\s*[*-] ", ln):
            items, cur = [], []
            while i < n and (
                re.match(r"^\s*[*-] ", lines[i])
                or (cur and lines[i].startswith("  ") and lines[i].strip())
            ):
                if re.match(r"^\s*[*-] ", lines[i]):
                    if cur:
                        items.append(" ".join(cur))
                    cur = [re.sub(r"^\s*[*-] ", "", lines[i]).strip()]
                else:
                    cur.append(lines[i].strip())
                i += 1
            if cur:
                items.append(" ".join(cur))
            body.append("<ul>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ul>")
            continue
        if re.match(r"^\s*\d+\. ", ln):
            items, cur = [], []
            while i < n and (
                re.match(r"^\s*\d+\. ", lines[i])
                or (cur and lines[i].startswith("   ") and lines[i].strip())
            ):
                if re.match(r"^\s*\d+\. ", lines[i]):
                    if cur:
                        items.append(" ".join(cur))
                    cur = [re.sub(r"^\s*\d+\. ", "", lines[i]).strip()]
                else:
                    cur.append(lines[i].strip())
                i += 1
            if cur:
                items.append(" ".join(cur))
            body.append("<ol>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ol>")
            continue
        if not ln.strip():
            i += 1
            continue
        para = []
        while (
            i < n
            and lines[i].strip()
            and not re.match(r"^(#|\||```|\s*[*-] |\s*\d+\. |---$)", lines[i])
        ):
            para.append(lines[i].strip())
            i += 1
        body.append(f"<p>{inline(' '.join(para))}</p>")
    return "\n".join(body), toc


CSS = """
:root{
  --ground:#FAFAF8; --panel:#FFFFFF; --ink:#151A1D; --ink-soft:#4A555C;
  --ink-faint:#7C878E; --rule:#E1E2DD; --rule-soft:#EDEEE9;
  --accent:#0B6E78; --accent-soft:#E4F0F1;
  --pass:#2F6B4A; --pass-bg:#E6F0E9;
  --fail:#A32B22; --fail-bg:#F6E5E3;
  --unmeasured:#8A6008; --unmeasured-bg:#F6EDDC;
  --debt:#6B4E9B; --debt-bg:#EFE9F6;
  --shadow:0 1px 2px rgba(20,26,29,.06), 0 8px 24px -18px rgba(20,26,29,.5);
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --ground:#0E1315; --panel:#141A1D; --ink:#E7EBEA; --ink-soft:#A6B2B4;
    --ink-faint:#77878A; --rule:#26302F; --rule-soft:#1D2528;
    --accent:#4FC2C9; --accent-soft:#14292C;
    --pass:#79C79A; --pass-bg:#152720;
    --fail:#E5837A; --fail-bg:#2C1A19;
    --unmeasured:#D9AE5C; --unmeasured-bg:#2A2318;
    --debt:#B79BE0; --debt-bg:#221C2E;
    --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -20px rgba(0,0,0,.9);
  }
}
:root[data-theme="dark"]{
  --ground:#0E1315; --panel:#141A1D; --ink:#E7EBEA; --ink-soft:#A6B2B4;
  --ink-faint:#77878A; --rule:#26302F; --rule-soft:#1D2528;
  --accent:#4FC2C9; --accent-soft:#14292C;
  --pass:#79C79A; --pass-bg:#152720;
  --fail:#E5837A; --fail-bg:#2C1A19;
  --unmeasured:#D9AE5C; --unmeasured-bg:#2A2318;
  --debt:#B79BE0; --debt-bg:#221C2E;
  --shadow:0 1px 2px rgba(0,0,0,.4), 0 10px 30px -20px rgba(0,0,0,.9);
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans","Segoe UI",system-ui,sans-serif;
  font-size:16.5px; line-height:1.62; -webkit-font-smoothing:antialiased;
}
.shell{display:grid; grid-template-columns:16.5rem minmax(0,1fr); gap:3rem;
  max-width:78rem; margin:0 auto; padding:0 1.75rem 6rem}
nav{position:sticky; top:0; align-self:start; max-height:100vh; overflow-y:auto;
  padding:2.5rem 0 2rem; border-right:1px solid var(--rule-soft)}
nav .kicker{font-family:"IBM Plex Mono",monospace; font-size:.66rem; letter-spacing:.16em;
  text-transform:uppercase; color:var(--ink-faint); margin:0 0 1rem}
nav ol{list-style:none; margin:0; padding:0; display:flex; flex-direction:column; gap:.1rem}
nav a{display:grid; grid-template-columns:1.6rem 1fr; gap:.35rem; padding:.34rem .6rem .34rem 0;
  color:var(--ink-soft); text-decoration:none; font-size:.85rem; border-radius:3px; line-height:1.35}
nav a span:first-child{font-family:"IBM Plex Mono",monospace; font-size:.72rem; color:var(--ink-faint);
  font-variant-numeric:tabular-nums}
nav a:hover{color:var(--accent)}
nav a:hover span:first-child{color:var(--accent)}
nav a:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
main{padding:2.5rem 0 0; min-width:0}
h1{font-family:"IBM Plex Serif",Georgia,serif; font-weight:600; font-size:clamp(2rem,4.2vw,2.9rem);
  line-height:1.12; letter-spacing:-.02em; margin:0 0 1.6rem; text-wrap:balance; max-width:20ch}
h2{font-family:"IBM Plex Serif",Georgia,serif; font-weight:600; font-size:1.55rem; line-height:1.22;
  letter-spacing:-.012em; margin:3.6rem 0 1.1rem; padding-top:1.6rem; border-top:1px solid var(--rule);
  display:grid; grid-template-columns:2.4rem 1fr; align-items:baseline; text-wrap:balance; scroll-margin-top:1.5rem}
h2 .num{font-family:"IBM Plex Mono",monospace; font-size:.8rem; font-weight:500; color:var(--accent);
  font-variant-numeric:tabular-nums}
h3{font-family:"IBM Plex Sans",sans-serif; font-weight:600; font-size:1.03rem; letter-spacing:.005em;
  margin:2.2rem 0 .6rem; color:var(--ink); text-wrap:balance}
p,li{max-width:68ch}
p{margin:0 0 1rem; color:var(--ink-soft)}
strong{color:var(--ink); font-weight:600}
ul,ol{margin:0 0 1.15rem; padding-left:1.15rem; display:flex; flex-direction:column; gap:.4rem;
  color:var(--ink-soft)}
li::marker{color:var(--ink-faint)}
hr{border:0; height:0; margin:0}
code{font-family:"IBM Plex Mono",ui-monospace,monospace; font-size:.855em;
  background:var(--rule-soft); border:1px solid var(--rule); border-radius:3px;
  padding:.06em .34em; color:var(--ink); white-space:nowrap}
pre{margin:0; padding:1.1rem 1.25rem; background:var(--panel); border:1px solid var(--rule);
  border-radius:4px; box-shadow:var(--shadow)}
pre code{background:none; border:0; padding:0; font-size:.82rem; line-height:1.72;
  white-space:pre; color:var(--ink-soft)}
.scroll{overflow-x:auto; margin:0 0 1.6rem; max-width:100%}
table{border-collapse:collapse; width:100%; font-size:.86rem; line-height:1.5}
th{font-family:"IBM Plex Mono",monospace; font-weight:500; font-size:.66rem; letter-spacing:.13em;
  text-transform:uppercase; color:var(--ink-faint); padding:0 .9rem .55rem; white-space:nowrap;
  border-bottom:1px solid var(--rule)}
td{padding:.68rem .9rem; border-bottom:1px solid var(--rule-soft); color:var(--ink-soft);
  vertical-align:top; font-variant-numeric:tabular-nums}
td:first-child{color:var(--ink)}
tbody tr:hover td{background:var(--rule-soft)}
.chip{font-family:"IBM Plex Mono",monospace; font-size:.64rem; letter-spacing:.08em;
  padding:.14em .45em; border-radius:2px; white-space:nowrap; font-weight:500}
.chip.measured{background:var(--pass-bg); color:var(--pass)}
.chip.derived{background:var(--accent-soft); color:var(--accent)}
.chip.chosen{background:var(--rule-soft); color:var(--ink-faint)}
.chip.unverified{background:var(--unmeasured-bg); color:var(--unmeasured)}
.chip.debt{background:var(--debt-bg); color:var(--debt)}
code.v.pass{background:var(--pass-bg); border-color:transparent; color:var(--pass)}
code.v.fail{background:var(--fail-bg); border-color:transparent; color:var(--fail)}
code.v.unmeasured{background:var(--unmeasured-bg); border-color:transparent; color:var(--unmeasured)}
 main > h1 + p{font-size:1.06rem; max-width:62ch}
em{font-style:italic; color:var(--ink)}
@media (max-width:900px){
  .shell{grid-template-columns:1fr; gap:0; padding:0 1.2rem 4rem}
  nav{position:static; max-height:none; border-right:0; border-bottom:1px solid var(--rule);
    padding:1.75rem 0 1.25rem}
  nav ol{display:grid; grid-template-columns:repeat(auto-fill,minmax(13rem,1fr)); gap:.1rem .8rem}
  main{padding-top:1.75rem}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important; transition:none!important}}
"""

md = SRC.read_text(encoding="utf-8")
body, toc = render(md)
nav = "".join(
    f'<li><a href="#{s}"><span>{num or "·"}</span><span>{html.escape(t)}</span></a></li>'
    for num, t, s in toc
)
page = f"""<title>Липсинк-шаблоны: мануал</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Serif:wght@600&display=swap">
<style>{CSS}</style>
<div class="shell">
<nav aria-label="Разделы">
  <p class="kicker">Разделы</p>
  <ol>{nav}</ol>
</nav>
<main>
{body}
</main>
</div>
"""
DST.parent.mkdir(parents=True, exist_ok=True)
DST.write_text(page, encoding="utf-8")
print(DST, len(page), "bytes,", len(toc), "sections")
