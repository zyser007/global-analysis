#!/usr/bin/env python3
"""One line per item of the background data, so the agent can plan research without reading the files.

  python3 -I editor-agent/brief.py            all sections (a few thousand tokens)
  python3 -I editor-agent/brief.py --leads    also the current headlines (site/data/headlines.json) as research leads
  python3 -I editor-agent/brief.py conflicts  only one section (meta, conflicts, economies, chokepoints, indicators, analysis, gold)

Columns: key | name | state | last dated mention in the text (d mon) | newest date in a source URL | number of sources.
Use show.py to read one item in full.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import datatools as T  # noqa: E402


def cut(s: object, n: int) -> str:
    t = " ".join(str(s).split())
    return t if len(t) <= n else t[: n - 1] + "…"


def last_mention(texts: list[str], ref: dt.date) -> str:
    ds = [d for t in texts for d in T.text_dates(t, ref) if d <= ref + dt.timedelta(days=1)]
    return T.thai_date(max(ds), year=False) if ds else "-"


def newest_url(urls: list[str]) -> str:
    ds = [d for d in (T.url_date(u) for u in urls) if d]
    return max(ds).isoformat() if ds else "-"


def main(argv: list[str] | None = None, root: pathlib.Path = T.ROOT) -> int:
    args = sys.argv[1:] if argv is None else argv
    leads = "--leads" in args
    only = [a for a in args if not a.startswith("--")]
    w, _ = T.load(root, "world-data")
    g, _ = T.load(root, "gold")
    meta = w["meta"]
    ref = dt.date.fromisoformat(meta["updated"])
    ref = max(ref, T.bkk_today())
    out: list[str] = []

    def want(s: str) -> bool:
        return not only or s in only

    if want("meta"):
        out.append("META updated=%s basis=%s title=%s" % (meta["updated"], meta.get("basis_th", "-"), meta["title"]))
    if want("conflicts"):
        out.append("## conflicts (id | name | type intensity confidence | last mention | newest url date | n src)")
        for c in sorted(w["conflicts"], key=lambda c: -c["intensity"]):
            out.append("%s | %s | %s i%d %s | %s | %s | %d" % (
                c["id"], cut(c["name_th"], 40), c["type"], c["intensity"], c["confidence"],
                last_mention([c["status_th"], c["summary_th"]], ref), newest_url(c["sources"]), len(c["sources"])))
    if want("economies"):
        out.append("## economies (iso | gdp26/gdp27 | cpi | rate | health | last mention | newest url date)")
        for e in w["economies"]:
            out.append("%s | %s/%s | %s | %s | %s | %s | %s" % (
                e["iso"], e["gdp_growth_2026"], e["gdp_growth_2027"], e["inflation"], e["policy_rate"], e["health"],
                last_mention([e["note_th"]], ref), newest_url(e["sources"])))
    if want("chokepoints"):
        out.append("## chokepoints (index | name | level | last mention) - no sources field; sources go in changes.json")
        for i, k in enumerate(w["chokepoints"]):
            out.append("%d | %s | L%d | %s" % (i, k["name_th"], k["level"], last_mention([k["note_th"]], ref)))
    if want("indicators"):
        out.append("## indicators (index | label | value | trend | as_of)")
        for i, it in enumerate(w["indicators"]):
            out.append("%d | %s | %s | %s | %s" % (i, cut(it["label_th"], 50), cut(it["value"], 18), it["trend"], it["as_of"]))
    if want("analysis"):
        a = w["analysis_th"]
        out.append("## analysis_th: %d points, %d risks, last mention %s | headline: %s" % (
            len(a["points"]), len(a["risks"]), last_mention([a["headline"], a["thailand"], *a["points"], *a["risks"]], ref),
            cut(a["headline"], 90)))
    if want("gold"):
        th = g["thai"]
        s = g["sentiment"]
        out.append("## gold")
        out.append("as_of=%s spot=%s day=%s%% week=%s%% from_peak=%s%% peak=%s (%s) year_low=%s | caption=%s" % (
            g["as_of"], g["spot_now"], g["change_day_pct"], g["change_week_pct"], g["from_peak_pct"], g["peak"], g["peak_date"],
            g["year_low"], cut(g["as_of_caption_th"], 50)))
        out.append("thai as_of=%s sell=%s buy=%s ornament=%s | sentiment bear/bull/neutral=%s/%s/%s | %s" % (
            th["as_of"], th["sell"], th["buy"], th["ornament_sell"], s["bearish"], s["bullish"], s["neutral"], cut(s["survey_th"], 60)))
        lv = g["levels"]
        out.append("levels: %s | ma200=%s rsi=%s | forecasts: %s" % (
            ", ".join("%s-%s %s" % (x["lo"], x["hi"], x["role"][:3]) for x in lv["support"]), lv["ma200"], lv["rsi_daily"],
            ", ".join("%s %s" % (f["name"], f["end_2026"]) for f in g["forecasts"]["items"])))
        cal = g["outlook_th"]["calendar_th"]
        out.append("calendar '%s': %s" % (cal["title_th"], " / ".join(cut(x, 40) for x in cal["items"])))
        out.append("series_2026 last point: %s | sections: drivers %d, supports %d, scenarios %d, risks up %d down %d" % (
            g["series_2026"]["points"][-1], len(g["drivers_th"]["points"]), len(g["supports_th"]["points"]),
            len(g["outlook_th"]["scenarios"]), len(g["outlook_th"]["risks_up"]), len(g["outlook_th"]["risks_down"])))
    if leads:
        p = root / "site" / "data" / "headlines.json"
        if p.exists():
            h = json.loads(p.read_text(encoding="utf-8"))
            out.append("## headlines %s (conflict_id | time | title)" % h.get("updated_at"))
            for it in h.get("items", []):
                out.append("%s | %s | %s" % (it.get("conflict_id"), str(it.get("time"))[:16], cut(it.get("title_th"), 80)))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
