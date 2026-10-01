"""Build the GitHub Pages site into _site/:

  index.html        landing page (site/index.html with the version and changelog filled in)
  docs/*.html       the repo's Markdown docs
  demo/             the real web app + recordings of the real API on invented sample data
  shots/*.png       screenshots taken from the demo
  latest.json       what the installed app checks to offer updates

Usage:  python site/build_site.py [--out _site] [--skip-demo]
"""
from __future__ import annotations

import argparse
import html
import posixpath
import json
import re
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SITE))

from aaryaai_finance import __version__  # noqa: E402

REPO = "https://github.com/ajeetchouksey/aaryaai-finance"
PAGES = "https://ajeetchouksey.github.io/aaryaai-finance"
DOCS = [  # (source, output, title)
    ("README.md", "overview.html", "Overview"),
    ("docs/getting-started.md", "getting-started.html", "Getting started"),
    ("docs/setup-guide.md", "setup-guide.html", "Setup guide"),
    ("docs/planning.md", "planning.html", "Planning tools"),
    ("docs/mcp.md", "mcp.html", "MCP: Claude Desktop & VS Code"),
    ("CONTRIBUTING.md", "rules-and-packs.html", "Rules, packs & data model"),
    ("docs/ai-providers.md", "ai.html", "Connecting AI"),
    ("PRIVACY.md", "privacy.html", "Privacy & security"),
    ("CHANGELOG.md", "changelog.html", "Changelog"),
]
LINK_MAP = {src: out for src, out, _ in DOCS} | {"LICENSE": f"{REPO}/blob/main/LICENSE", "THIRD_PARTY.md": f"{REPO}/blob/main/THIRD_PARTY.md"}


def changelog_sections() -> list[tuple[str, str]]:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.M)[1:]
    return [(p.split("\n", 1)[0].strip(), p.split("\n", 1)[1].strip() if "\n" in p else "") for p in parts]


def fix_links(md_text: str, src: str) -> str:
    base = Path(src).parent

    def rep(m):
        label, target = m.group(1), m.group(2)
        if re.match(r"^(https?:|mailto:|#|\.\./#)", target):
            return m.group(0)
        path, _, frag = target.partition("#")
        norm = posixpath.normpath((base / path).as_posix()).lstrip("./") if path else ""
        if norm in LINK_MAP:
            t = LINK_MAP[norm]
        elif norm:
            kind = "tree" if norm.endswith("/") or "." not in Path(norm).name else "blob"
            t = f"{REPO}/{kind}/main/{norm}"
        else:
            t = ""
        return f"[{label}]({t}{'#' + frag if frag else ''})"
    md_text = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)\)", rep, md_text)
    md_text = re.sub(r'<p align="center"><img src="aaryaai_finance/web/brand/[^"]+"[^>]*></p>\s*', "", md_text)
    return md_text


def render_docs(out: Path):
    tpl = (SITE / "doc.html").read_text(encoding="utf-8")
    (out / "docs").mkdir(parents=True, exist_ok=True)
    for src, dst, title in DOCS:
        p = ROOT / src
        if not p.exists():
            continue
        body = markdown.markdown(fix_links(p.read_text(encoding="utf-8"), src),
                                 extensions=["fenced_code", "tables", "toc", "sane_lists"], output_format="html5")
        nav = "".join(f'<a href="{d}"{" class=on" if d == dst else ""}>{html.escape(t)}</a>' for _, d, t in DOCS if (ROOT / _).exists())
        page = (tpl.replace("{{title}}", html.escape(title)).replace("{{nav}}", nav).replace("{{body}}", body)
                .replace("{{version}}", __version__).replace("{{edit}}", f"{REPO}/edit/main/{src}"))
        (out / "docs" / dst).write_text(page, encoding="utf-8")
    shutil.copy(out / "docs" / "overview.html", out / "docs" / "index.html")


def build_demo(out: Path) -> None:
    from demo_data import build as build_data
    from record_demo import record
    demo = out / "demo"
    web = ROOT / "aaryaai_finance" / "web"
    shutil.copytree(web, demo / "static")
    idx = (web / "index.html").read_text(encoding="utf-8")
    idx = idx.replace('"/static/', '"static/')
    idx = idx.replace('<link rel="stylesheet" href="static/style.css">',
                      '<link rel="stylesheet" href="static/style.css">\n<link rel="stylesheet" href="demo.css">\n<script src="demo.js"></script>')
    idx = idx.replace("<title>", '<meta name="robots" content="noindex">\n<title>', 1)
    (demo / "index.html").write_text(idx, encoding="utf-8")
    shutil.copy(SITE / "demo" / "demo.js", demo / "demo.js")
    shutil.copy(SITE / "demo" / "demo.css", demo / "demo.css")
    with tempfile.TemporaryDirectory() as t:
        data = build_data(Path(t) / "data")
        rec = record(data, out)
    (demo / "recordings.json").write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  demo: {len(rec)} recorded API answers")


