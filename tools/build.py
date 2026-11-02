#!/usr/bin/env python3
"""Build world-globe/index.html from tools/template.html.

- `__LAND_DOTS__`               <- tools/land_dots.json (raw text)
- `<script id="world-data">`    <- data/world-data.json + data/gold.json (as key "gold"),
                                   dumped compact (ensure_ascii=False, no spaces) so the block
                                   round-trips byte-for-byte with the previous generation.

Run:  python3 -I tools/build.py
"""
import json, re, sys, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "tools" / "template.html"
LAND = ROOT / "tools" / "land_dots.json"
WORLD = ROOT / "data" / "world-data.json"
GOLD = ROOT / "data" / "gold.json"
OUT = ROOT / "world-globe" / "index.html"

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

# the artifact page must start with <title>, carry no doctype/html/head/body
assert html.startswith("<title>"), "page must start with <title>"
assert not re.search(r"<!doctype|<(html|head|body)[\s>]", html, re.I), "page must not carry doctype/html/head/body"

# verify both JSON blocks parse and the gold data is present
for bid in ("world-data", "land-dots"):
    m = re.search(r'<script type="application/json" id="%s">(.*?)</script>' % bid, html, re.S)
    parsed = json.loads(m.group(1))
    if bid == "world-data":
        assert "gold" in parsed and parsed["gold"]["spot_now"] == world["gold"]["spot_now"]
        assert parsed["conflicts"] and parsed["economies"] and parsed["indicators"]
    else:
        assert len(parsed) > 6000, "land dots look truncated"

OUT.write_text(html, encoding="utf-8")
print("wrote %s (%d bytes, %d lines)" % (OUT, len(html.encode("utf-8")), html.count("\n") + 1))
