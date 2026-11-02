#!/usr/bin/env python3
"""Serve a copy of site/ under /global-analysis/ on 127.0.0.1 (mimics https://zyser007.github.io/global-analysis/).

  python3 e2e/serve.py <mode> <port>
    full     -- site/ as is (index.html + data/*.json)
    nodata   -- index.html only: every data/*.json request 404s (offline path)
    mutable  -- like full; the tests rewrite the JSON files in e2e/.srv/mutable/global-analysis/data/
"""
import functools, http.server, pathlib, shutil, sys

mode, port = sys.argv[1], int(sys.argv[2])
assert mode in ("full", "nodata", "mutable"), mode
here = pathlib.Path(__file__).resolve().parent
site = here.parent / "site"
root = here / ".srv" / mode
dest = root / "global-analysis"
if root.exists():
    shutil.rmtree(root)
shutil.copytree(site, dest)
if mode == "nodata":
    shutil.rmtree(dest / "data")

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
