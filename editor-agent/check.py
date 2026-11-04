#!/usr/bin/env python3
"""Validators for the editor agent (data/world-data.json, data/gold.json and the run files).

Default (no flags)  schema + consistency of the two data files (works on the current files, no network)
--live              health of the live layer the GitHub Actions bot writes (site/data/*.json, cost log)
--base REF          compare the data files with git REF (default HEAD) and require that every changed
                    item is listed, with dated source URLs, in editor-agent/runs/<run-date>.changes.json
--run-date DAY      the run's Bangkok date (YYYY-MM-DD); with --base it also requires the run files
                    and that meta dates were moved to the run date
--page              site/index.html embeds exactly data/world-data.json + data/gold.json (rebuilt)
--scope             files changed since --base (ignoring commits by the Actions bot) stay inside the
                    editor agent's allowed paths
--all               --live --page --scope together (use with --base and --run-date at the end of a run)

Prints one line per finding: "ERROR <where>: <what>" or "WARN <where>: <what>", then a summary.
Exit code 1 if there is any ERROR (or any WARN with --strict). --json prints the findings as JSON.

Run:  python3 -I editor-agent/check.py [flags]          (stdlib + jsonschema only, no network)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
HERE = ROOT / "editor-agent"
WORLD = "data/world-data.json"
GOLD = "data/gold.json"
PAGE = "site/index.html"
RUNS = "editor-agent/runs"
LIVE_DIR = "site/data"
HEADLINES_SCHEMA = "updater/schema/headlines.schema.json"
COST_LOG = "updater/cost-log.csv"
BKK = dt.timezone(dt.timedelta(hours=7))
BOT_EMAILS = {"41898283+github-actions[bot]@users.noreply.github.com", "github-actions[bot]@users.noreply.github.com"}

TH_MONTH_ABBR = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
TH_MONTH_FULL = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม",
                 "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]
EN_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec"]
# relative-time words that go stale the next day unless a date sits next to them
NOW_WORDS_TH = ["ล่าสุด", "ขณะนี้", "ปัจจุบัน", "ตอนนี้", "วันนี้", "เมื่อวาน", "พรุ่งนี้", "สัปดาห์นี้", "สัปดาห์หน้า",
                "สัปดาห์ที่แล้ว", "เดือนนี้", "เดือนหน้า", "เดือนที่แล้ว", "ปลายเดือน", "ต้นเดือน", "ปีนี้"]
NOW_WORDS_EN = ["now", "latest", "current", "currently", "today", "yesterday", "tomorrow", "this week", "next week"]
# words that are fine in running text when they sit right next to an explicit date
TEXT_NOW_WORDS = ["วันนี้", "เมื่อวาน", "พรุ่งนี้", "ขณะนี้", "ตอนนี้", "สัปดาห์นี้", "สัปดาห์หน้า", "สัปดาห์ที่แล้ว"]
# headline topics that are not conflicts on the globe (updater/schema/headlines.schema.json)
PSEUDO_IDS = {"economy", "world", "disaster", "thailand"}
GOLD_META_KEYS = {"as_of", "as_of_caption_th", "updated_th", "unit", "disclaimer_th", "sources"}
ALLOWED_RUN_FILE = re.compile(r"^editor-agent/runs/\d{4}-\d{2}-\d{2}(\.md|\.changes\.json)$")
ALLOWED_FILES = {WORLD, GOLD, PAGE}
# counts the page layout was designed for (overview tiles, lists); a change is allowed but worth a look. (e2e itself
# runs on frozen fixture data in e2e/fixtures/, so data changes no longer break it.)
E2E_COUNTS = {"conflicts": 25, "economies": 21, "indicators": 20, "analysis_th.points": 6, "analysis_th.risks": 4,
              "gold.forecasts.items": 6}


# Sources that may not back a fact (blogs, newsletters, social posts, SEO / market-commentary aggregators,
# chart and quote pages). A listed domain also covers its subdomains.
BLOCKED_SOURCE_DOMAINS = (
    "substack.com", "medium.com", "blogspot.com", "wordpress.com", "tumblr.com", "quora.com", "reddit.com",
    "x.com", "twitter.com", "facebook.com", "instagram.com", "tiktok.com", "threads.net",
    "pomegra.io", "financefeeds.com", "babypips.com", "hoa.org.uk", "fxstreet.com", "fxempire.com",
    "investinglive.com", "money.co.uk", "goldprice.org", "tradingview.com",
)
BLOCKED_SOURCE_PATH = re.compile(r"/(charts?|quotes?|symbols?|live-?prices?|price-?charts?)(/|$|\?)", re.I)
MAX_SOURCE_AGE_DAYS = 7


def source_problem(url: str) -> str | None:
    """Why a URL may not be used as a dated source for a fact, or None."""
    h = host(url)
    for d in BLOCKED_SOURCE_DOMAINS:
        if h == d or h.endswith("." + d):
            return "%s is a blocked source type (blog / newsletter / social / aggregator): use an established outlet or the primary source" % h
    path = re.sub(r"^https?://[^/]+", "", url.strip())
    if BLOCKED_SOURCE_PATH.search(path):
        return "%s is a chart or quote page, not a dated report: cite the news article or the official release" % url
    return None


def entry_source_problems(e: dict, run_date: dt.date) -> list[str]:
    """Problems with the sources of one changes.json entry (blocked sources, stale or future dates)."""
    out = []
    days = []
    for s in e.get("sources", []) or []:
        p = source_problem(str(s.get("url", "")))
        if p:
            out.append(p)
        d = parse_day(s.get("published", ""))
        if d is not None:
            if d > run_date:
                out.append("source %s is dated %s, after the run date" % (s.get("url"), d))
            days.append(d)
    if days and (run_date - max(days)).days > MAX_SOURCE_AGE_DAYS:
        if not (e.get("confidence") == "low" and str(e.get("stale_reason_th") or "").strip()):
            out.append("newest source is %s, more than %d days before the run: find a current source, or set confidence low and "
                       "stale_reason_th explaining why no newer one exists" % (max(days), MAX_SOURCE_AGE_DAYS))
    return out


# ----------------------------------------------------------------------------- helpers
class Findings:
    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def error(self, where: str, what: str) -> None:
        self.items.append({"level": "ERROR", "where": where, "what": what})

    def warn(self, where: str, what: str) -> None:
        self.items.append({"level": "WARN", "where": where, "what": what})

    def info(self, where: str, what: str) -> None:
        self.items.append({"level": "INFO", "where": where, "what": what})

    @property
    def errors(self) -> list[dict[str, str]]:
        return [i for i in self.items if i["level"] == "ERROR"]

    @property
    def warnings(self) -> list[dict[str, str]]:
        return [i for i in self.items if i["level"] == "WARN"]


def thai_date(d: dt.date) -> str:
    """2026-11-02 -> '2 พ.ย. 2569' (the form the page and the data use)."""
    return "%d %s %d" % (d.day, TH_MONTH_ABBR[d.month - 1], d.year + 543)


def parse_day(s: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def parse_instant(s: str) -> dt.datetime | None:
    try:
        t = dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def bkk_day(t: dt.datetime) -> dt.date:
    return t.astimezone(BKK).date()


def norm_url(u: str) -> str:
    u = u.strip()
    u = re.sub(r"^http://", "https://", u)
    u = re.sub(r"^https://www\.", "https://", u)
    return u.rstrip("/")


def host(u: str) -> str:
    m = re.match(r"^https?://([^/]+)", u.strip())
    h = (m.group(1) if m else u).lower()
    return h[4:] if h.startswith("www.") else h


def has_month(text: str) -> str | None:
    for m in TH_MONTH_ABBR + TH_MONTH_FULL:
        if m in text:
            return m
    low = text.lower()
    for m in EN_MONTHS:
        if re.search(r"\b%s\b" % re.escape(m), low):
            return m
    if re.search(r"(?<!\d)(25[5-9]\d|20[2-9]\d)(?!\d)", text):
        return "a year"
    return None


def has_now_word(text: str) -> str | None:
    for w in NOW_WORDS_TH:
        if w in text:
            return w
    low = text.lower()
    for w in NOW_WORDS_EN:
        if re.search(r"\b%s\b" % re.escape(w), low):
            return w
    return None


DATE_NEAR = re.compile(r"\d{1,2}\s*(%s)|\d{4}-\d{2}-\d{2}" % "|".join(re.escape(m) for m in TH_MONTH_ABBR + TH_MONTH_FULL))


def undated_now_words(text: str) -> list[str]:
    """Relative-time words in running text with no explicit date within 25 characters."""
    out = []
    for w in TEXT_NOW_WORDS:
        for m in re.finditer(re.escape(w), text):
            window = text[max(0, m.start() - 25): m.end() + 25]
            if not DATE_NEAR.search(window):
                out.append(w)
    return out


def load_json_text(txt: str, where: str, f: Findings) -> Any:
    try:
        return json.loads(txt)
    except json.JSONDecodeError as e:
        f.error(where, "not valid JSON: %s" % e)
        return None


def read_json(root: pathlib.Path, rel: str, f: Findings, required: bool = True) -> Any:
    p = root / rel
    if not p.exists():
        if required:
            f.error(rel, "file is missing")
        return None
    return load_json_text(p.read_text(encoding="utf-8"), rel, f)


def git(root: pathlib.Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def git_show_json(root: pathlib.Path, ref: str, rel: str, f: Findings) -> Any:
    r = git(root, "show", "%s:%s" % (ref, rel))
    if r.returncode != 0:
        f.error(rel, "cannot read it at git ref %s: %s" % (ref, r.stderr.strip()[:200]))
        return None
    return load_json_text(r.stdout, "%s@%s" % (rel, ref), f)


def schema_errors(schema_name: str, doc: Any) -> list[str]:
    import jsonschema  # imported here so the date helpers stay usable without it

    schema = json.loads((HERE / "schema" / schema_name).read_text(encoding="utf-8"))
    v = jsonschema.Draft202012Validator(schema)
    out = []
    for e in sorted(v.iter_errors(doc), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append("%s: %s" % (path, e.message[:300]))
    return out


# ----------------------------------------------------------------------------- data checks
def check_world(w: dict, f: Findings, today: dt.date) -> None:
    where = WORLD
    for e in schema_errors("world-data.schema.json", w):
        f.error(where, "schema: " + e)
    if not isinstance(w, dict) or "meta" not in w:
        return
    meta = w.get("meta", {})
    title = str(meta.get("title", ""))
    if has_month(title):
        f.error(where + " meta.title", "title must not carry a month or year (%s); put the date range in meta.basis_th" % has_month(title))
    if has_now_word(title):
        f.error(where + " meta.title", "title must not use undated 'now' wording (%s)" % has_now_word(title))
    updated = parse_day(meta.get("updated", ""))
    if updated:
        if updated > today:
            f.error(where + " meta.updated", "%s is in the future (today in Bangkok is %s)" % (updated, today))
        age = (today - updated).days
        if age > 2:
            f.warn(where + " meta.updated", "background data is %d days old (%s)" % (age, updated))
        basis = meta.get("basis_th")
        if basis is None:
            f.warn(where + " meta.basis_th", "missing: the footer falls back to meta.updated only")
        elif not re.search(r"(?<!\d)%d %s" % (updated.day, re.escape(TH_MONTH_ABBR[updated.month - 1])), basis):
            f.error(where + " meta.basis_th", "%r does not end at meta.updated (%s = %s)" % (basis, updated, thai_date(updated)))
        newest = max((parse_day(i.get("as_of", "")) for i in w.get("indicators", []) if parse_day(i.get("as_of", ""))), default=None)
        if newest and newest > updated:
            f.error(where + " meta.updated", "%s is older than the newest indicator as_of (%s)" % (updated, newest))
    for i in w.get("indicators", []):
        d = parse_day(i.get("as_of", ""))
        if d and d > today:
            f.error(where + " indicators[%s]" % i.get("label_th"), "as_of %s is in the future" % d)

    for sec, key in (("conflicts", "id"), ("economies", "iso"), ("chokepoints", "name_th"), ("indicators", "label_th")):
        seen = set()
        for item in w.get(sec, []):
            k = item.get(key)
            if k in seen:
                f.error(where + " %s" % sec, "duplicate %s %r" % (key, k))
            seen.add(k)
    for sec in ("conflicts", "economies", "chokepoints"):
        for item in w.get(sec, []):
            name = str(item.get("name_th", ""))
            label = "%s[%s]" % (sec, item.get("id") or item.get("iso") or name)
            if has_month(name):
                f.error(where + " " + label, "name_th must not carry a month or year (%s)" % has_month(name))
            if has_now_word(name):
                f.error(where + " " + label, "name_th must not use undated 'now' wording (%s)" % has_now_word(name))
            for fld in ("status_th", "summary_th", "note_th"):
                words = undated_now_words(str(item.get(fld, "")))
                if words:
                    f.warn(where + " " + label + "." + fld, "relative time words with no date nearby: %s" % ", ".join(sorted(set(words))))
    for e in w.get("economies", []):
        lab = where + " economies[%s]" % e.get("iso")
        for fld, lo, hi in (("gdp_growth_2026", -30, 30), ("gdp_growth_2027", -30, 30), ("inflation", -10, 400), ("policy_rate", -2, 200)):
            v = e.get(fld)
            if isinstance(v, (int, float)) and not lo <= v <= hi:
                f.error(lab, "%s = %s is outside the plausible range %s..%s" % (fld, v, lo, hi))
    for k, n in E2E_COUNTS.items():
        if k.startswith("gold."):
            continue
        cur = w
        for part in k.split("."):
            cur = cur.get(part, []) if isinstance(cur, dict) else []
        if isinstance(cur, list) and len(cur) != n:
            f.warn(where + " " + k, "%d items, the page layout was designed for %d" % (len(cur), n))


def check_gold(g: dict, f: Findings, today: dt.date, now: dt.datetime) -> None:
    where = GOLD
    for e in schema_errors("gold.schema.json", g):
        f.error(where, "schema: " + e)
    if not isinstance(g, dict):
        return
    t = parse_instant(g.get("as_of", ""))
    if t:
        if t > now + dt.timedelta(minutes=10):
            f.error(where + " as_of", "%s is in the future" % g["as_of"])
        d = bkk_day(t)
        if thai_date(d) not in str(g.get("updated_th", "")):
            f.error(where + " updated_th", "%r does not contain the Bangkok date of as_of (%s)" % (g.get("updated_th"), thai_date(d)))
        age_h = (now - t).total_seconds() / 3600
        if age_h > 48:
            f.warn(where + " as_of", "gold analysis is %.0f hours old" % age_h)
        peak = parse_day(g.get("peak_date", ""))
        if peak and peak > d:
            f.error(where + " peak_date", "%s is after as_of" % peak)
    thai = g.get("thai", {}) if isinstance(g.get("thai"), dict) else {}
    tt = parse_instant(thai.get("as_of", ""))
    if tt and tt > now + dt.timedelta(minutes=10):
        f.error(where + " thai.as_of", "%s is in the future" % thai.get("as_of"))
    if isinstance(thai.get("sell"), int) and isinstance(thai.get("buy"), int) and thai["sell"] < thai["buy"]:
        f.error(where + " thai", "sell %s is below buy %s" % (thai["sell"], thai["buy"]))
    spot = g.get("spot_now")
    if isinstance(spot, (int, float)):
        if not 500 <= spot <= 20000:
            f.error(where + " spot_now", "%s USD/oz is not plausible" % spot)
        peak_v = g.get("peak")
        fp = g.get("from_peak_pct")
        if isinstance(peak_v, (int, float)) and isinstance(fp, (int, float)) and peak_v > 0:
            calc = (spot / peak_v - 1) * 100
            if abs(calc - fp) > 1.5:
                f.warn(where + " from_peak_pct", "%s but spot_now/peak gives %.1f" % (fp, calc))
            if spot > peak_v * 1.001:
                f.warn(where + " peak", "spot_now %s is above the recorded peak %s: update peak/peak_date" % (spot, peak_v))
        low = g.get("intraday_low")
        if isinstance(low, (int, float)) and low > spot * 1.02:
            f.warn(where + " intraday_low", "%s is above spot_now %s" % (low, spot))
    s = g.get("sentiment", {}) if isinstance(g.get("sentiment"), dict) else {}
    parts = [s.get(k) for k in ("bearish", "bullish", "neutral")]
    if all(isinstance(p, int) for p in parts) and abs(sum(parts) - 100) > 2:
        f.warn(where + " sentiment", "bearish + bullish + neutral = %d, not 100" % sum(parts))
    for lv in (g.get("levels", {}) or {}).get("support", []):
        if isinstance(lv.get("lo"), (int, float)) and isinstance(lv.get("hi"), (int, float)) and lv["lo"] > lv["hi"]:
            f.error(where + " levels.support[%s]" % lv.get("range_th"), "lo %s > hi %s" % (lv["lo"], lv["hi"]))
    for it in (g.get("forecasts", {}) or {}).get("items", []):
        for k in ("end_2026", "end_2027"):
            v = it.get(k)
            if isinstance(v, (int, float)) and not 500 <= v <= 20000:
                f.error(where + " forecasts[%s]" % it.get("name"), "%s = %s is not plausible" % (k, v))
    for path, text in (("drivers_th.title_th", (g.get("drivers_th") or {}).get("title_th", "")),
                       ("supports_th.title_th", (g.get("supports_th") or {}).get("title_th", "")),
                       ("sentiment.title_th", s.get("title_th", "")),
                       ("outlook_th.calendar_th.title_th", ((g.get("outlook_th") or {}).get("calendar_th") or {}).get("title_th", ""))):
        if has_now_word(str(text)):
            f.warn(where + " " + path, "title %r uses relative time (%s); name the dates instead" % (text, has_now_word(str(text))))
    n = len((g.get("forecasts", {}) or {}).get("items", []))
    if n != E2E_COUNTS["gold.forecasts.items"]:
        f.warn(where + " forecasts.items", "%d items, the page layout was designed for %d" % (n, E2E_COUNTS["gold.forecasts.items"]))


# ----------------------------------------------------------------------------- diff vs base
def keyed(items: list, key: str) -> dict:
    return {i.get(key): i for i in items if isinstance(i, dict)}


def world_diff(old: dict, new: dict) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for sec, key in (("conflicts", "id"), ("economies", "iso"), ("chokepoints", "name_th"), ("indicators", "label_th")):
        a, b = keyed(old.get(sec, []), key), keyed(new.get(sec, []), key)
        out[sec] = {
            "changed": sorted(k for k in a.keys() & b.keys() if a[k] != b[k]),
            "added": sorted(b.keys() - a.keys()),
            "removed": sorted(a.keys() - b.keys()),
        }
    out["analysis_th"] = {"changed": ["analysis_th"] if old.get("analysis_th") != new.get("analysis_th") else [], "added": [], "removed": []}
    return out


def gold_diff(old: dict, new: dict) -> list[str]:
    keys = (old.keys() | new.keys()) - GOLD_META_KEYS
    return sorted(k for k in keys if old.get(k) != new.get(k))


def headline_ids(root: pathlib.Path) -> set[str] | None:
    p = root / HEADLINES_SCHEMA
    if not p.exists():
        return None
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
        return set(s["properties"]["items"]["items"]["properties"]["conflict_id"]["enum"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return None


def check_diff(root: pathlib.Path, base: str, run_date: dt.date | None, w: dict, g: dict, f: Findings) -> dict:
    old_w = git_show_json(root, base, WORLD, f)
    old_g = git_show_json(root, base, GOLD, f)
    if old_w is None or old_g is None or not isinstance(w, dict) or not isinstance(g, dict):
        return {}
    wd = world_diff(old_w, w)
    gd = gold_diff(old_g, g)
    world_changed = old_w != w
    gold_changed = old_g != g
    summary = {"base": base, "world": wd, "gold": gd, "world_changed": world_changed, "gold_changed": gold_changed}
    n_items = sum(len(v) for s in wd.values() for v in s.values()) + len(gd)
    f.info("diff", "%d item(s) changed against %s (world-data %s, gold %s)" % (
        n_items, base, "changed" if world_changed else "unchanged", "changed" if gold_changed else "unchanged"))
    if not (world_changed or gold_changed):
        return summary
    if run_date is None:
        f.warn("diff", "data changed but no --run-date given: cannot check the run's change log")
        return summary

    # meta dates moved to the run
    if world_changed and w.get("meta", {}).get("updated") != run_date.isoformat():
        f.error(WORLD + " meta.updated", "world data changed but meta.updated is %s, not the run date %s" % (w.get("meta", {}).get("updated"), run_date))
    if gold_changed:
        t = parse_instant(g.get("as_of", ""))
        if not t or bkk_day(t) < run_date - dt.timedelta(days=1):
            f.error(GOLD + " as_of", "gold data changed but as_of (%s) was not moved to the run" % g.get("as_of"))

    log = root / RUNS / ("%s.md" % run_date)
    if not log.exists():
        f.error(str(log.relative_to(root)), "the Thai change summary for this run is missing")
    ch_path = root / RUNS / ("%s.changes.json" % run_date)
    ch = read_json(root, str(ch_path.relative_to(root)), f)
    if ch is None:
        return summary
    for e in schema_errors("changes.schema.json", ch):
        f.error(str(ch_path.relative_to(root)), "schema: " + e)
    if ch.get("date") != run_date.isoformat():
        f.error(str(ch_path.relative_to(root)), "date %r is not the run date %s" % (ch.get("date"), run_date))

    def entries(kind: str) -> list[dict]:
        return [e for e in ch.get(kind, []) if isinstance(e, dict)]

    def covering(kind: str, file: str, section: str, key: str) -> list[dict]:
        return [e for e in entries(kind) if e.get("file") == file and e.get("section") == section and key in e.get("keys", [])]

    newest_source: dict[str, dt.date] = {}
    changed_keys_listed: set[str] = set()
    for kind in ("changes", "added", "removed"):
        for e in entries(kind):
            lab = "%s %s/%s %s" % (kind, e.get("file"), e.get("section"), ",".join(e.get("keys", []))[:80])
            for p in entry_source_problems(e, run_date):
                f.error("changes " + lab, p)
            changed_keys_listed |= set(e.get("keys", []))
            for s in e.get("sources", []):
                d = parse_day(s.get("published", ""))
                if d is None:
                    continue
                fk = e.get("file", "")
                newest_source[fk] = max(newest_source.get(fk, d), d)
    both = sorted(set(ch.get("reviewed_unchanged", []) or []) & changed_keys_listed)
    if both:
        f.error(ch_path.name, "listed as changed and as reviewed_unchanged at the same time: %s" % ", ".join(both))

    def require(kind: str, file: str, section: str, key: str, item: dict | None, min_sources: int = 1) -> None:
        lab = "%s %s[%s]" % (file, section, key)
        cov = covering(kind, file, section, key)
        if not cov:
            f.error(lab, "%s but not listed under %r in %s" % ({"changes": "changed", "added": "added", "removed": "removed"}[kind], kind, ch_path.name))
            return
        urls = [s.get("url", "") for e in cov for s in e.get("sources", [])]
        if len(urls) < min_sources:
            f.error(lab, "needs at least %d dated source URL(s) in %s, has %d" % (min_sources, ch_path.name, len(urls)))
        if min_sources >= 2 and len({host(u) for u in urls}) < 2:
            f.error(lab, "a new item needs sources from at least 2 different publishers")
        if item is None:
            return
        listed = {norm_url(u) for u in urls}
        if section in ("conflicts", "economies"):
            page = {norm_url(u) for u in item.get("sources", [])}
            if listed and not (listed & page):
                f.error(lab, "none of this run's source URLs is in the item's own sources[] (the page would not show them)")
        if section == "indicators" and listed and norm_url(item.get("source", "")) not in listed:
            f.error(lab, "indicator source %s is not one of this run's source URLs" % item.get("source"))
        if section == "conflicts" and any(e.get("confidence") == "low" for e in cov) and item.get("confidence") == "high":
            f.warn(lab, "the change is marked low confidence but the item says confidence high")

    new_idx = {sec: keyed(w.get(sec, []), key) for sec, key in (("conflicts", "id"), ("economies", "iso"), ("chokepoints", "name_th"), ("indicators", "label_th"))}
    for sec, parts in wd.items():
        for k in parts["changed"]:
            require("changes", "world-data", sec, k, new_idx.get(sec, {}).get(k) if sec != "analysis_th" else None)
        for k in parts["added"]:
            require("added", "world-data", sec, k, new_idx.get(sec, {}).get(k), min_sources=2 if sec == "conflicts" else 1)
        for k in parts["removed"]:
            require("removed", "world-data", sec, k, None)
    for k in gd:
        require("changes", "gold", "gold", k, None)

    ids = headline_ids(root)
    if ids is not None:
        for k in wd["conflicts"]["removed"]:
            if k in ids:
                f.error("world-data conflicts[%s]" % k, "removed, but headlines link to this id (updater/schema/headlines.schema.json): mark it ended instead")
        for k in wd["conflicts"]["added"]:
            if k not in ids:
                f.error("world-data conflicts[%s]" % k, "new id is not in the headlines conflict_id enum (updater tests fail): a new conflict needs a code change - put it on an agent/* branch with an issue, not on main")

    upd = parse_day(w.get("meta", {}).get("updated", ""))
    if upd and "world-data" in newest_source and newest_source["world-data"] > upd:
        f.error(WORLD + " meta.updated", "%s is older than the newest source of this run (%s)" % (upd, newest_source["world-data"]))
    t = parse_instant(g.get("as_of", ""))
    if t and "gold" in newest_source and newest_source["gold"] > bkk_day(t):
        f.warn(GOLD + " as_of", "as_of (%s) is older than the newest gold source of this run (%s)" % (g.get("as_of"), newest_source["gold"]))

    # entries that point at nothing that changed
    changed_keys = {("world-data", sec, k) for sec, p in wd.items() for k in p["changed"] + p["added"] + p["removed"]}
    changed_keys |= {("gold", "gold", k) for k in gd}
    for kind in ("changes", "added", "removed"):
        for e in entries(kind):
            for k in e.get("keys", []):
                if (e.get("file"), e.get("section"), k) not in changed_keys and e.get("section") != "meta":
                    f.warn("changes %s/%s[%s]" % (e.get("file"), e.get("section"), k), "listed in %s but did not change" % ch_path.name)
    return summary


# ----------------------------------------------------------------------------- page / scope / live
def check_page(root: pathlib.Path, w: Any, g: Any, f: Findings) -> None:
    p = root / PAGE
    if not p.exists():
        f.error(PAGE, "missing: run python3 -I tools/build.py")
        return
    m = re.search(r'<script type="application/json" id="world-data">(.*?)</script>', p.read_text(encoding="utf-8"), re.S)
    if not m:
        f.error(PAGE, "has no #world-data block")
        return
    emb = load_json_text(m.group(1), PAGE + " #world-data", f)
    if emb is None or not isinstance(w, dict):
        return
    want = dict(w)
    want["gold"] = g
    if emb != want:
        f.error(PAGE, "embedded data differs from data/*.json: run python3 -I tools/splice_gold.py && python3 -I tools/build.py")


def changed_files(root: pathlib.Path, base: str, f: Findings) -> set[str]:
    files: set[str] = set()
    for args in (("diff", "--name-only", "HEAD"), ("diff", "--name-only", "--cached", "HEAD"), ("ls-files", "--others", "--exclude-standard")):
        r = git(root, *args)
        if r.returncode != 0:
            f.error("git", "git %s failed: %s" % (" ".join(args), r.stderr.strip()[:200]))
            continue
        files |= {x for x in r.stdout.splitlines() if x}
    r = git(root, "log", "--format=%H %ae", "%s..HEAD" % base)
    if r.returncode != 0:
        f.error("git", "cannot list commits since %s: %s" % (base, r.stderr.strip()[:200]))
        return files
    for line in r.stdout.splitlines():
        sha, _, email = line.partition(" ")
        if email in BOT_EMAILS:
            continue
        rr = git(root, "show", "--name-only", "--format=", sha)
        files |= {x for x in rr.stdout.splitlines() if x}
    return files


def check_scope(root: pathlib.Path, base: str, f: Findings) -> None:
    files = changed_files(root, base, f)
    bad = sorted(x for x in files if x not in ALLOWED_FILES and not ALLOWED_RUN_FILE.match(x))
    for x in bad:
        f.error("scope " + x, "the editor agent may not change this file on main (allowed: data/world-data.json, data/gold.json, site/index.html, editor-agent/runs/<date>.md|.changes.json)")
    f.info("scope", "%d changed file(s) since %s: %s" % (len(files), base, ", ".join(sorted(files)) or "none"))


def check_live(root: pathlib.Path, w: Any, g: Any, f: Findings, now: dt.datetime) -> None:
    def age_h(ts: str | None) -> float | None:
        t = parse_instant(ts or "")
        return None if t is None else (now - t).total_seconds() / 3600

    # the bot runs every hour (prices from free direct feeds + disasters, minute 7) and adds headlines with Claude at
    # 08:00 / 20:00 Bangkok, so about 26 bot commits a day; 3 h allows for GitHub's late or skipped cron starts.
    # gold_history only moves when the gold as_of moves (not while gold is shut), so it keeps the older 6 h limit.
    limits = (("status", "updated_at", 3), ("market", "updated_at", 3), ("headlines", "updated_at", 14),
              ("disasters", "updated", 3), ("gold_history", "updated_at", 6))
    docs: dict[str, Any] = {}
    for name, fld, lim in limits:
        rel = "%s/%s.json" % (LIVE_DIR, name)
        d = read_json(root, rel, f, required=name != "gold_history")
        docs[name] = d
        if not isinstance(d, dict):
            continue
        a = age_h(d.get(fld))
        if a is None:
            f.warn(rel, "%s is missing or not a timestamp" % fld)
        elif a > lim:
            f.warn(rel, "%s is %.1f hours old (limit %d h): the Actions bot may have stopped" % (fld, a, lim))
        elif a < -0.2:
            f.warn(rel, "%s is in the future" % fld)
        else:
            f.info(rel, "%s %.1f h old" % (fld, a))
    st = docs.get("status")
    if isinstance(st, dict) and st.get("ok") is not True:
        f.warn(LIVE_DIR + "/status.json", "last bot run failed: %s" % st.get("message_th"))
    dz = docs.get("disasters")
    if isinstance(dz, dict) and dz.get("ok") is False:
        f.warn(LIVE_DIR + "/disasters.json", "a disaster feed failed: %s" % dz.get("message_th"))
    mk = docs.get("market")
    if isinstance(mk, dict):
        for it in mk.get("items", []):
            try:
                float(str(it.get("value")).replace(",", ""))
            except ValueError:
                f.warn(LIVE_DIR + "/market.json", "%s value %r is not a number" % (it.get("key"), it.get("value")))
        gold_live = next((it for it in mk.get("items", []) if it.get("key") == "gold"), None)
        if gold_live and isinstance(g, dict) and isinstance(g.get("spot_now"), (int, float)):
            try:
                v = float(str(gold_live.get("value")).replace(",", ""))
                gap = abs(v / g["spot_now"] - 1) * 100
                if gap > 8:
                    f.warn(GOLD + " spot_now", "analysis spot %s is %.0f%% away from the live price %s: refresh gold.json" % (g["spot_now"], gap, v))
            except (ValueError, ZeroDivisionError):
                pass
    hd = docs.get("headlines")
    ids = headline_ids(root)
    if isinstance(w, dict):
        world_ids = {c.get("id") for c in w.get("conflicts", [])}
        if ids is not None:
            for k in sorted(ids - world_ids - PSEUDO_IDS):
                f.warn(HEADLINES_SCHEMA, "conflict_id %r has no conflict in data/world-data.json" % k)
        if isinstance(hd, dict):
            for it in hd.get("items", []):
                c = it.get("conflict_id")
                if c not in world_ids and c not in PSEUDO_IDS:
                    f.warn(LIVE_DIR + "/headlines.json", "headline %s links to unknown conflict %r" % (it.get("id"), c))
    p = root / COST_LOG
    if p.exists():
        rows = list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))
        recent = [r for r in rows if (age_h(r.get("time_utc")) or 1e9) <= 24]
        failed = [r for r in recent if r.get("ok") != "yes"]
        cost = sum(float(r.get("cost_usd") or 0) for r in recent)
        n_prices = sum(1 for r in recent if r.get("mode") == "prices")
        f.info(COST_LOG, "last 24 h: %d bot run(s) (%d hourly price runs, expect ~24; %d full runs, expect 2), %d failed, $%.2f"
               % (len(recent), n_prices, len(recent) - n_prices, len(failed), cost))
        if not recent:
            f.warn(COST_LOG, "no bot run in the last 24 hours")
        for r in failed:
            f.warn(COST_LOG, "bot run %s (%s) failed: %s" % (r.get("time_utc"), r.get("mode"), r.get("note")))


# ----------------------------------------------------------------------------- main
def run(argv: list[str] | None = None, root: pathlib.Path = ROOT) -> tuple[int, Findings]:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", nargs="?", const="HEAD", default=None, help="git ref to compare the data with (default HEAD)")
    ap.add_argument("--run-date", help="the run's Bangkok date YYYY-MM-DD")
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--page", action="store_true")
    ap.add_argument("--scope", action="store_true")
    ap.add_argument("--all", action="store_true", help="--live --page --scope")
    ap.add_argument("--scope-only", action="store_true", help="only the file-scope check (used by publish.sh)")
    ap.add_argument("--now", help="override the current time (ISO 8601, for tests)")
    ap.add_argument("--strict", action="store_true", help="warnings also fail")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    now = parse_instant(a.now) if a.now else dt.datetime.now(dt.timezone.utc)
    if now is None:
        ap.error("--now is not an ISO time")
    today = bkk_day(now)
    run_date = parse_day(a.run_date) if a.run_date else None
    if a.run_date and run_date is None:
        ap.error("--run-date must be YYYY-MM-DD")
    if a.all:
        a.live = a.page = a.scope = True
    base = a.base or ("HEAD" if (a.scope or a.scope_only or run_date) else None)

    f = Findings()
    if a.scope_only:
        check_scope(root, base or "HEAD", f)
        failed = bool(f.errors)
        for i in f.items:
            print("%-5s %s: %s" % (i["level"], i["where"], i["what"]))
        return (1 if failed else 0), f
    w = read_json(root, WORLD, f)
    g = read_json(root, GOLD, f)
    if isinstance(w, dict):
        check_world(w, f, today)
    if isinstance(g, dict):
        check_gold(g, f, today, now)
    if base:
        check_diff(root, base, run_date, w, g, f)
    if a.page:
        check_page(root, w, g, f)
    if a.scope:
        check_scope(root, base or "HEAD", f)
    if a.live:
        check_live(root, w, g, f, now)

    failed = bool(f.errors) or (a.strict and bool(f.warnings))
    if a.json:
        print(json.dumps({"ok": not failed, "errors": len(f.errors), "warnings": len(f.warnings), "findings": f.items}, ensure_ascii=False, indent=1))
    else:
        for i in f.items:
            print("%-5s %s: %s" % (i["level"], i["where"], i["what"]))
        print("check.py: %s - %d error(s), %d warning(s)" % ("FAIL" if failed else "OK", len(f.errors), len(f.warnings)))
    return (1 if failed else 0), f


if __name__ == "__main__":
    sys.exit(run()[0])
