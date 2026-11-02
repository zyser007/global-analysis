#!/usr/bin/env python3
"""Splice tools/gold_module.js into tools/template.html (between the gold-panel marker and the live-layer marker).
Run after editing gold_module.js, then tools/build.py."""
import pathlib, sys
here = pathlib.Path(__file__).resolve().parent
tpl = here / "template.html"
s = tpl.read_text(encoding="utf-8")
mod = (here / "gold_module.js").read_text(encoding="utf-8")
A = "/* ================= gold panel ================= */\n"
B = "/* ================= live layer (artifact db, read-only) ================= */\n"
assert s.count(A) == 1 and s.count(B) == 1 and mod.startswith(A), "markers missing"
i, j = s.index(A), s.index(B)
s = s[:i] + mod.rstrip("\n") + "\n\n" + s[j:]
tpl.write_text(s, encoding="utf-8")
print("spliced gold module into", tpl)