def fmt_money(v: float, ccy: str) -> str:
    sym = {"EUR": "€", "INR": "₹", "USD": "$"}.get(ccy, ccy + " ")
    n = int(round(v))
    if ccy == "INR":                                    # lakh grouping: 1,09,80,611
        s = str(abs(n))
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:]); head = head[:-2]
        if head:
            parts.insert(0, head)
        body = ",".join(parts + [tail]) if parts else tail
    else:
        body = f"{abs(n):,}"
    return ("−" if n < 0 else "") + sym + body


def hero_figure(out: Path) -> dict:
    """Numbers for the landing-page figure, taken from the demo recording so they match the demo."""
    try:
        rec = json.loads((out / "demo" / "recordings.json").read_text(encoding="utf-8"))
        pos = json.loads(rec["GET /calc/position"]["body"])
        nw, rates = pos["net_worth"], pos["rates"]
    except (OSError, KeyError, ValueError):
        nw, rates = {"net_worth": 111478, "base": "EUR", "by_currency": {"EUR": 78360, "INR": 39319}}, {"INR": 98.5}
    base, total = nw["base"], nw["net_worth"]
    by = nw.get("by_currency", {})
    gross = sum(by.values()) or 1
    rows = []
    for ccy, v_base in sorted(by.items(), key=lambda x: -x[1]):
        native = v_base * rates.get(ccy, 1) if ccy != base else v_base
        share = v_base / gross
        col = {"EUR": "var(--eur)", "INR": "var(--inr)"}.get(ccy, "var(--good)")
        rows.append(f'<div class="row"><span class="tag {ccy.lower()}">{ccy}</span><span class="bar"><i style="width:{share * 100:.0f}%;background:{col}"></i></span>'
                    f'<span class="v"><span data-amt>{fmt_money(native, ccy)}</span></span></div>')
    other = next((c for c in by if c != base), None)
    alt = f'≈ <span data-amt>{fmt_money(total * rates[other], other)}</span> at {rates[other]:.2f} {other} per {base}' if other and rates.get(other) else ""
    return {"total": f'<span data-amt>{fmt_money(total, base)}</span>', "alt": alt, "rows": "".join(rows)}


def build(out: Path, skip_demo: bool = False) -> None:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    shutil.copytree(SITE / "assets", out / "assets")
    shutil.copy(ROOT / "aaryaai_finance/web/brand/favicon.svg", out / "assets/favicon.svg")
    shutil.copy(ROOT / "aaryaai_finance/web/brand/logo-mono-white.svg", out / "assets/logo-mono-white.svg")
    for f in ("barlow-400", "barlow-500", "barlow-600", "barlowcond-600", "barlowcond-700", "plexmono-400", "plexmono-500"):
        shutil.copy(ROOT / f"aaryaai_finance/web/fonts/{f}.woff2", out / f"assets/{f}.woff2")
    if skip_demo:
        (out / "shots").mkdir()
    else:
        build_demo(out)
    render_docs(out)

    sections = changelog_sections()
    head, notes = sections[0] if sections else (__version__, "")
    notes_html = markdown.markdown(fix_links(notes, "CHANGELOG.md"), extensions=["sane_lists"])
    released = head.split("—")[-1].strip() if "—" in head else date.today().isoformat()
    tag = f"v{__version__}"
    page = (SITE / "index.html").read_text(encoding="utf-8")
    page = (page.replace("{{version}}", __version__).replace("{{released}}", html.escape(released))
            .replace("{{notes}}", notes_html).replace("{{zip}}", f"{REPO}/archive/refs/tags/{tag}.zip")
            .replace("{{repo}}", REPO).replace("{{year}}", str(date.today().year)))
    hero = hero_figure(out)
    page = page.replace("{{hero_total}}", hero["total"]).replace("{{hero_alt}}", hero["alt"]).replace("{{hero_rows}}", hero["rows"])
    (out / "index.html").write_text(page, encoding="utf-8")

    (out / "latest.json").write_text(json.dumps({
        "name": "aaryaai-finance", "version": __version__, "released": released, "channel": "stable",
        "notes_url": f"{PAGES}/docs/changelog.html", "download_url": f"{REPO}/archive/refs/tags/{tag}.zip",
        "install": f"pipx install --force git+{REPO}@{tag}", "notes": re.sub(r"\s+", " ", re.sub(r"[*`#\[\]]", "", notes))[:600],
    }, indent=2), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    (out / "404.html").write_text(page.replace("<main", '<main data-404="1"', 1), encoding="utf-8")
    print(f"built {out} for v{__version__}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    ap.add_argument("--skip-demo", action="store_true")
    a = ap.parse_args()
    build(a.out, a.skip_demo)
