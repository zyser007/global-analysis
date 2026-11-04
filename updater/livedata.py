#!/usr/bin/env python3
"""Shared pieces of the live-data updaters (updater/prices.py, updater/update.py, updater/backfill_gold_history.py).

- paths, the 13 market keys, Thai date / number / text helpers
- JSON Schema validation of site/data/*.json plus the checks a schema can't express
- the market safety rules: no move > 15 % from the previous value, never an older as_of, label / unit from the
  previous file, gold_th buy / ornament_sell plausibility (sanity_market, scrub_gold_th)
- atomic writes (write_docs), the gold_history.json append (history_docs), the failure status, the cost log CSV
"""
from __future__ import annotations

import copy
import csv
import datetime as dt
import json
import os
import pathlib
import re
import tempfile
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
SCHEMA_DIR = ROOT / "updater" / "schema"
COST_LOG = ROOT / "updater" / "cost-log.csv"
DOCS = ("market", "headlines", "status")
HISTORY = "gold_history"             # site/data/gold_history.json: gold points for the chart (not fatal when broken)
HISTORY_CAP = 400                    # points kept in gold_history.json
HISTORY_FULL_DAYS = 30               # newer points stay as they are; older ones thin out to the last point of each Bangkok day
GOLD_TH_EXTRA = ("buy", "ornament_sell")
BUY_SPREAD_MAX = 1000                # baht: 0 < sell - buy <= this
ORNAMENT_PREMIUM_MAX = 2500          # baht: sell < ornament_sell <= sell + this

MAX_MOVE = 0.15                      # reject a market value that moved more than 15 %

# market keys in display order, with what each one means
MARKET_KEYS: dict[str, str] = {
    "brent": "Brent crude front-month futures, USD per barrel",
    "wti": "WTI crude front-month futures, USD per barrel",
    "gold": "Gold spot XAU/USD, USD per troy ounce",
    "gold_th": "Thai Gold Traders Association 96.5% gold bar SELL price, baht per baht-weight (latest announcement)",
    "dxy": "US Dollar Index (DXY), points",
    "spx": "S&P 500 index, points (last close if the US market is shut)",
    "ndx": "Nasdaq 100 index, points (last close if the US market is shut)",
    "btc": "Bitcoin BTC/USD, USD",
    "usdthb": "Thai baht per US dollar (USD/THB)",
    "us10y": "US 10-year Treasury yield, percent",
    "vix": "CBOE VIX index, points",
    "set": "SET index (Stock Exchange of Thailand), points",
    "nikkei": "Nikkei 225 index, points",
}

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
TH_MONTHS = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


class UpdateError(Exception):
    """A failed run: old data files stay, status.json gets ok=false with `message_th`."""

    def __init__(self, message: str, message_th: str):
        super().__init__(message)
        self.message_th = message_th


# ----------------------------------------------------------------- small helpers
def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def bkk_th(t: dt.datetime) -> str:
    b = t.astimezone(dt.timezone(dt.timedelta(hours=7)))
    return f"{b.day} {TH_MONTHS[b.month - 1]} {b.year + 543} {b:%H:%M} น."


THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")


