#!/usr/bin/env python3
"""Serve a copy of site/ under /global-analysis/ on 127.0.0.1 (mimics https://zyser007.github.io/global-analysis/).

  python3 e2e/serve.py <mode> <port>
    full     -- site/ as is (index.html + data/*.json)
    nodata   -- index.html only: every data/*.json request 404s (offline path)
    mutable  -- like full; the tests rewrite the JSON files in e2e/.srv/mutable/global-analysis/data/
  E2E_SITE=/path/to/site  serves another copy of site/ (e.g. one whose data/ was written by updater/prices.py --data-dir)

The page's embedded background data (data/world-data.json + data/gold.json, which the editor agent rewrites every
day) is swapped for the frozen copy in e2e/fixtures/, so the expectations in the specs stay valid: e2e tests the
page code, check.py / visual_check.py test the current data. E2E_LIVE_EMBED=1 keeps the site's own embedded data.
"""
import functools, http.server, json, os, pathlib, re, shutil, sys

mode, port = sys.argv[1], int(sys.argv[2])
assert mode in ("full", "nodata", "mutable"), mode
here = pathlib.Path(__file__).resolve().parent
site = pathlib.Path(os.environ["E2E_SITE"]).resolve() if os.environ.get("E2E_SITE") else here.parent / "site"
root = here / ".srv" / mode
dest = root / "global-analysis"
if root.exists():
    shutil.rmtree(root)
shutil.copytree(site, dest)
if mode == "nodata":
    shutil.rmtree(dest / "data")
if os.environ.get("E2E_LIVE_EMBED") != "1":
    fx = here / "fixtures"
    world = json.loads((fx / "world-data.json").read_text(encoding="utf-8"))
    world["gold"] = json.loads((fx / "gold.json").read_text(encoding="utf-8"))
    txt = json.dumps(world, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = dest / "index.html"
    html, n = re.subn(r'(<script type="application/json" id="world-data">)(.*?)(</script>)',
                      lambda m: m.group(1) + txt + m.group(3), page.read_text(encoding="utf-8"), count=1, flags=re.S)
    assert n == 1, "index.html has no #world-data block"
    page.write_text(html, encoding="utf-8")

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

handler = functools.partial(Quiet, directory=str(root))
srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
print("serving %s on http://127.0.0.1:%d/global-analysis/" % (mode, port), flush=True)
srv.serve_forever()
