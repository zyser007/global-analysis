#!/usr/bin/env python3
"""Rebuild site/data/gold_history.json from the git history of site/data/market.json (one point per distinct
gold / gold_th as_of, the same rule update.py uses on every run). No network, no API key.

    python -I updater/backfill_gold_history.py            # write site/data/gold_history.json
    python -I updater/backfill_gold_history.py --check    # print what it would write, change nothing
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import update  # noqa: E402

MARKET_PATH = "site/data/market.json"


def history_from_markets(markets: list[dict], now: dt.datetime | None = None) -> dict:
    """Fold market.json versions (oldest first) into a gold_history doc, skipping versions whose gold point is
    unusable or whose as_of did not move. `now` (default: the newest updated_at) drives the thinning of old points."""
    usable = [m for m in markets if isinstance(m, dict) and update.history_point(m) is not None]
    if now is None:
        now = max((dt.datetime.fromisoformat(m["updated_at"].replace("Z", "+00:00")) for m in usable),
                  default=update.utcnow())
    hist: dict | None = None
    for m in sorted(usable, key=lambda m: update._ts(m["updated_at"])):
        t = dt.datetime.fromisoformat(m["updated_at"].replace("Z", "+00:00"))
        hist, _ = update.append_history(hist, m, t)
    hist = hist or {"updated_at": update.iso(now), "points": []}
    hist["points"] = update.compact_history(hist["points"], now)
    return hist


def git_markets(root: pathlib.Path) -> list[dict]:
    """Every committed version of site/data/market.json, oldest first (unreadable versions are skipped)."""
    log = subprocess.run(["git", "-C", str(root), "log", "--reverse", "--format=%H", "--", MARKET_PATH],
                         capture_output=True, text=True, check=True).stdout.split()
    out = []
    for sha in log:
        r = subprocess.run(["git", "-C", str(root), "show", f"{sha}:{MARKET_PATH}"], capture_output=True, text=True)
        if r.returncode != 0:
            continue
        try:
            out.append(json.loads(r.stdout))
        except ValueError:
            continue
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="print the result, write nothing")
    args = ap.parse_args(argv)
    markets = git_markets(update.ROOT)
    current = update.DATA_DIR / "market.json"
    if current.exists():                      # the working copy may be newer than the last commit
        markets.append(update.load_json(current))
    hist = history_from_markets(markets)
    errs = update.validate_doc(update.HISTORY, hist)
    if errs:
        print("backfill: INVALID\n  " + "\n  ".join(errs[:5]), file=sys.stderr)
        return 1
    pts = hist["points"]
    print(f"backfill: {len(markets)} market.json versions -> {len(pts)} points"
          + (f" ({pts[0]['spot_as_of']} .. {pts[-1]['spot_as_of']})" if pts else ""))
    for p in pts:
        print(f"  {p['spot_as_of']}  spot {p['spot']:>8}   {p['th_as_of']}  th_sell {p['th_sell']}")
    if not args.check:
        update.write_docs(update.DATA_DIR, {update.HISTORY: hist})
        print(f"wrote {update.DATA_DIR / (update.HISTORY + '.json')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
