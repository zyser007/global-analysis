#!/usr/bin/env python3
"""Refresh site/data/disasters.json from GDACS and USGS (free public feeds, no AI, no API key).

    python updater/disasters.py              # fetch both feeds, write site/data/disasters.json
    python updater/disasters.py --check      # validate the current file only (no network)

Feeds
- GDACS (Global Disaster Alert and Coordination System, EC JRC + UN OCHA), event search API:
  earthquakes, tropical cyclones, floods, volcanoes, wildfires and droughts with an alert level.
  We ask for orange and red events only.
- USGS earthquake summary feed, M4.5+ of the past 7 days (GeoJSON). We keep the quakes USGS
  itself counts as significant (`sig` >= 600, the threshold of its "significant" feed) or with a
  PAGER alert of yellow or higher.

Rules
- Events that ended long ago are dropped (MAX_AGE_DAYS per type, counted from the event's end).
- A quake that is in both feeds (time within 3 min, epicentre within 150 km) is kept once, as the
  GDACS event, with the USGS event page as a second source.
- Order: red, orange, yellow, green, no alert; then newest start first. At most MAX_ITEMS.
- Titles are Thai, built from templates (no AI). Country names go through a small table and fall
  back to the English name.
- The document is validated against updater/schema/disasters.schema.json and written atomically.
  When one feed fails (network, HTTP error, junk), that feed's events from the previous file are
  kept (still age-filtered) and `feeds.<name>.ok` / `message_th` say so; the other feed's events
  are refreshed. When both fail, the items and `updated` stay as they were, `ok` is false and the
  exit code is 1. Exit code 0 otherwise.
- Python standard library for fetching; jsonschema (already pinned in requirements.txt) to validate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import pathlib
import re
import sys
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
SCHEMA_PATH = ROOT / "updater" / "schema" / "disasters.schema.json"
FILE_NAME = "disasters.json"

GDACS_SEARCH = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
GDACS_TYPES = ("EQ", "TC", "FL", "VO", "WF", "DR")
GDACS_WINDOW_DAYS = 45               # search window (GDACS matches events still running inside it)
USGS_FEED = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_week.geojson"
USGS_MIN_SIG = 600                   # USGS "significant earthquakes" threshold
USGS_PAGER_MIN = "yellow"            # ... or a PAGER alert at least this high
USER_AGENT = "world-globe-live/1.0 (+https://zyser007.github.io/global-analysis/; disasters.py)"
TIMEOUT_S = 30
MAX_BYTES = 8 * 1024 * 1024
MAX_ITEMS = 30
MAX_AGE_DAYS = {"earthquake": 14, "cyclone": 7, "flood": 14, "volcano": 14, "wildfire": 10, "drought": 31}
DEDUP_SECONDS = 180
DEDUP_KM = 150

TYPE_OF = {"EQ": "earthquake", "TC": "cyclone", "FL": "flood", "VO": "volcano", "WF": "wildfire", "DR": "drought"}
TYPE_TH = {"earthquake": "แผ่นดินไหว", "cyclone": "พายุหมุนเขตร้อน", "flood": "น้ำท่วม",
           "volcano": "ภูเขาไฟ", "wildfire": "ไฟป่า", "drought": "ภัยแล้ง"}
ALERT_RANK = {"red": 0, "orange": 1, "yellow": 2, "green": 3, None: 4}
FEEDS = ("gdacs", "usgs")
SOURCE_NAME = {"gdacs": "GDACS", "usgs": "USGS"}
FEED_TH = {"gdacs": "GDACS", "usgs": "USGS"}

# English (as GDACS / USGS spell it) -> Thai. Unknown names stay in English.
COUNTRY_TH = {
    "afghanistan": "อัฟกานิสถาน", "albania": "แอลเบเนีย", "algeria": "แอลจีเรีย", "andorra": "อันดอร์รา",
    "angola": "แองโกลา", "argentina": "อาร์เจนตินา", "armenia": "อาร์มีเนีย", "australia": "ออสเตรเลีย",
    "austria": "ออสเตรีย", "azerbaijan": "อาเซอร์ไบจาน", "bangladesh": "บังกลาเทศ", "belarus": "เบลารุส",
    "belgium": "เบลเยียม", "belize": "เบลีซ", "benin": "เบนิน", "bhutan": "ภูฏาน", "bolivia": "โบลิเวีย",
    "bosnia & herzegovina": "บอสเนียและเฮอร์เซโกวีนา", "bosnia and herzegovina": "บอสเนียและเฮอร์เซโกวีนา",
    "botswana": "บอตสวานา", "brazil": "บราซิล", "brunei": "บรูไน", "bulgaria": "บัลแกเรีย",
    "burkina faso": "บูร์กินาฟาโซ", "burundi": "บุรุนดี", "cambodia": "กัมพูชา", "cameroon": "แคเมอรูน",
    "canada": "แคนาดา", "central african republic": "สาธารณรัฐแอฟริกากลาง", "chad": "ชาด", "chile": "ชิลี",
    "china": "จีน", "colombia": "โคลอมเบีย", "costa rica": "คอสตาริกา", "croatia": "โครเอเชีย", "cuba": "คิวบา",
    "cyprus": "ไซปรัส", "czech republic": "เช็กเกีย", "czechia": "เช็กเกีย",
    "democratic republic of congo": "คองโก (กินชาซา)", "democratic republic of the congo": "คองโก (กินชาซา)",
    "denmark": "เดนมาร์ก", "djibouti": "จิบูตี", "dominican republic": "สาธารณรัฐโดมินิกัน", "ecuador": "เอกวาดอร์",
    "egypt": "อียิปต์", "el salvador": "เอลซัลวาดอร์", "eritrea": "เอริเทรีย", "estonia": "เอสโตเนีย",
    "ethiopia": "เอธิโอเปีย", "fiji": "ฟิจิ", "finland": "ฟินแลนด์", "france": "ฝรั่งเศส", "gabon": "กาบอง",
    "georgia": "จอร์เจีย", "germany": "เยอรมนี", "ghana": "กานา", "greece": "กรีซ", "guam": "กวม",
    "guatemala": "กัวเตมาลา", "guinea": "กินี", "guyana": "กายอานา", "haiti": "เฮติ", "honduras": "ฮอนดูรัส",
    "hong kong": "ฮ่องกง", "hungary": "ฮังการี", "iceland": "ไอซ์แลนด์", "india": "อินเดีย",
    "indonesia": "อินโดนีเซีย", "iran": "อิหร่าน", "iraq": "อิรัก", "ireland": "ไอร์แลนด์", "israel": "อิสราเอล",
    "italy": "อิตาลี", "jamaica": "จาเมกา", "japan": "ญี่ปุ่น", "jordan": "จอร์แดน", "kazakhstan": "คาซัคสถาน",
    "kenya": "เคนยา", "kyrgyzstan": "คีร์กีซสถาน", "laos": "ลาว", "lao people's democratic republic": "ลาว",
    "latvia": "ลัตเวีย", "lebanon": "เลบานอน", "liechtenstein": "ลิกเตนสไตน์", "libya": "ลิเบีย",
    "lithuania": "ลิทัวเนีย", "luxembourg": "ลักเซมเบิร์ก", "madagascar": "มาดากัสการ์", "malawi": "มาลาวี",
    "malaysia": "มาเลเซีย", "mali": "มาลี", "marshall islands": "หมู่เกาะมาร์แชลล์", "mauritania": "มอริเตเนีย",
    "mexico": "เม็กซิโก", "micronesia": "ไมโครนีเซีย", "moldova": "มอลโดวา", "mongolia": "มองโกเลีย",
    "montenegro": "มอนเตเนโกร", "morocco": "โมร็อกโก", "mozambique": "โมซัมบิก", "myanmar": "เมียนมา",
    "namibia": "นามิเบีย", "nepal": "เนปาล", "netherlands": "เนเธอร์แลนด์", "new caledonia": "นิวแคลิโดเนีย",
    "new zealand": "นิวซีแลนด์", "nicaragua": "นิการากัว", "niger": "ไนเจอร์", "nigeria": "ไนจีเรีย",
    "north korea": "เกาหลีเหนือ", "northern mariana islands": "หมู่เกาะนอร์เทิร์นมาเรียนา",
    "norway": "นอร์เวย์", "oman": "โอมาน", "pakistan": "ปากีสถาน", "panama": "ปานามา",
    "papua new guinea": "ปาปัวนิวกินี", "paraguay": "ปารากวัย", "peru": "เปรู", "philippines": "ฟิลิปปินส์",
    "poland": "โปแลนด์", "portugal": "โปรตุเกส", "puerto rico": "เปอร์โตริโก", "romania": "โรมาเนีย",
    "russia": "รัสเซีย", "rwanda": "รวันดา", "samoa": "ซามัว", "saudi arabia": "ซาอุดีอาระเบีย",
    "senegal": "เซเนกัล", "serbia": "เซอร์เบีย", "singapore": "สิงคโปร์", "slovakia": "สโลวาเกีย",
    "slovenia": "สโลวีเนีย", "solomon islands": "หมู่เกาะโซโลมอน", "somalia": "โซมาเลีย",
    "south africa": "แอฟริกาใต้", "south korea": "เกาหลีใต้", "south sudan": "ซูดานใต้", "spain": "สเปน",
    "sri lanka": "ศรีลังกา", "sudan": "ซูดาน", "sweden": "สวีเดน", "switzerland": "สวิตเซอร์แลนด์",
    "syria": "ซีเรีย", "taiwan": "ไต้หวัน", "tajikistan": "ทาจิกิสถาน", "tanzania": "แทนซาเนีย",
    "thailand": "ไทย", "timor-leste": "ติมอร์-เลสเต", "east timor": "ติมอร์-เลสเต", "togo": "โตโก",
    "tonga": "ตองกา", "tunisia": "ตูนิเซีย", "turkey": "ตุรกี", "turkiye": "ตุรกี", "turkmenistan": "เติร์กเมนิสถาน",
    "uganda": "ยูกันดา", "ukraine": "ยูเครน", "united arab emirates": "สหรัฐอาหรับเอมิเรตส์",
    "united kingdom": "สหราชอาณาจักร", "united states": "สหรัฐฯ", "uruguay": "อุรุกวัย", "uzbekistan": "อุซเบกิสถาน",
    "vanuatu": "วานูอาตู", "venezuela": "เวเนซุเอลา", "vietnam": "เวียดนาม", "viet nam": "เวียดนาม",
    "yemen": "เยเมน", "zambia": "แซมเบีย", "zimbabwe": "ซิมบับเว",
    # regions (GDACS drought names, USGS places)
    "europe": "ยุโรป", "central america": "อเมริกากลาง", "south america": "อเมริกาใต้", "east africa": "แอฟริกาตะวันออก",
    "west africa": "แอฟริกาตะวันตก", "southern africa": "แอฟริกาตอนใต้", "central sahel": "ซาเฮลตอนกลาง",
    "sahel": "ซาเฮล", "middle east": "ตะวันออกกลาง", "southeast asia": "เอเชียตะวันออกเฉียงใต้",
    "south asia": "เอเชียใต้", "central asia": "เอเชียกลาง", "east asia": "เอเชียตะวันออก",
    "horn of africa": "จะงอยแอฟริกา", "north africa": "แอฟริกาเหนือ", "caribbean": "แคริบเบียน",
    "easter island": "เกาะอีสเตอร์", "mid-atlantic ridge": "สันเขากลางมหาสมุทรแอตแลนติก",
    "bonin islands": "หมู่เกาะโบนิน", "kuril islands": "หมู่เกาะคูริล", "fiji region": "ภูมิภาคฟิจิ",
    "kermadec islands": "หมู่เกาะเคอร์มาเดก", "south sandwich islands": "หมู่เกาะเซาท์แซนด์วิช",
    "aleutian islands": "หมู่เกาะอะลูเชียน", "tonga region": "ภูมิภาคตองกา",
}
# USGS writes US places as "..., CA" / "..., Alaska"
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "Alaska", "Hawaii", "California", "Nevada", "Oregon",
    "Washington", "Idaho", "Montana", "Utah", "Wyoming", "Texas", "Oklahoma", "New Mexico", "Arizona",
}

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class FeedError(Exception):
    """A feed could not be used this round (network, HTTP status, junk)."""


# ----------------------------------------------------------------- helpers
def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(v: Any) -> dt.datetime | None:
    """GDACS '2026-11-02T15:35:12' (UTC, no zone), ISO with Z/offset, or USGS epoch milliseconds."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        try:
            return dt.datetime.fromtimestamp(v / 1000.0, dt.timezone.utc).replace(microsecond=0)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(v).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        t = dt.datetime.fromisoformat(s)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t.astimezone(dt.timezone.utc).replace(microsecond=0)


