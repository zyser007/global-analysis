#!/usr/bin/env python3
"""Build site/index.html (a standalone page for GitHub Pages) from tools/template.html.

- `__LAND_DOTS__`               <- tools/land_dots.json (raw text)
- `<script id="world-data">`    <- data/world-data.json + data/gold.json (as key "gold"),
                                   dumped compact (ensure_ascii=False, no spaces).

The live prices / headlines / run status are NOT embedded: the page fetches
site/data/{market,headlines,status}.json at runtime (relative URLs), and
updater/update.py rewrites those files from GitHub Actions.

Run:  python3 -I tools/build.py          (after editing tools/gold_module.js run tools/splice_gold.py first)
"""
import json, re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "tools" / "template.html"
LAND = ROOT / "tools" / "land_dots.json"
WORLD = ROOT / "data" / "world-data.json"
GOLD = ROOT / "data" / "gold.json"
OUT = ROOT / "site" / "index.html"

tpl = TEMPLATE.read_text(encoding="utf-8")
if "__LAND_DOTS__" not in tpl:
    sys.exit("template has no __LAND_DOTS__ placeholder")

world = json.loads(WORLD.read_text(encoding="utf-8"))
world["gold"] = json.loads(GOLD.read_text(encoding="utf-8"))
world_txt = json.dumps(world, ensure_ascii=False, separators=(",", ":"))

pat = re.compile(r'(<script type="application/json" id="world-data">)(.*?)(</script>)', re.S)
if not pat.search(tpl):
    sys.exit("template has no #world-data block")
html = pat.sub(lambda m: m.group(1) + world_txt + m.group(3), tpl, count=1)
html = html.replace("__LAND_DOTS__", LAND.read_text(encoding="utf-8").strip(), 1)

# a normal standalone document
assert html.startswith("<!doctype html>"), "page must start with a doctype"
for tag in ('<html lang="th">', "<head>", '<meta charset="utf-8">', "viewport-fit=cover", "</head>", "<body>", "</body>", "</html>"):
    assert tag in html, "missing " + tag
assert "claude.use" not in html and "window.claude" not in html, "artifact runtime code left in the page"
# every runtime URL must be relative (the site lives under /<repo>/ on GitHub Pages)
assert not re.search(r"fetch\(\s*['\"]/", html), "fetch() with an absolute path"
assert "'data/' + name + '.json" in html, "live layer must fetch data/<doc>.json relatively"
# external scripts: three.js r128 pinned on cdnjs only
srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
assert srcs == ["https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"], srcs

# verify both JSON blocks parse and the gold data is present
for bid in ("world-data", "land-dots"):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % bid, html, re.S)
    parsed = json.loads(m.group(1))
    if bid == "world-data":
        assert "gold" in parsed and parsed["gold"]["spot_now"] == world["gold"]["spot_now"]
        assert parsed["conflicts"] and parsed["economies"] and parsed["indicators"]
    else:
        assert len(parsed) > 6000, "land dots look truncated"

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print("wrote %s (%d bytes, %d lines)" % (OUT.relative_to(ROOT), len(html.encode("utf-8")), html.count("\n") + 1))