def parse_number(v: Any) -> float | None:
    """'3,903.12' / '−2.5' / ' 62500 ' / '+50' / '๖๒,๕๐๐' -> float; anything else (NaN, inf included) -> None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v and v not in (float("inf"), float("-inf")) else None
    s = str(v).strip().translate(THAI_DIGITS).replace(",", "").replace("−", "-").replace(" ", "").replace("\u00a0", "")
    s = s[1:] if s.startswith("+") else s
    return float(s) if NUM_RE.match(s) else None


def normalize_value(v: Any) -> str:
    s = str(v).strip().translate(THAI_DIGITS).replace(",", "").replace("−", "-").replace(" ", "")
    return s[1:] if s.startswith("+") else s


def clean_th(s: Any, limit: int = 400) -> str:
    """Thai display text: no raw double quotes (pairs become “ ”), single spaces, length-capped."""
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    out, open_q = [], True
    for ch in s:
        if ch == '"':
            out.append("“" if open_q else "”")
            open_q = not open_q
        else:
            out.append(ch)
    s = "".join(out)
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def load_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def allowed_conflict_ids() -> list[str]:
    return list(load_json(SCHEMA_DIR / "headlines.schema.json")["properties"]["items"]["items"]["properties"]["conflict_id"]["enum"])


# ----------------------------------------------------------------- validation
_validators: dict[str, Any] = {}


def validate_doc(name: str, doc: Any) -> list[str]:
    """JSON Schema + the checks a schema can't express. Returns a list of problems ([] = valid)."""
    import jsonschema  # pinned in requirements.txt

    if name not in _validators:
        schema = load_json(SCHEMA_DIR / f"{name}.schema.json")
        jsonschema.Draft202012Validator.check_schema(schema)
        _validators[name] = jsonschema.Draft202012Validator(schema)
    errs = [f"{name}: {'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}" for e in _validators[name].iter_errors(doc)]
    if errs:
        return errs
    if name == "market":
        keys = [i["key"] for i in doc["items"]]
        if sorted(keys) != sorted(MARKET_KEYS):
            errs.append(f"market: keys {keys} != {list(MARKET_KEYS)}")
        errs += [f"market: {i['key']}: value {i['value']!r} is not a number" for i in doc["items"] if parse_number(i["value"]) is None]
    if name == "headlines":
        ids = [i["id"] for i in doc["items"]]
        if len(set(ids)) != len(ids):
            errs.append("headlines: duplicate ids")
    return errs


def sanity_market(prev: dict, new_items: dict[str, dict], max_move: float = MAX_MOVE) -> tuple[list[dict], list[str]]:
    """Merge the model's items into the previous market items.

    label_th / unit always come from the previous file. A value that does not parse, or that moved
    more than `max_move` from the previous value, is rejected: the previous item is kept and its
    change_th says so. Returns (items, notes about rejected keys)."""
    out, notes = [], []
    for old in prev["items"]:
        key = old["key"]
        sub = new_items.get(key)
        if not isinstance(sub, dict):
            out.append(_stale(old, "ไม่ได้รับค่าใหม่รอบนี้"))
            notes.append(f"{key}: missing")
            continue
        new_v, old_v = parse_number(sub.get("value")), parse_number(old["value"])
        if new_v is None:
            out.append(_stale(old, "ค่าใหม่อ่านเป็นตัวเลขไม่ได้"))
            notes.append(f"{key}: not a number ({sub.get('value')!r})")
            continue
        if old_v not in (None, 0.0) and abs(new_v - old_v) / abs(old_v) > max_move:
            pct = (new_v - old_v) / abs(old_v) * 100
            out.append(_stale(old, f"ค่าใหม่ {normalize_value(sub.get('value'))} ต่าง {pct:+.0f}% เกินเกณฑ์ 15%"))
            notes.append(f"{key}: moved {pct:+.1f}% ({old['value']} -> {sub.get('value')})")
            continue
        as_of = str(sub.get("as_of") or "").strip()
        source = str(sub.get("source") or "").strip()
        if ISO_RE.match(as_of) and _ts(as_of) < _ts(old["as_of"]):
            out.append(copy.deepcopy(old))      # an older quote never replaces a newer one
            notes.append(f"{key}: as_of {as_of} is older than the previous {old['as_of']}")
            continue
        item = {
            "key": key,
            "label_th": old["label_th"],
            "value": normalize_value(sub["value"]),
            "unit": old["unit"],
            "change_th": clean_th(sub.get("change_th"), 220) or old["change_th"],
            "trend": sub.get("trend") if sub.get("trend") in ("up", "down", "flat") else "flat",
            "as_of": as_of if ISO_RE.match(as_of) else old["as_of"],
            "source": source if re.match(r"^https?://\S+$", source) and '"' not in source else old["source"],
        }
        if key == "gold_th":   # only from this submission: an old buy price never sits next to a new sell price
            for f in GOLD_TH_EXTRA:
                n = parse_number(sub.get(f))
                if n is not None:
                    item[f] = int(n) if n == int(n) else n
        out.append(item)
    return out, notes


def scrub_gold_th(market: dict) -> list[str]:
    """Drop gold_th buy / ornament_sell (in place) unless 0 < sell - buy <= 1000 and sell < ornament_sell <= sell + 2500.
    The item itself always stays. Returns notes about dropped fields."""
    notes = []
    for it in market.get("items") or []:
        if not isinstance(it, dict) or it.get("key") != "gold_th":
            continue
        sell = parse_number(it.get("value"))
        for f in GOLD_TH_EXTRA:
            if f not in it:
                continue
            v = it[f]
            n = None if isinstance(v, bool) or not isinstance(v, (int, float)) else float(v)
            ok = sell is not None and n is not None and (
                0 < sell - n <= BUY_SPREAD_MAX if f == "buy" else sell < n <= sell + ORNAMENT_PREMIUM_MAX)
            if not ok:
                del it[f]
                notes.append(f"gold_th: dropped {f}={v!r} (sell {it.get('value')})")
    return notes


