#!/usr/bin/env python3
"""Print ONE item of the background data (never the whole file).

  python3 -I editor-agent/show.py conflicts ukraine_russia            the whole item
  python3 -I editor-agent/show.py conflicts ukraine_russia status_th sources   only these fields
  python3 -I editor-agent/show.py economies THA note_th
  python3 -I editor-agent/show.py chokepoints 0          (index from brief.py, or a unique part of the name)
  python3 -I editor-agent/show.py indicators 3
  python3 -I editor-agent/show.py meta
  python3 -I editor-agent/show.py analysis_th points
  python3 -I editor-agent/show.py gold thai              a top-level key or dotted path of data/gold.json
  python3 -I editor-agent/show.py gold outlook_th.calendar_th
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import datatools as T  # noqa: E402


def main(argv: list[str] | None = None, root: pathlib.Path = T.ROOT) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        print(__doc__)
        return 2
    section, rest = args[0], args[1:]
    try:
        if section == "gold":
            g, _ = T.load(root, "gold")
            if not rest:
                print("gold keys: " + ", ".join(g.keys()) + "  (show one: show.py gold <key or dotted.path>)")
                return 0
            out = {p: T.get_path(g, p) for p in rest}
        elif section in ("meta", "analysis_th"):
            w, _ = T.load(root, "world-data")
            obj = w[section]
            out = {f: obj[f] for f in rest} if rest else obj
        elif section in T.LIST_SECTIONS:
            w, _ = T.load(root, "world-data")
            if not rest:
                print("usage: show.py %s <key> [field ...]" % section)
                return 2
            i, item = T.find_item(w, section, rest[0])
            out = {f: item[f] for f in rest[1:]} if rest[1:] else item
            if section in ("chokepoints", "indicators"):
                out = {"_index": i, **out}
        else:
            print("unknown section %r; use one of: %s, gold" % (section, ", ".join(sorted(T.WORLD_SECTIONS))))
            return 2
    except (KeyError, IndexError, TypeError) as e:
        print("not found: %s" % e)
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