def num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def clean(s: Any, limit: int = 300) -> str:
    """Single spaces, no raw double quotes, length-capped."""
    s = re.sub(r"\s+", " ", str(s or "")).strip().replace('"', "”")
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def _key(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", n).strip().lower()


def country_th(name: str) -> str:
    """Thai name from the table; strips 'central ' / ' region' style qualifiers; falls back to English."""
    name = clean(name, 120)
    if not name:
        return ""
    k = _key(name)
    if k in COUNTRY_TH:
        return COUNTRY_TH[k]
    for pre in ("central ", "northern ", "southern ", "eastern ", "western ", "off the coast of ", "near the coast of "):
        if k.startswith(pre) and k[len(pre):] in COUNTRY_TH:
            return COUNTRY_TH[k[len(pre):]]
    if k.endswith(" region") and k[:-7] in COUNTRY_TH:
        return COUNTRY_TH[k[:-7]]
    return name


def places_th(names: list[str], limit: int = 3) -> str:
    """'ญี่ปุ่น จีน กวม และอีก 2 แห่ง' (Thai lists are space-separated)."""
    th = [country_th(n) for n in names if n]
    if len(th) <= limit:
        return " ".join(th)
    return " ".join(th[:limit]) + f" และอีก {len(th) - limit} แห่ง"


def fmt_int(v: float) -> str:
    return f"{round(v):,}"


def fmt_area_km2(v: float) -> str:
    if v >= 1_000_000:
        return f"ราว {v / 1_000_000:.1f} ล้าน ตร.กม."
    return f"ราว {fmt_int(v)} ตร.กม."


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def _coords(feature: dict) -> tuple[float, float] | None:
    g = feature.get("geometry") or {}
    c = g.get("coordinates") if isinstance(g, dict) else None
    if not isinstance(c, list) or len(c) < 2:
        return None
    lon, lat = num(c[0]), num(c[1])
    if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return None
    return round(lat, 4), round(lon, 4)


# ----------------------------------------------------------------- fetching
def http_get(url: str, timeout: float = TIMEOUT_S) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URLs above
        body = r.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise FeedError(f"response larger than {MAX_BYTES} bytes")
        return r.status, body


Fetcher = Callable[[str], tuple[int, bytes]]


def gdacs_url(now: dt.datetime) -> str:
    q = {"eventlist": ";".join(GDACS_TYPES), "alertlevel": "orange;red",
         "fromDate": (now - dt.timedelta(days=GDACS_WINDOW_DAYS)).strftime("%Y-%m-%d"),
         "toDate": (now + dt.timedelta(days=1)).strftime("%Y-%m-%d"), "pagesize": "100", "pagenumber": "1"}
    return GDACS_SEARCH + "?" + urllib.parse.urlencode(q, safe=";")


def _get_json(fetch: Fetcher, url: str, empty_ok: bool = False) -> Any:
    try:
        status, body = fetch(url)
    except FeedError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as e:  # HTTPError is a URLError
        raise FeedError(f"{type(e).__name__}: {e}") from e
    if status == 204 and empty_ok:
        return None
    if status != 200:
        raise FeedError(f"HTTP {status}")
    try:
        return json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as e:
        raise FeedError(f"not JSON: {e}") from e


def _features(doc: Any) -> list:
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection" or not isinstance(doc.get("features"), list):
        raise FeedError("not a GeoJSON FeatureCollection")
    return doc["features"]


def _check_parsed(name: str, raw: int, ok: int) -> None:
    if raw and ok * 2 < raw:
        raise FeedError(f"{name}: only {ok} of {raw} events could be read")


# ----------------------------------------------------------------- GDACS
def _gdacs_title(typ: str, p: dict, countries: list[str]) -> tuple[str, str, float | None, str]:
    """-> (title_th, severity_th, severity_value, severity_unit)"""
    sev = p.get("severitydata") if isinstance(p.get("severitydata"), dict) else {}
    value, unit, text = num(sev.get("severity")), clean(sev.get("severityunit"), 20), clean(sev.get("severitytext"), 200)
    where = places_th(countries)
    loc = f"ใน{where}" if where else ""
    name = clean(p.get("eventname"), 60)
    if typ == "earthquake":
        depth = re.search(r"Depth:\s*([0-9.]+)\s*km", text)
        mag = f"{value:.1f}" if value else ""
        sev_th = (f"ขนาด {mag}" if mag else "") + (f" ลึก {float(depth.group(1)):.0f} กม." if depth else "")
        title = f"แผ่นดินไหว{'ขนาด ' + mag if mag else ''} {loc}"
        return clean(title), sev_th.strip(), value, "M" if value else ""
    if typ == "cyclone":
        nm = name or clean(re.sub(r"^Tropical Cyclone\s+", "", str(p.get("name") or "")), 60)
        wind = f"{value:.0f}" if value else ""
        sev_th = f"ลมสูงสุด {wind} กม./ชม." if wind else ""
        title = f"พายุหมุนเขตร้อน {nm} {sev_th} {'กระทบ' + where if where else ''}"
        return clean(title), sev_th, value, "km/h" if value else ""
    if typ == "volcano":
        nm = name or clean(re.sub(r"^Eruption\s+", "", str(p.get("name") or "")), 60)
        title = f"ภูเขาไฟ {nm} ปะทุ {loc}" if nm else f"ภูเขาไฟปะทุ {loc}"
        return clean(title), "", None, ""
    if typ == "wildfire":
        sev_th = f"พื้นที่ไหม้ราว {fmt_int(value)} เฮกตาร์" if value and unit == "ha" else ""
        return clean(f"ไฟป่า{loc} {sev_th}"), sev_th, value if sev_th else None, "ha" if sev_th else ""
    if typ == "drought":
        sev_th = f"ภัยแล้งด้านการเกษตร พื้นที่{fmt_area_km2(value)}" if value and unit == "km2" else ""
        region = re.sub(r"-\d{4}$", "", name).strip()
        parts = [r.strip() for r in region.split(",") if r.strip()]
        region_th = " ".join(country_th(r) for r in parts) if parts and all(_key(r) in COUNTRY_TH for r in parts) else ""
        n = len(countries)
        if region_th and n > 1:
            title = f"ภัยแล้งใน{region_th} ครอบคลุม {n} ประเทศ"
        else:
            title = f"ภัยแล้ง{loc}"
        return clean(title), sev_th, value if sev_th else None, "km2" if sev_th else ""
    # flood: the GDACS list gives no usable size ("Magnitude 0")
    return clean(f"น้ำท่วม{loc}"), "", None, ""


def parse_gdacs(doc: Any, now: dt.datetime) -> list[dict]:
    """GDACS SEARCH GeoJSON -> items (orange/red only, not too old). Raises FeedError on junk."""
    if doc is None:          # HTTP 204: no events in the window
        return []
    feats = _features(doc)
    items, readable = [], 0
    for f in feats:
        try:
            it = _gdacs_item(f)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if it is None:
            continue
        readable += 1
        if it["alert_level"] in ("orange", "red") and not too_old(it, now):
            items.append(it)
    _check_parsed("GDACS", len(feats), readable)
    return items


def _gdacs_item(f: dict) -> dict | None:
    p = f["properties"]
    code = str(p["eventtype"]).upper()
    typ = TYPE_OF.get(code)
    eid = p.get("eventid")
    pos = _coords(f)
    start, end = parse_time(p.get("fromdate")), parse_time(p.get("todate"))
    if typ is None or not isinstance(eid, int) or pos is None or start is None:
        return None
    end = end or start
    upd = parse_time(p.get("datemodified")) or end
    alert = str(p.get("alertlevel") or "").strip().lower() or None
    if alert not in ALERT_RANK:
        return None
    countries = [clean(c.get("countryname"), 80) for c in (p.get("affectedcountries") or []) if isinstance(c, dict) and c.get("countryname")]
    if not countries:
        countries = [c.strip() for c in str(p.get("country") or "").split(",") if c.strip()]
    title, sev_th, sev_v, sev_u = _gdacs_title(typ, p, countries)
    url = ((p.get("url") or {}).get("report") if isinstance(p.get("url"), dict) else None) \
        or f"https://www.gdacs.org/report.aspx?eventtype={code}&eventid={eid}"
    url = str(url).replace("http://", "https://", 1)
    return {
        "id": f"gdacs-{code.lower()}-{eid}",
        "type": typ,
        "title_th": title,
        "country": countries[0] if countries else "",
        "country_th": places_th(countries),
        "countries": countries[:40],
        "lat": pos[0], "lon": pos[1],
        "start": iso(start), "end": iso(max(end, start)), "updated": iso(max(upd, start)),
        "alert_level": alert,
        "severity_th": sev_th,
        "severity_value": round(sev_v, 2) if sev_v is not None else None,
        "severity_unit": sev_u,
        "source_url": url,
        "source_name": "GDACS",
    }


# ----------------------------------------------------------------- USGS
def _usgs_place(place: str) -> tuple[str, str]:
    """'165 km NW of Port-Olry, Vanuatu' -> ('Vanuatu', 'วานูอาตู'); 'southeast of Easter Island' -> ('', 'เกาะอีสเตอร์')."""
    place = clean(place, 160)
    if "," in place:
        tail = place.rsplit(",", 1)[1].strip()
        tail = re.sub(r"\s+region$", "", tail)
        if tail in US_STATES:
            return "United States", "สหรัฐฯ"
        return tail, country_th(tail)
    tail = re.sub(r"^.*\bof\s+", "", place).strip()
    return "", country_th(tail)


def parse_usgs(doc: Any, now: dt.datetime) -> list[dict]:
    feats = _features(doc)
    meta = doc.get("metadata") if isinstance(doc, dict) else None
    if isinstance(meta, dict) and meta.get("status") not in (None, 200):
        raise FeedError(f"USGS metadata status {meta.get('status')}")
    items, readable = [], 0
    for f in feats:
        try:
            it = _usgs_item(f)
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
        if it is None:
            continue
        readable += 1
        sig, alert = it.pop("_sig"), it["alert_level"]
        notable = (sig is not None and sig >= USGS_MIN_SIG) or ALERT_RANK.get(alert, 9) <= ALERT_RANK[USGS_PAGER_MIN]
        if notable and not too_old(it, now):
            items.append(it)
    _check_parsed("USGS", len(feats), readable)
    return items


def _usgs_item(f: dict) -> dict | None:
    p = f["properties"]
    if str(p.get("type") or "earthquake") != "earthquake":
        return None
    fid = str(f.get("id") or "")
    mag, pos, t = num(p.get("mag")), _coords(f), parse_time(p.get("time"))
    if not re.fullmatch(r"[a-z0-9]{4,40}", fid) or mag is None or pos is None or t is None:
        return None
    upd = parse_time(p.get("updated")) or t
    alert = p.get("alert")
    alert = str(alert).lower() if alert else None
    if alert not in ALERT_RANK:
        alert = None
    country, where = _usgs_place(str(p.get("place") or ""))
    depth = None
    c = (f.get("geometry") or {}).get("coordinates") or []
    if len(c) > 2:
        depth = num(c[2])
    sev_th = f"ขนาด {mag:.1f}" + (f" ลึก {depth:.0f} กม." if depth is not None else "")
    title = f"แผ่นดินไหวขนาด {mag:.1f} " + ((f"ใน{where}" if country else f"บริเวณ{where}") if where else "")
    url = str(p.get("url") or f"https://earthquake.usgs.gov/earthquakes/eventpage/{fid}")
    if not url.startswith("https://"):
        url = f"https://earthquake.usgs.gov/earthquakes/eventpage/{fid}"
    sig = num(p.get("sig"))
    return {
        "id": f"usgs-{fid}",
        "type": "earthquake",
        "title_th": clean(title),
        "country": country,
        "country_th": where,
        "countries": [country] if country else [],
        "lat": pos[0], "lon": pos[1],
        "start": iso(t), "end": iso(t), "updated": iso(max(upd, t)),
        "alert_level": alert,
        "severity_th": sev_th,
        "severity_value": round(mag, 2),
        "severity_unit": "M",
        "source_url": url,
        "source_name": "USGS",
        "_sig": sig,
    }


# ----------------------------------------------------------------- combine
def too_old(it: dict, now: dt.datetime) -> bool:
    end = parse_time(it.get("end")) or parse_time(it.get("start"))
    if end is None:
        return True
    return now - end > dt.timedelta(days=MAX_AGE_DAYS.get(it.get("type"), 14))


def same_quake(a: dict, b: dict) -> bool:
    if a["type"] != "earthquake" or b["type"] != "earthquake":
        return False
    ta, tb = parse_time(a["start"]), parse_time(b["start"])
    if ta is None or tb is None or abs((ta - tb).total_seconds()) > DEDUP_SECONDS:
        return False
    return haversine_km(a["lat"], a["lon"], b["lat"], b["lon"]) <= DEDUP_KM


def dedupe(gdacs: list[dict], usgs: list[dict]) -> tuple[list[dict], list[dict], int]:
    """A quake in both feeds stays once: the GDACS event, with the USGS page as a second source and
    the higher of the two alert levels. Returns (gdacs, remaining usgs, merged count)."""
    out_g = [dict(g) for g in gdacs]
    rest, merged = [], 0
    for u in usgs:
        match = next((g for g in out_g if same_quake(g, u)), None)
        if match is None:
            rest.append(u)
            continue
        merged += 1
        match["alt_source_url"] = u["source_url"]
        match["alt_source_name"] = u["source_name"]
        if ALERT_RANK.get(u["alert_level"], 9) < ALERT_RANK.get(match["alert_level"], 9):
            match["alert_level"] = u["alert_level"]
    return out_g, rest, merged


def sort_key(it: dict) -> tuple:
    t = parse_time(it.get("start"))
    return (ALERT_RANK.get(it.get("alert_level"), 9), -(t.timestamp() if t else 0), it["id"])


def _by_feed(items: list[dict], feed: str) -> list[dict]:
    return [i for i in items if i.get("source_name") == SOURCE_NAME[feed]]


def build_doc(prev: dict | None, fresh: dict[str, list[dict] | None], errors: dict[str, str], now: dt.datetime,
              urls: dict[str, str]) -> dict:
    """fresh[feed] is None when that feed failed; its previous events are then kept (age-filtered)."""
    prev_items = list((prev or {}).get("items") or [])
    prev_feeds = (prev or {}).get("feeds") or {}
    parts: dict[str, list[dict]] = {}
    for feed in FEEDS:
        if fresh.get(feed) is not None:
            parts[feed] = list(fresh[feed])
        else:
            parts[feed] = [dict(i) for i in _by_feed(prev_items, feed) if not too_old(i, now)]
    # dedupe again over the combined set; with fresh USGS data, old USGS links on kept GDACS quakes are recomputed
    if fresh.get("usgs") is not None:
        for g in parts["gdacs"]:
            g.pop("alt_source_url", None)
            g.pop("alt_source_name", None)
    g_items, u_items, _ = dedupe(parts["gdacs"], parts["usgs"])
    items = sorted(g_items + u_items, key=sort_key)[:MAX_ITEMS]
    ok_all = all(fresh.get(f) is not None for f in FEEDS)
    any_ok = any(fresh.get(f) is not None for f in FEEDS)
    feeds = {}
    for feed in FEEDS:
        old = prev_feeds.get(feed) if isinstance(prev_feeds.get(feed), dict) else {}
        ok = fresh.get(feed) is not None
        feeds[feed] = {
            "ok": ok,
            "fetched": iso(now) if ok else old.get("fetched"),
            "count": len([i for i in items if i["source_name"] == SOURCE_NAME[feed]]),
            "url": urls[feed],
        }
        if not ok:
            feeds[feed]["error"] = clean(errors.get(feed) or "unknown error", 200)
    failed = [FEED_TH[f] for f in FEEDS if fresh.get(f) is None]
    if not failed:
        msg = ""
    elif any_ok:
        msg = f"โหลดข้อมูลจาก {' และ '.join(failed)} ไม่สำเร็จรอบนี้ แสดงเหตุการณ์จากรอบก่อนของแหล่งนั้น"
    else:
        msg = "โหลดข้อมูลภัยพิบัติไม่สำเร็จทุกแหล่งรอบนี้ แสดงรายการล่าสุดที่ได้รับ"
    updated = iso(now) if any_ok else ((prev or {}).get("updated") or iso(now))
    return {"updated": updated, "checked": iso(now), "ok": ok_all, "message_th": msg, "feeds": feeds, "items": items}


# ----------------------------------------------------------------- validate + write
_validator: Any = None


def validate(doc: Any) -> list[str]:
    global _validator
    import jsonschema  # pinned in updater/requirements.txt

    if _validator is None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        _validator = jsonschema.Draft202012Validator(schema)
    errs = [f"disasters: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in _validator.iter_errors(doc)]
    if errs:
        return errs
    ids = [i["id"] for i in doc["items"]]
    if len(set(ids)) != len(ids):
        errs.append("disasters: duplicate ids")
    if [i["id"] for i in sorted(doc["items"], key=sort_key)] != ids:
        errs.append("disasters: items are not in alert / newest order")
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
    fd, tmp = tempfile.mkstemp(prefix=".disasters.", suffix=".json.tmp", dir=data_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
        os.replace(tmp, data_dir / FILE_NAME)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


# ----------------------------------------------------------------- run
def run(data_dir: pathlib.Path = DATA_DIR, fetch: Fetcher = http_get, now: dt.datetime | None = None) -> int:
    now = now or utcnow()
    prev, why = load_previous(data_dir)
    if prev is None and why != "no previous file":
        print(f"previous {FILE_NAME} unusable ({why}); starting from an empty list", file=sys.stderr)
    urls = {"gdacs": gdacs_url(now), "usgs": USGS_FEED}
    fresh: dict[str, list[dict] | None] = {}
    errors: dict[str, str] = {}
    parsers = {"gdacs": lambda: parse_gdacs(_get_json(fetch, urls["gdacs"], empty_ok=True), now),
               "usgs": lambda: parse_usgs(_get_json(fetch, urls["usgs"]), now)}
    for feed in FEEDS:
        try:
            fresh[feed] = parsers[feed]()
            print(f"{SOURCE_NAME[feed]}: {len(fresh[feed])} events kept")
        except FeedError as e:
            fresh[feed], errors[feed] = None, str(e)
            print(f"{SOURCE_NAME[feed]}: FAILED - {e}", file=sys.stderr)
    any_ok = any(v is not None for v in fresh.values())
    if not any_ok and prev is None:
        print(f"both feeds failed and there is no valid previous file; {FILE_NAME} not written", file=sys.stderr)
        return 1
    doc = build_doc(prev, fresh, errors, now, urls)
    write_doc(data_dir, doc)
    merged = sum(1 for i in doc["items"] if i.get("alt_source_url"))
    line = (f"wrote {FILE_NAME}: {len(doc['items'])} events "
            f"(GDACS {doc['feeds']['gdacs']['count']}, USGS {doc['feeds']['usgs']['count']}, in both {merged})"
            + ("" if doc["ok"] else f" - {', '.join(f for f in FEEDS if fresh.get(f) is None)} failed, previous events kept"))
    print(line)
    if not doc["ok"] and any_ok and os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::warning::{line}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        try:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"### Disasters\n{line}\n\n")
        except OSError:
            pass
    return 0 if any_ok else 1


def check(data_dir: pathlib.Path = DATA_DIR) -> int:
    path = data_dir / FILE_NAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"disasters check: INVALID - cannot read {path}: {e}")
        return 1
    errs = validate(doc)
    if errs:
        print("disasters check: INVALID\n  " + "\n  ".join(errs[:10]))
        return 1
    print(f"disasters check: OK - {len(doc['items'])} events (updated {doc['updated']}, ok={doc['ok']})")
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