STALE_PREFIX = "ค่าเดิม รอยืนยัน"


def parse_ts_iso(s: str) -> dt.datetime:
    """An ISO_RE timestamp ('2026-11-04T06:03:00Z' / '+07:00') -> aware datetime."""
    return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def _ts(s: str) -> float:
    return parse_ts_iso(s).timestamp()


def count_changed(prev_items: list[dict], new_items: list[dict]) -> int:
    """Items whose value or as_of differs from the previous file (= really refreshed this run)."""
    old = {i["key"]: (i["value"], i["as_of"]) for i in prev_items}
    return sum(1 for i in new_items if old.get(i["key"]) != (i["value"], i["as_of"]))


def _stale(old: dict, why: str) -> dict:
    item = copy.deepcopy(old)
    item["change_th"] = clean_th(f"{STALE_PREFIX} ({why})", 220)
    return item


def _short(x: Any, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(x if x is not None else "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ----------------------------------------------------------------- files
def write_docs(data_dir: pathlib.Path, docs: dict[str, dict]) -> list[str]:
    """Validate everything first, then replace the files atomically (temp file + os.replace).
    gold_th's optional buy / ornament_sell are checked here and dropped when implausible; returns those notes."""
    notes = scrub_gold_th(docs["market"]) if isinstance(docs.get("market"), dict) else []
    for name, doc in docs.items():
        errs = validate_doc(name, doc)
        if errs:
            raise UpdateError("; ".join(errs[:5]), "ผลลัพธ์ไม่ผ่านการตรวจโครงสร้างข้อมูล")
    tmp_paths = {}
    try:
        for name, doc in docs.items():
            fd, tmp = tempfile.mkstemp(prefix=f".{name}.", suffix=".json.tmp", dir=data_dir)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(dump_json(doc))
            tmp_paths[name] = tmp
        for name, tmp in tmp_paths.items():
            os.replace(tmp, data_dir / f"{name}.json")
    finally:
        for tmp in tmp_paths.values():
            if os.path.exists(tmp):
                os.unlink(tmp)
    return notes


# ----------------------------------------------------------------- gold history (chart points)
def _bkk_day(s: str) -> str:
    return (dt.datetime.fromisoformat(s.replace("Z", "+00:00")) + dt.timedelta(hours=7)).strftime("%Y-%m-%d")


def history_point(market: dict) -> dict | None:
    """The gold point of one market.json: spot + Thai sell with their own as_of; None if either is unusable."""
    items = {i.get("key"): i for i in market.get("items") or [] if isinstance(i, dict)}
    g, t = items.get("gold"), items.get("gold_th")
    if not g or not t:
        return None
    spot, sell = parse_number(g.get("value")), parse_number(t.get("value"))
    stamps = (str(market.get("updated_at") or ""), str(g.get("as_of") or ""), str(t.get("as_of") or ""))
    if not spot or not sell or spot <= 0 or sell <= 0 or not all(ISO_RE.match(x) for x in stamps):
        return None
    return {"time": stamps[0], "spot": int(spot) if spot == int(spot) else spot, "spot_as_of": stamps[1],
            "th_sell": int(sell) if sell == int(sell) else sell, "th_as_of": stamps[2]}


def compact_history(points: list[dict], now: dt.datetime, cap: int = HISTORY_CAP,
                    full_days: int = HISTORY_FULL_DAYS) -> list[dict]:
    """Points newer than `full_days` stay; older ones thin out to the last point of each Bangkok day
    (what the chart and the day change need); then only the newest `cap` points are kept."""
    cut = now.timestamp() - full_days * 86400
    old = [p for p in points if _ts(p["time"]) < cut]
    keep = [p for i, p in enumerate(old) if i == len(old) - 1 or _bkk_day(old[i + 1]["time"]) != _bkk_day(p["time"])]
    out = keep + [p for p in points if _ts(p["time"]) >= cut]
    return out[-cap:] if cap > 0 else out


def append_history(hist: dict | None, market: dict, now: dt.datetime, cap: int = HISTORY_CAP) -> tuple[dict, bool]:
    """Add the gold point of `market` to `hist` (None = a new file). Skipped (changed=False) when neither
    as_of moved since the last point. Returns (the new history doc, changed)."""
    points = [copy.deepcopy(p) for p in (hist or {}).get("points") or []]
    pt = history_point(market)
    if pt is None:
        return {"updated_at": (hist or {}).get("updated_at") or iso(now), "points": points}, False
    if points and (points[-1]["spot_as_of"], points[-1]["th_as_of"]) == (pt["spot_as_of"], pt["th_as_of"]):
        return {"updated_at": hist["updated_at"], "points": points}, False
    points.append(pt)
    return {"updated_at": iso(now), "points": compact_history(points, now, cap)}, True


def load_history(data_dir: pathlib.Path) -> tuple[dict | None, str | None]:
    """(doc, None) for a valid file, (None, None) when there is none yet, (None, problem) when it is broken."""
    path = data_dir / f"{HISTORY}.json"
    if not path.exists():
        return None, None
    try:
        doc = load_json(path)
    except (OSError, ValueError) as e:
        return None, f"cannot read {path.name}: {e}"
    errs = validate_doc(HISTORY, doc)
    return (None, "; ".join(errs[:3])) if errs else (doc, None)


def history_docs(data_dir: pathlib.Path, docs: dict[str, dict], now: dt.datetime) -> tuple[dict[str, dict], list[str]]:
    """The gold_history doc to write with this run's market.json ({} when nothing to add). A broken history
    file is left alone and reported, never fatal."""
    if "market" not in docs:
        return {}, []
    hist, problem = load_history(data_dir)
    if problem:
        return {}, [f"{HISTORY}: left unchanged, file is invalid ({_short(problem, 200)})"]
    new, changed = append_history(hist, docs["market"], now)
    if not changed:
        return {}, [f"{HISTORY}: gold as_of unchanged, no new point"]
    errs = validate_doc(HISTORY, new)
    if errs:   # pragma: no cover - points are built from a validated market doc
        return {}, [f"{HISTORY}: new point not written ({_short('; '.join(errs), 200)})"]
    return {HISTORY: new}, []


def failure_status(prev_status: dict | None, message_th: str, now: dt.datetime) -> dict:
    return {
        "updated_at": iso(now),
        "run_count": int((prev_status or {}).get("run_count", 0)) + 1,
        "ok": False,
        "message_th": clean_th(f"อัปเดตอัตโนมัติไม่สำเร็จ ({message_th}) {bkk_th(now)} แสดงค่าล่าสุดที่ได้รับ", 400),
    }


# ----------------------------------------------------------------- cost log
CSV_FIELDS = ["time_utc", "mode", "ok", "model", "requests", "input_tokens", "output_tokens",
              "cache_write_tokens", "cache_read_tokens", "web_searches", "cost_usd", "note", "web_fetches", "items_changed"]


def _migrate_csv(cost_log: pathlib.Path) -> None:
    """Rewrite an older cost log whose header lacks the newer columns (they were appended at the end)."""
    if not cost_log.exists() or cost_log.stat().st_size == 0:
        return
    with cost_log.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
        header = rows and list(rows[0].keys())
    if header == CSV_FIELDS or not rows:
        return
    with cost_log.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_FIELDS})


def append_cost_row(row: dict, cost_log: pathlib.Path) -> None:
    """Append one row (keys from CSV_FIELDS; missing ones stay empty) to the cost log, migrating an older header first."""
    _migrate_csv(cost_log)
    new = not cost_log.exists() or cost_log.stat().st_size == 0
    cost_log.parent.mkdir(parents=True, exist_ok=True)
    with cost_log.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def load_docs(data_dir: pathlib.Path, names: tuple[str, ...]) -> tuple[dict, list[str]]:
    """Read and validate site/data/<name>.json for each name. Returns (docs that could be read, problems)."""
    prev, errs = {}, []
    for name in names:
        path = data_dir / f"{name}.json"
        try:
            prev[name] = load_json(path)
        except (OSError, ValueError) as e:
            errs.append(f"{name}: cannot read {path.name}: {e}")
            continue
        errs += validate_doc(name, prev[name])
    return prev, errs
