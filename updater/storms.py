#!/usr/bin/env python3
"""Refresh site/data/storms.json: tropical cyclone tracks and wind areas from GDACS (free public feed, no AI, no API key).

    python updater/storms.py              # fetch the feed, write site/data/storms.json
    python updater/storms.py --check      # validate the current file only (no network)

Feed
- GDACS event search (TC only, green, orange and red), then one geometry request per storm:
  gdacsapi/api/polygons/getgeometry. It gives the track segments with a forecast flag, the areas that
  winds of 60, 90 and 120 km/h reach, and the uncertainty cone. GDACS takes these from JTWC, NOAA or an RSMC.
- A storm's geometry is fetched again only when its GDACS episode changed (a new advisory, about every
  6 hours); otherwise the previous file's geometry is reused. That spares GDACS and keeps the commits small.

Rules (the same safety rules as updater/disasters.py)
- Kept: storms GDACS marks as current, plus storms that ended up to ENDED_KEEP_DAYS ago. At most MAX_ITEMS.
- Order: red, orange, yellow, green, no alert; then the latest data first.
- The document is validated against updater/schema/storms.schema.json and written atomically, compact,
  and never above MAX_FILE_BYTES (cones, then wind areas, then tracks of the last storms go first).
- The list fails (network, HTTP error, junk): the items and `updated` stay as they were, `ok` is false,
  `message_th` says so and the exit code is 1. There is no write when there is nothing to keep.
- One geometry fails: that storm keeps its previous geometry, or only its position when it has none, `ok` is
  false, `message_th` says so and the exit code stays 0.
- Python standard library for fetching; jsonschema (already pinned in requirements.txt) to validate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import tempfile
import urllib.parse
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import disasters as dz  # noqa: E402  (fetching, time, number and Thai place helpers)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
SCHEMA_PATH = ROOT / "updater" / "schema" / "storms.schema.json"
FILE_NAME = "storms.json"

GDACS_SEARCH = dz.GDACS_SEARCH
GEOMETRY_URL = "https://www.gdacs.org/gdacsapi/api/polygons/getgeometry"
WINDOW_DAYS = 21                     # search window: a long-lived storm is still found
ENDED_KEEP_DAYS = 2                  # a storm stays this long after GDACS stops marking it current
KEPT_DAYS_ON_FAILURE = 7             # with the feed down, old storms still leave the list
MAX_ITEMS = 8
MAX_RING = 36                        # points kept per wind area or cone outline
MAX_FILE_BYTES = 48 * 1024
WIND_AREAS = ("60", "90", "120")     # km/h, as GDACS labels them


def list_url(now: dt.datetime) -> str:
    q = {"eventlist": "TC", "alertlevel": "green;orange;red",
         "fromDate": (now - dt.timedelta(days=WINDOW_DAYS)).strftime("%Y-%m-%d"),
         "toDate": (now + dt.timedelta(days=1)).strftime("%Y-%m-%d"), "pagesize": "50", "pagenumber": "1"}
    return GDACS_SEARCH + "?" + urllib.parse.urlencode(q, safe=";")


def geometry_url(event_id: int, episode: int) -> str:
    return GEOMETRY_URL + "?" + urllib.parse.urlencode({"eventtype": "TC", "eventid": event_id, "episodeid": episode})


# ----------------------------------------------------------------- the storm list
def _is_true(v: Any) -> bool:
    return v is True or str(v).strip().lower() == "true"


def _storm(f: dict) -> dict | None:
    p = f["properties"]
    eid, episode = p.get("eventid"), p.get("episodeid")
    pos = dz._coords(f)
    start = dz.parse_time(p.get("fromdate"))
    if str(p.get("eventtype") or "TC").upper() != "TC" or not isinstance(eid, int) or not isinstance(episode, int) or pos is None or start is None:
        return None
    end = dz.parse_time(p.get("todate")) or start
    alert = str(p.get("alertlevel") or "").strip().lower() or None
    if alert not in dz.ALERT_RANK:
        return None
    sev = p.get("severitydata") if isinstance(p.get("severitydata"), dict) else {}
    wind = dz.num(sev.get("severity"))
    countries = [dz.clean(c.get("countryname"), 80) for c in (p.get("affectedcountries") or []) if isinstance(c, dict) and c.get("countryname")]
    if not countries:
        countries = [c.strip() for c in str(p.get("country") or "").split(",") if c.strip()]
    url = (p.get("url") or {}).get("report") if isinstance(p.get("url"), dict) else None
    url = str(url or f"https://www.gdacs.org/report.aspx?eventid={eid}&episodeid={episode}&eventtype=TC").replace("http://", "https://", 1)
    return {
        "id": f"gdacs-tc-{eid}",
        "event_id": eid,
        "episode": episode,
        "name": dz.clean(p.get("eventname"), 60) or f"TC-{eid}",
        "alert_level": alert,
        "ongoing": _is_true(p.get("iscurrent")),
        "lat": pos[0], "lon": pos[1],
        "start": dz.iso(start), "end": dz.iso(max(end, start)),
        "updated": dz.iso(max(dz.parse_time(p.get("datemodified")) or end, start)),
        "wind_kmh": round(wind) if wind else None,
        "agency": dz.clean(p.get("source"), 20),
        "country_th": dz.places_th(countries),
        "source_url": url,
        "track": [],
        "wind_areas": {},
        "cone": [],
    }


def keep(item: dict, now: dt.datetime) -> bool:
    if item.get("ongoing"):
        return True
    end = dz.parse_time(item.get("end"))
    return end is not None and now - end <= dt.timedelta(days=ENDED_KEEP_DAYS)


def sort_key(it: dict) -> tuple:
    t = dz.parse_time(it.get("end"))
    return (dz.ALERT_RANK.get(it.get("alert_level"), 9), -(t.timestamp() if t else 0), it["id"])


def parse_list(doc: Any, now: dt.datetime) -> list[dict]:
    """GDACS SEARCH GeoJSON -> kept storms, without geometry. Raises FeedError on junk."""
    if doc is None:          # HTTP 204: no events in the window
        return []
    feats = dz._features(doc)
    items, readable = [], 0
    for f in feats:
        try:
            it = _storm(f)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if it is None:
            continue
        readable += 1
        if keep(it, now):
            items.append(it)
    dz._check_parsed("GDACS", len(feats), readable)
    return sorted(items, key=sort_key)[:MAX_ITEMS]


# ----------------------------------------------------------------- one storm's geometry
def _pt(c: Any) -> tuple[float, float] | None:
    if not isinstance(c, list) or len(c) < 2:
        return None
    lon, lat = dz.num(c[0]), dz.num(c[1])
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    return round(lat, 1), round(lon, 1)


def _ring(geometry: dict) -> list[list[float]]:
    """The largest outer ring of a Polygon or MultiPolygon, thinned to MAX_RING points."""
    kind = geometry.get("type")
    rings = geometry.get("coordinates") if kind == "Polygon" else [p[0] for p in (geometry.get("coordinates") or []) if p] if kind == "MultiPolygon" else []
    rings = rings[:1] if kind == "Polygon" else rings
    if not rings:
        return []
    ring = max(rings, key=len)
    pts = [p for p in (_pt(c) for c in ring) if p]
    if len(pts) > MAX_RING:
        step = len(pts) / MAX_RING
        pts = [pts[int(i * step)] for i in range(MAX_RING)]
    out: list[list[float]] = []
    for p in pts:
        if not out or out[-1] != [p[0], p[1]]:
            out.append([p[0], p[1]])
    return out


def _chain(segments: list[tuple[tuple[float, float], tuple[float, float], bool]]) -> list[list[float]]:
    """GDACS lists the track as unordered 2-point segments. Walk them from the start: [[lat, lon, forecast 0/1], ...]."""
    if not segments:
        return []
    nxt = {a: (b, fc) for a, b, fc in segments}
    ends = {b for _, b, _ in segments}
    starts = [a for a, _, _ in segments if a not in ends]
    cur = starts[0] if starts else segments[-1][0]
    out, seen = [[cur[0], cur[1], 0]], {cur}
    while cur in nxt:
        cur, fc = nxt[cur]
        if cur in seen:
            break
        seen.add(cur)
        out.append([cur[0], cur[1], 1 if fc else 0])
    return out if len(out) == len(segments) + 1 else []


def parse_geometry(doc: Any) -> dict:
    """-> {track, wind_areas, cone}. Raises FeedError when the document has no usable track."""
    feats = dz._features(doc)
    segs, areas, cone = [], {}, []
    for f in feats:
        if not isinstance(f, dict):
            continue
        g = f.get("geometry") if isinstance(f.get("geometry"), dict) else {}
        p = f.get("properties") if isinstance(f.get("properties"), dict) else {}
        cls = str(p.get("Class") or "")
        if g.get("type") == "LineString" and cls.startswith("Line_"):
            pts = [x for x in (_pt(c) for c in (g.get("coordinates") or [])) if x]
            segs.extend((a, b, _is_true(p.get("forecast"))) for a, b in zip(pts, pts[1:]) if a != b)
        elif cls == "Poly_Cones":
            cone = _ring(g)
        elif cls.startswith("Poly_") and not p.get("featuretype"):
            label = str(p.get("polygonlabel") or "").replace("km/h", "").strip()
            if label in WIND_AREAS:
                areas[label] = _ring(g)
    track = _chain(segs)
    if len(track) < 2:
        raise dz.FeedError("no usable track in the geometry")
    return {"track": track, "wind_areas": {k: v for k, v in areas.items() if len(v) >= 3}, "cone": cone if len(cone) >= 3 else []}


# ----------------------------------------------------------------- combine
def dumps(doc: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n"


def fit_budget(doc: dict) -> None:
    """Keep the hourly commit small: the least urgent storms lose their cones, then wind areas, then tracks."""
    for field, empty in (("cone", []), ("wind_areas", {}), ("track", [])):
        for it in reversed(doc["items"]):
            if len(dumps(doc).encode("utf-8")) <= MAX_FILE_BYTES:
                return
            it[field] = empty


def build_doc(prev: dict | None, fresh: list[dict] | None, geo: dict[str, dict], failed: list[str], list_error: str,
              now: dt.datetime, url: str) -> dict:
    prev = prev or {}
    if fresh is None:
        limit = dt.timedelta(days=KEPT_DAYS_ON_FAILURE)
        items = [dict(i) for i in prev.get("items") or [] if (t := dz.parse_time(i.get("end"))) is not None and now - t <= limit]
        msg = "โหลดข้อมูลพายุจาก GDACS ไม่สำเร็จรอบนี้ แสดงข้อมูลล่าสุดที่ได้รับ"
    else:
        items = []
        for it in fresh:
            it = dict(it)
            it.update(geo.get(it["id"]) or {})
            items.append(it)
        msg = ("โหลดเส้นทางพายุ " + " ".join(failed) + " ไม่สำเร็จรอบนี้ แสดงข้อมูลล่าสุดที่มี") if failed else ""
    ok = fresh is not None and not failed
    old = prev.get("feed") if isinstance(prev.get("feed"), dict) else {}
    feed = {"ok": fresh is not None, "fetched": dz.iso(now) if fresh is not None else old.get("fetched"), "count": len(items), "url": url}
    if fresh is None:
        feed["error"] = dz.clean(list_error or "unknown error", 200)
    doc = {"updated": dz.iso(now) if fresh is not None else (prev.get("updated") or dz.iso(now)), "checked": dz.iso(now),
           "ok": ok, "message_th": msg, "feed": feed, "items": items}
    fit_budget(doc)
    return doc


# ----------------------------------------------------------------- validate + write
_validator: Any = None


def validate(doc: Any) -> list[str]:
    global _validator
    import jsonschema  # pinned in updater/requirements.txt

    if _validator is None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        _validator = jsonschema.Draft202012Validator(schema)
    errs = [f"storms: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in _validator.iter_errors(doc)]
    if errs:
        return errs
    ids = [i["id"] for i in doc["items"]]
    if len(set(ids)) != len(ids):
        errs.append("storms: duplicate ids")
    if [i["id"] for i in sorted(doc["items"], key=sort_key)] != ids:
        errs.append("storms: items are not in alert / newest order")
    if len(dumps(doc).encode("utf-8")) > MAX_FILE_BYTES:
        errs.append(f"storms: larger than {MAX_FILE_BYTES} bytes")
    return errs


def load_previous(data_dir: pathlib.Path) -> tuple[dict | None, str]:
    path = data_dir / FILE_NAME
    if not path.exists():
        return None, "no previous file"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"cannot read {path.name}: {e}"
    errs = validate(doc)
    return (None, "; ".join(errs[:3])) if errs else (doc, "")


def write_doc(data_dir: pathlib.Path, doc: dict) -> None:
    errs = validate(doc)
    if errs:
        raise ValueError("; ".join(errs[:5]))
    data_dir.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".storms.", suffix=".json.tmp", dir=data_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(dumps(doc))
        os.replace(tmp, data_dir / FILE_NAME)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ----------------------------------------------------------------- run
def run(data_dir: pathlib.Path = DATA_DIR, fetch: dz.Fetcher = dz.http_get, now: dt.datetime | None = None) -> int:
    now = now or dz.utcnow()
    prev, why = load_previous(data_dir)
    if prev is None and why != "no previous file":
        print(f"previous {FILE_NAME} unusable ({why}); starting from an empty list", file=sys.stderr)
    prev_by_id = {i["id"]: i for i in (prev or {}).get("items") or []}
    url = list_url(now)
    fresh: list[dict] | None
    list_error = ""
    try:
        fresh = parse_list(dz._get_json(fetch, url, empty_ok=True), now)
        print(f"GDACS: {len(fresh)} storms kept")
    except dz.FeedError as e:
        fresh, list_error = None, str(e)
        print(f"GDACS: FAILED - {e}", file=sys.stderr)
    if fresh is None and prev is None:
        print(f"the feed failed and there is no valid previous file; {FILE_NAME} not written", file=sys.stderr)
        return 1
    geo: dict[str, dict] = {}
    failed: list[str] = []
    fetched = 0
    for it in fresh or []:
        old = prev_by_id.get(it["id"])
        if old and old.get("episode") == it["episode"] and old.get("track"):
            geo[it["id"]] = {k: old[k] for k in ("track", "wind_areas", "cone")}
            continue
        try:
            geo[it["id"]] = parse_geometry(dz._get_json(fetch, geometry_url(it["event_id"], it["episode"])))
            fetched += 1
        except dz.FeedError as e:
            print(f"GDACS geometry {it['name']}: FAILED - {e}", file=sys.stderr)
            failed.append(it["name"])
            if old:
                geo[it["id"]] = {k: old.get(k, d) for k, d in (("track", []), ("wind_areas", {}), ("cone", []))}
    doc = build_doc(prev, fresh, geo, failed, list_error, now, url)
    write_doc(data_dir, doc)
    size = len(dumps(doc).encode("utf-8"))
    line = (f"wrote {FILE_NAME}: {len(doc['items'])} storms, {size} bytes, {fetched} geometry requests"
            + ("" if doc["ok"] else " - " + (doc["message_th"] or "failed")))
    print(line)
    if not doc["ok"] and fresh is not None and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::{line}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"### Storms\n{line}\n\n")
        except OSError:
            pass
    return 0 if fresh is not None else 1


def check(data_dir: pathlib.Path = DATA_DIR) -> int:
    path = data_dir / FILE_NAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"storms check: INVALID - cannot read {path}: {e}")
        return 1
    errs = validate(doc)
    if errs:
        print("storms check: INVALID\n  " + "\n  ".join(errs[:10]))
        return 1
    print(f"storms check: OK - {len(doc['items'])} storms (updated {doc['updated']}, ok={doc['ok']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="validate the current file only; no network")
    ap.add_argument("--data-dir", type=pathlib.Path, default=DATA_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.check:
        return check(args.data_dir)
    return run(args.data_dir)


if __name__ == "__main__":
    sys.exit(main())
