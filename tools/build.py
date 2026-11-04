#!/usr/bin/env python3
"""Build site/index.html (a standalone page for GitHub Pages) from tools/template.html.

- `__LAND_DOTS__`               <- tools/land_dots.json (raw text)
- `__WORLD_DATA__`               <- data/world-data.json + data/gold.json (as key "gold"),
                                   dumped compact (ensure_ascii=False, no spaces). The template holds only this
                                   placeholder; the build fails if it is missing.
- `__LIVE_INDICATORS__`          <- tools/live_indicators.json (indicator tiles that market.json keeps live)

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
LIVE_IND = ROOT / "tools" / "live_indicators.json"
OUT = ROOT / "site" / "index.html"

tpl = TEMPLATE.read_text(encoding="utf-8")
if "__LAND_DOTS__" not in tpl:
    sys.exit("template has no __LAND_DOTS__ placeholder")

world = json.loads(WORLD.read_text(encoding="utf-8"))
world["gold"] = json.loads(GOLD.read_text(encoding="utf-8"))
world_txt = json.dumps(world, ensure_ascii=False, separators=(",", ":"))

# the template carries placeholders only, never a copy of the data (so nobody mistakes it for live content)
WORLD_PH = '<script type="application/json" id="world-data">__WORLD_DATA__</script>'
LIVE_PH = '<script type="application/json" id="live-indicators">__LIVE_INDICATORS__</script>'
for ph in (WORLD_PH, LIVE_PH):
    if tpl.count(ph) != 1:
        sys.exit("template must contain exactly one %s (found %d)" % (ph, tpl.count(ph)))
live_ind = json.loads(LIVE_IND.read_text(encoding="utf-8"))
labels = {i["label_th"] for i in world.get("indicators", [])}
for m in live_ind:
    assert {"key", "label"} <= set(m), "tools/live_indicators.json entries need key and label: %r" % m
    if m["label"] not in labels:
        print("note: live indicator %r has no matching indicator label in data/world-data.json" % m["label"])
html = tpl.replace("__WORLD_DATA__", world_txt.replace("</", "<\\/"), 1)
html = html.replace("__LIVE_INDICATORS__", json.dumps(live_ind, ensure_ascii=False, separators=(",", ":")), 1)
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
for bid in ("world-data", "land-dots", "live-indicators"):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % bid, html, re.S)
    parsed = json.loads(m.group(1))
    if bid == "world-data":
        assert "gold" in parsed and parsed["gold"]["spot_now"] == world["gold"]["spot_now"]
        assert parsed["conflicts"] and parsed["economies"] and parsed["indicators"]
    elif bid == "land-dots":
        assert len(parsed) > 6000, "land dots look truncated"
    else:
        assert isinstance(parsed, list), "live indicators must be a list"
assert "__WORLD_DATA__" not in html and "__LIVE_INDICATORS__" not in html and "__LAND_DOTS__" not in html

OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(html, encoding="utf-8")
print("wrote %s (%d bytes, %d lines)" % (OUT.relative_to(ROOT), len(html.encode("utf-8")), html.count("\n") + 1))
