#!/usr/bin/env python3
"""Refresh site/data/{market,headlines,status}.json with Claude + web search.

    python updater/update.py prices          # market.json values only (<= 6 web searches)
    python updater/update.py full            # market + 12-16 headlines + status (<= 20 web searches)
    python updater/update.py --dry-run       # no API call: validate the current files and exit

Design
- One Messages API call (claude-sonnet-5-5, adaptive thinking, effort medium) with the
  `web_search_20260209` server tool (max_uses enforced) and one strict client tool
  (`submit_prices` / `submit_full`) that carries the result. Web search always attaches
  citations, which structured outputs (output_config.format) rejects, so the JSON comes back
  as the strict tool's input instead; tool_choice stays "auto" (forced tool choice is a 400
  on this model) and the prompt tells the model to finish with the tool.
- The stable instructions, key list and allowed conflict ids sit in a cached system prompt;
  the previous JSON files go in the user turn so the model only changes what moved.
- `pause_turn` is resumed (append-only history, identical tools) while the search budget lasts.
- `stop_reason == "refusal"` fails the run; server-side fallbacks ("default") are opted in.
- Output is validated against updater/schema/*.json plus sanity checks (numbers parse, no move
  > 15% from the previous value -> previous value kept and flagged in change_th). Files are
  written atomically and only when everything is valid; on any failure the old market/headlines
  stay and status.json gets ok=false with a Thai message.
- Token usage, web-search count and an estimated USD cost are printed, appended to
  updater/cost-log.csv and written to $GITHUB_STEP_SUMMARY when set.
- The API key is read only from $ANTHROPIC_API_KEY and is never printed.
"""
from __future__ import annotations

import argparse
import copy
import csv
import datetime as dt
import json
import os
import pathlib
import re
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
SCHEMA_DIR = ROOT / "updater" / "schema"
COST_LOG = ROOT / "updater" / "cost-log.csv"
DOCS = ("market", "headlines", "status")

MODEL = "claude-sonnet-5-5"          # user's choice (cost); fallbacks="default" may serve a declined turn on claude-sonnet-5
EFFORT = "medium"                    # skill: medium for multistep tool use on Sonnet 5.5
MAX_TOKENS = 64000                   # streaming request, thinking counts toward it
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_SEARCHES = {"prices": 6, "full": 20}
# web fetch has no per-use fee (tokens only); max_content_tokens caps each page that enters the context
MAX_FETCHES = {"prices": 5, "full": 8}
FETCH_MAX_CONTENT_TOKENS = 8000
HEADLINES_MIN, HEADLINES_MAX = 12, 16
MIN_NEWS_SEARCHES = 4                # a full run must search the news at least this often before submitting
PRICES_FRESH_MIN = 60                # full run: prices younger than this are not searched again
NEWS_TOPICS = ("Iran / Hormuz", "US markets, the Fed and US data", "the US midterm elections", "Ukraine-Russia", "China",
               "Thai politics and economy, the baht and Thai gold", "Yemen / Saudi Arabia")
MAX_MOVE = 0.15                      # reject a market value that moved more than 15 %
MAX_REQUESTS = 5                     # first call + pause_turn continuations + one nudge + one schema fix
DEADLINE_S = 11 * 60                 # the workflow job times out at 15 min

# USD per million tokens (Claude Sonnet 5.5, Claude API first-party) and per web search.
# Cache read is $0.20/MTok per the claude-api skill pricing table (2026-10-06); edit here if it changes.
PRICE = {"input": 2.00, "output": 10.00, "cache_write_5m": 2.50, "cache_read": 0.10}
WEB_SEARCH_USD = 10.0 / 1000

# market keys in display order, with what each one means for the model
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
TAGS_EXTRA = {"thailand": "Thailand domestic news that is not the Thai-Cambodian border",
              "economy": "markets / economy / central banks", "world": "other world news"}

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


def parse_number(v: Any) -> float | None:
    """'3,903.12' / '−2.5' / ' 62500 ' -> float; anything else -> None."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("−", "-").replace(" ", "")
    return float(s) if NUM_RE.match(s) else None


def normalize_value(v: Any) -> str:
    return str(v).strip().replace(",", "").replace("−", "-").replace(" ", "")


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
        out.append({
            "key": key,
            "label_th": old["label_th"],
            "value": normalize_value(sub["value"]),
            "unit": old["unit"],
            "change_th": clean_th(sub.get("change_th"), 220) or old["change_th"],
            "trend": sub.get("trend") if sub.get("trend") in ("up", "down", "flat") else "flat",
            "as_of": as_of if ISO_RE.match(as_of) else old["as_of"],
            "source": source if re.match(r"^https?://\S+$", source) and '"' not in source else old["source"],
        })
    return out, notes


STALE_PREFIX = "ค่าเดิม รอยืนยัน"


def _ts(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def count_changed(prev_items: list[dict], new_items: list[dict]) -> int:
    """Items whose value or as_of differs from the previous file (= really refreshed this run)."""
    old = {i["key"]: (i["value"], i["as_of"]) for i in prev_items}
    return sum(1 for i in new_items if old.get(i["key"]) != (i["value"], i["as_of"]))


def _stale(old: dict, why: str) -> dict:
    item = copy.deepcopy(old)
    item["change_th"] = clean_th(f"{STALE_PREFIX} ({why})", 220)
    return item


def build_headlines(items: list[dict], now: dt.datetime, prev: dict | None = None) -> dict:
    allowed = set(allowed_conflict_ids())
    by_source = {i.get("source"): i for i in (prev or {}).get("items", [])}
    rows = []
    for it in items:
        if not isinstance(it, dict):
            continue
        t = str(it.get("time") or "").strip()
        src = str(it.get("source") or "").strip()
        row = {
            "conflict_id": it.get("conflict_id") if it.get("conflict_id") in allowed else "world",
            "title_th": clean_th(it.get("title_th"), 200),
            "time": t if ISO_RE.match(t) else iso(now),
            "source": src,
            "source_name": clean_th(it.get("source_name"), 60),
        }
        old = by_source.get(src)
        if old:   # a kept headline is copied verbatim (no retyped titles, no refreshed times)
            row = {k: old[k] for k in ("conflict_id", "title_th", "time", "source", "source_name")}
        if row["title_th"] and re.match(r"^https?://\S+$", src) and '"' not in src and row["source_name"]:
            rows.append(row)
    rows.sort(key=lambda r: r["time"], reverse=True)
    rows = rows[:HEADLINES_MAX]
    if len(rows) < HEADLINES_MIN:
        raise UpdateError(f"only {len(rows)} usable headlines (need {HEADLINES_MIN}-{HEADLINES_MAX})",
                          f"ได้พาดหัวข่าวที่ใช้ได้เพียง {len(rows)} ข่าว ต้องมี {HEADLINES_MIN}–{HEADLINES_MAX} ข่าว")
    return {"updated_at": iso(now), "items": [{"id": f"h{i + 1}", **r} for i, r in enumerate(rows)]}


def _norm_title(t: str) -> str:
    return re.sub(r"\W+", "", str(t or "")).lower()


def headlines_since(prev: dict) -> str:
    """The newest headline time of the previous set (a run that re-submitted old items moved updated_at
    without adding news), falling back to updated_at."""
    times = [i["time"] for i in prev.get("items", []) if ISO_RE.match(str(i.get("time", "")))]
    return max(times, key=_ts) if times else str(prev.get("updated_at") or "")


def count_new_headlines(prev: dict, items: list[dict]) -> int:
    """New = title and source not in the previous set, or a time later than the newest previous headline."""
    titles = {_norm_title(i.get("title_th")) for i in prev.get("items", [])}
    sources = {i.get("source") for i in prev.get("items", [])}
    since = headlines_since(prev)
    n = 0
    for it in items:
        later = ISO_RE.match(it.get("time", "")) and ISO_RE.match(since) and _ts(it["time"]) > _ts(since)
        unseen = _norm_title(it.get("title_th")) not in titles and it.get("source") not in sources
        n += 1 if (later or unseen) else 0
    return n


def prices_age_min(prev_market: dict, now: dt.datetime) -> float | None:
    try:
        return (now.timestamp() - _ts(prev_market["updated_at"])) / 60
    except (KeyError, ValueError):
        return None


# ----------------------------------------------------------------- prompt + tools
def system_prompt() -> str:
    """Stable across runs and modes (cached). Never put the date or the previous data here."""
    keys = "\n".join(f"- {k}: {v}" for k, v in MARKET_KEYS.items())
    ids = "\n".join(f"- {c}" for c in allowed_conflict_ids())
    extra = "\n".join(f"- {k}: {v}" for k, v in TAGS_EXTRA.items())
    return f"""You maintain the live data files of a public Thai-language website: a 3D globe of world conflicts, economies and markets, with a gold-price panel. Readers are in Thailand. You run unattended on a schedule; nobody reads your text replies, only the data you submit through the submit tool.

## Job
Find the latest quote for every market item, then call the submit tool exactly once with the complete result. The user turn gives the run mode, the current UTC and Bangkok time, which market sessions are open or closed right now, the tool budgets, a list of quote pages you may fetch directly, and the previous files.
- Mode "prices": update the 13 market items only. Call submit_prices.
- Mode "full": research and write 12 to 16 fresh headlines and a one-paragraph run summary, and update the 13 market items unless the user turn says the prices are fresh (then submit_full has no market field and you must not search prices at all). Call submit_full.

## How to find the quotes (follow this plan)
1. Fetch the quote pages listed in the user turn with web_fetch first: they are tables that cover several items at once (commodities, currencies and the dollar index, stock indexes, bond yields, the Thai gold association price board). A fetch costs no search.
2. Then use web_search for whatever is still missing or older than the previous as_of, grouping several items per query. A good plan for at most 6 searches:
   a) gold spot price + Brent + WTI crude today
   b) ราคาทองคำ สมาคมค้าทองคำ วันนี้ ประกาศล่าสุด (the latest Thai gold-bar announcement of today)
   c) SET index close today + USD/THB (ดัชนี SET ปิดวันนี้ ค่าเงินบาท)
   d) Bitcoin price + US dollar index DXY + US 10-year Treasury yield
   e) S&P 500, Nasdaq 100 and VIX (cash session if open, otherwise last close; futures only as context in change_th)
   f) Nikkei 225 close today
   You may open a promising result page with web_fetch (quote pages such as tradingeconomics.com, investing.com, cnbc.com, reuters.com, set.or.th, goldtraders.or.th, thairath.co.th).
3. A quote counts as newer when the time it refers to is later than the previous item's as_of. Whenever a reputable source shows a later quote, use it, even if it differs only slightly and even if you could not find an exact match for the previous source. Do not keep an old value just because one particular page did not load.
4. Timestamps: a live quote page or price table shows the current or last price as of the moment you fetched it. Use the page's own quote or "last updated" time when it shows one; otherwise use the fetch time (retrieved_at) for a market that is trading now, or the session close time for a closed session. A search result dated today with a price counts too (use its stated time, or its page date). You do not need a minute-exact timestamp printed next to the number; you must not set as_of later than the current time.
5. When you call the tools from code: web_search(...) and web_fetch(...) return a JSON string, so json.loads it first. A search gives a list of results (url, title, page_age, content); a fetch gives an object whose page text is at ["content"]["source"]["data"].
6. Keep the context small: when you fetch or search from code, print only the lines you need (the rows or sentences that mention the instrument, its price and its time), never whole pages or raw result objects. Every printed character is re-read on each later step and costs money.
7. For the markets that are trading now (see the session list in the user turn), returning the previous value is a failure unless every fetch and search for that item failed; in that case say in change_th what you tried. Keep the previous value and as_of only when the market has not traded since the previous as_of (closed session, weekend, holiday). Say so in change_th.

## Submitting
The submit tool's input must follow its schema exactly: "market" is an object with "note_th" and "items", and "items" is an object keyed by the 13 market keys below (not a list), each with value, change_th, trend, as_of and source. In mode "full", "headlines" is a list of objects. Pass objects as objects, not as JSON strings.

## Market items (key: meaning)
{keys}

Rules for every market item:
- value: a plain decimal number as a string, no thousands separators, no units, no plus sign (e.g. "3903.12", "62500", "4.93").
- as_of: the time the value refers to (the quote time, or the session close time for a closing value), ISO 8601 UTC (e.g. "2026-11-02T07:45:00Z"). It must not be later than the current time. source: the https URL of the page the value came from (a quote page or a reputable outlet).
- For a market that is trading now (gold, oil, FX, the dollar index, US yields, Bitcoin) the value should be from the last hour or two. For a session that closed today (SET, Nikkei, and US indexes after their close) use today's close with the close time as as_of.
- change_th: short Thai text, at most about 140 characters: the change versus the previous close or the last update, with the reason when it is clear (for example "−2.7% วันนี้ จากปิดศุกร์ 113.43 หลังอิหร่านเสนอเปิดฮอร์มุซ"). Use the Unicode minus sign (−) for negative numbers in Thai text.
- trend: "up", "down" or "flat" for the move described in change_th.
- A value that moves more than 15% from the previous value, or an as_of older than the previous one, is rejected automatically and the old item is kept, so double-check large moves against a second source before reporting them.
- note_th: one or two Thai sentences on what this round covers (which prices are intraday and which are closes), in the style of the previous note_th.

## Headlines (mode "full" only)
- Research the news with web_search before submitting (at least 4 searches, grouped by theme), covering the time since the newest previous headline given in the user turn. Themes: Iran / Hormuz; US markets, the Fed and US data; the US midterm elections; Ukraine-Russia; China; Thai politics and economy, the baht and Thai gold; Yemen / Saudi Arabia; plus any other conflict on the globe that made news.
- 12 to 16 items, newest first, about the conflicts on the globe, the world economy and Thailand. Keep at most about 5 older items that are still among the most important; every other item must be newer than the newest previous headline whenever such news exists.
- Sources: prefer primary, major outlets: Reuters, AP, AFP, Bloomberg, BBC, Al Jazeera, CNBC, ไทยรัฐ, มติชน, Bangkok Post, ประชาชาติธุรกิจ, กรุงเทพธุรกิจ, Kyiv Independent. Avoid syndication and aggregator sites (local TV sites re-running wire copy, regional papers re-running IANS, aggregators) when the original is available. One source URL per headline: the article itself, https.
- title_th: a Thai headline of at most about 120 characters, factual, no clickbait, written by you (do not copy foreign headlines word for word).
- time: the publication time of the source article (or the time of the event it reports, if earlier and stated), ISO 8601 UTC, never later than the current time. source_name: the outlet name.
- conflict_id must be one of these ids (the globe links a headline to its conflict pin):
{ids}
  Extra tags:
{extra}
- A kept previous headline keeps its original time; do not refresh its time. Drop an older market headline whose numbers are superseded by the latest prices (for example an oil or gold level that has since moved) and drop items from syndication sites when you have a primary source.

## Run summary (mode "full" only)
status_message_th: one Thai paragraph (at most about 400 characters) saying what changed in this round: the biggest market moves and the main news themes.

## Text rules
- All *_th fields are Thai. Keep tickers, index names and outlet names in their usual Latin spelling.
- Never use the ASCII double-quote character in any text field; use Thai wording or “ ” if a quotation is unavoidable.
- Report facts from your searches only; never invent a number, a time or a URL. If you are unsure of a value, keep the previous one.
- This is an information page, not investment advice; do not add recommendations."""


def _item_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["value", "change_th", "trend", "as_of", "source"],
        "properties": {
            "value": {"type": "string", "description": "plain decimal number, no commas/units"},
            "change_th": {"type": "string"},
            "trend": {"type": "string", "enum": ["up", "down", "flat"]},
            "as_of": {"type": "string", "description": "ISO 8601 UTC"},
            "source": {"type": "string", "description": "https URL"},
        },
    }


def _market_schema() -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["note_th", "items"],
        "properties": {
            "note_th": {"type": "string"},
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(MARKET_KEYS),
                "properties": {k: _item_schema() for k in MARKET_KEYS},
            },
        },
    }


def submit_tool(mode: str, skip_prices: bool = False) -> dict:
    # strict is off: the API rejects the compiled grammar of these schemas as too large. write_docs validates every
    # submitted input with jsonschema and the sanity checks, so a malformed submission never reaches the site.
    if mode == "prices":
        return {
            "name": "submit_prices",
            "description": "Submit the updated 13 market items. Call exactly once, at the end, after searching.",
            "strict": False,  # strict grammar for this schema is too large for the API; output is validated with jsonschema
            "input_schema": {"type": "object", "additionalProperties": False, "required": ["market"],
                             "properties": {"market": _market_schema()}},
        }
    tool = {
        "name": "submit_full",
        "description": "Submit the updated market items, 12-16 headlines and the run summary. Call exactly once, at the end, after searching.",
        "strict": False,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["market", "headlines", "status_message_th"],
            "properties": {
                "market": _market_schema(),
                "headlines": {
                    "type": "array",
                    "description": "12 to 16 items, newest first",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["conflict_id", "title_th", "time", "source", "source_name"],
                        "properties": {
                            "conflict_id": {"type": "string", "enum": allowed_conflict_ids()},
                            "title_th": {"type": "string"},
                            "time": {"type": "string", "description": "ISO 8601 UTC"},
                            "source": {"type": "string", "description": "https URL of the article"},
                            "source_name": {"type": "string"},
                        },
                    },
                },
                "status_message_th": {"type": "string"},
            },
        },
    }
    if skip_prices:   # prices are fresh: the model submits news + summary only
        del tool["input_schema"]["properties"]["market"]
        tool["input_schema"]["required"].remove("market")
        tool["description"] = "Submit 12-16 headlines and the run summary (prices are fresh this run). Call exactly once, at the end, after searching the news."
    return tool


def tools_for(mode: str, skip_prices: bool = False) -> list[dict]:
    return [
        {
            "type": "web_search_20260209",   # dynamic filtering; no separate code_execution tool
            "name": "web_search",
            "max_uses": MAX_SEARCHES[mode],
            "user_location": {"type": "approximate", "timezone": "Asia/Bangkok"},  # web search rejects country TH
        },
        {
            # web_fetch_20260309 = dynamic filtering (as 20260209) + use_cache, so quote pages are fetched fresh;
            # no per-use fee, only tokens, capped by max_uses x max_content_tokens
            "type": "web_fetch_20260309",
            "name": "web_fetch",
            "max_uses": MAX_FETCHES[mode],
            "max_content_tokens": FETCH_MAX_CONTENT_TOKENS,
            "use_cache": False,
        },
        submit_tool(mode, skip_prices),
    ]


# quote pages the model may fetch without searching (web_fetch only opens URLs that appear in the conversation)
QUOTE_PAGES = [
    ("https://tradingeconomics.com/commodities", "Brent, WTI, gold"),
    ("https://tradingeconomics.com/currencies", "the dollar index DXY and major pairs"),
    ("https://tradingeconomics.com/thailand/currency", "USD/THB (the baht is often missing from the main currencies table)"),
    ("https://tradingeconomics.com/stocks", "S&P 500, Nasdaq 100, Nikkei 225, SET"),
    ("https://tradingeconomics.com/bonds", "US 10-year yield"),
    ("https://www.goldtraders.or.th/", "Thai gold association price board (96.5% bar, sell)"),
]


def _fmt_local(t: dt.datetime, tz: dt.tzinfo, label: str) -> str:
    lt = t.astimezone(tz)
    return f"{lt:%a %H:%M} {label}"


def market_sessions(now: dt.datetime) -> list[str]:
    """Plain-language session state for each market at `now` (weekday hours; local holidays not known)."""
    from zoneinfo import ZoneInfo

    bkk, tokyo, ny = ZoneInfo("Asia/Bangkok"), ZoneInfo("Asia/Tokyo"), ZoneInfo("America/New_York")
    b, t, n = now.astimezone(bkk), now.astimezone(tokyo), now.astimezone(ny)

    def within(lt, start, end):
        m = lt.hour * 60 + lt.minute
        return lt.weekday() < 5 and start <= m < end

    def state(lt, sessions, close_label):
        if lt.weekday() >= 5:
            return "closed (weekend): use the last close of Friday"
        m = lt.hour * 60 + lt.minute
        if any(a <= m < z for a, z in sessions):
            return "OPEN now: use an intraday quote from the last hour or two"
        if m >= sessions[-1][1]:
            return f"closed for the day ({close_label}): use today's close"
        if m < sessions[0][0]:
            return "not open yet today: use the previous session's close"
        return "lunch break: use the latest quote of today's morning session"

    # US futures/FX/commodities: Sunday 18:00 to Friday 17:00 New York time, daily pause 17:00-18:00
    nm = n.hour * 60 + n.minute
    globex = not (n.weekday() == 5 or (n.weekday() == 6 and nm < 18 * 60) or (n.weekday() == 4 and nm >= 17 * 60) or (17 * 60 <= nm < 18 * 60))
    us_cash = state(n, [(9 * 60 + 30, 16 * 60)], "closed 16:00 New York")
    return [
        f"Bangkok {_fmt_local(now, bkk, '(UTC+7)')}, Tokyo {_fmt_local(now, tokyo, '(UTC+9)')}, New York {_fmt_local(now, ny, n.tzname() or '')}",
        f"gold spot, Brent, WTI, DXY, USD/THB, US 10-year yield: {'trading now (nearly 24 h on weekdays): use a quote from the last hour or two' if globex else 'not trading now: use the last quote before the pause/weekend'}",
        "Bitcoin: trades 24/7: use a quote from the last hour",
        f"SET (Bangkok 10:00-12:30, 14:30-16:30): {state(b, [(10 * 60, 12 * 60 + 30), (14 * 60 + 30, 16 * 60 + 30)], 'closed 16:30 Bangkok')}",
        f"Nikkei 225 (Tokyo 09:00-11:30, 12:30-15:30): {state(t, [(9 * 60, 11 * 60 + 30), (12 * 60 + 30, 15 * 60 + 30)], 'closed 15:30 Tokyo')}",
        f"S&P 500, Nasdaq 100, VIX cash session (New York 09:30-16:00): {us_cash}; US index futures are {'trading' if globex else 'not trading'} (mention them in change_th only)",
        f"Thai gold association (announces several times on business days, about 09:00-17:30 Bangkok): {'announcing today: use the latest announcement of today' if within(b, 9 * 60, 17 * 60 + 30) else 'use the latest announcement (today if there was one)'}",
    ]


def user_message(mode: str, prev: dict, now: dt.datetime, skip_prices: bool = False) -> str:
    if skip_prices:
        age = prices_age_min(prev["market"], now) or 0
        parts = [
            f"Mode: {mode} (news run; prices are fresh)",
            f"Current time: {iso(now)} (Bangkok {bkk_th(now)})",
            f"Prices: market.json was updated {age:.0f} minutes ago by the prices run, so do not search or fetch prices in this run "
            "and do not submit a market field. Spend the budget on news.",
            f"Budgets for this run: web_search at most {MAX_SEARCHES[mode]} searches; web_fetch at most {MAX_FETCHES[mode]} pages.",
            f"Previous headlines.json (newest item {headlines_since(prev['headlines'])}; search the news published since then):",
            "```json\n" + json.dumps(prev["headlines"], ensure_ascii=False, indent=1) + "\n```",
            "Latest prices, for the run summary only:",
            "```json\n" + json.dumps({i["key"]: [i["value"], i["change_th"]] for i in prev["market"]["items"]}, ensure_ascii=False) + "\n```",
            f"Search the news (at least {MIN_NEWS_SEARCHES} searches, grouped by theme), then call submit_full once with 12-16 headlines and status_message_th.",
        ]
        return "\n\n".join(parts)
    parts = [
        f"Mode: {mode}",
        f"Current time: {iso(now)} (Bangkok {bkk_th(now)})",
        "Market sessions right now (computed from the clock; local holidays are not known):\n" + "\n".join("- " + x for x in market_sessions(now)),
        f"Budgets for this run: web_search at most {MAX_SEARCHES[mode]} searches; web_fetch at most {MAX_FETCHES[mode]} pages.",
        "Quote pages you may fetch directly:\n" + "\n".join(f"- {u} ({what})" for u, what in QUOTE_PAGES),
        "Previous market.json (an item is refreshed when you give a value whose as_of is later than the as_of below):",
        "```json\n" + json.dumps(prev["market"], ensure_ascii=False, indent=1) + "\n```",
    ]
    if mode == "full":
        parts += [f"Previous headlines.json (newest item {headlines_since(prev['headlines'])}; search the news published since then):",
                  "```json\n" + json.dumps(prev["headlines"], ensure_ascii=False, indent=1) + "\n```"]
        parts.append(f"Follow the price plan, search the news (at least {MIN_NEWS_SEARCHES} searches, grouped by theme), then call submit_full once with all 13 market items, 12-16 headlines and status_message_th.")
    else:
        parts.append("Follow the plan, then call submit_prices once with all 13 market items.")
    return "\n\n".join(parts)


# ----------------------------------------------------------------- usage + cost
@dataclass
class Usage:
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    web_searches: int = 0
    web_fetches: int = 0
    served_by: list[str] = field(default_factory=list)
    stop_reasons: list[str] = field(default_factory=list)

    def add(self, resp: Any) -> None:
        u = getattr(resp, "usage", None)
        self.requests += 1
        self.stop_reasons.append(str(getattr(resp, "stop_reason", "")))
        m = getattr(resp, "model", None)
        if m and m not in self.served_by:
            self.served_by.append(str(m))
        if u is None:
            return
        self.input_tokens += int(getattr(u, "input_tokens", 0) or 0)
        self.output_tokens += int(getattr(u, "output_tokens", 0) or 0)
        self.cache_write_tokens += int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        self.cache_read_tokens += int(getattr(u, "cache_read_input_tokens", 0) or 0)
        stu = getattr(u, "server_tool_use", None)
        self.web_searches += int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
        self.web_fetches += int(getattr(stu, "web_fetch_requests", 0) or 0) if stu is not None else 0

    def cost_usd(self) -> float:
        return round(
            self.input_tokens * PRICE["input"] / 1e6
            + self.output_tokens * PRICE["output"] / 1e6
            + self.cache_write_tokens * PRICE["cache_write_5m"] / 1e6
            + self.cache_read_tokens * PRICE["cache_read"] / 1e6
            + self.web_searches * WEB_SEARCH_USD,
            6,
        )


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


def log_cost(mode: str, ok: bool, usage: Usage, note: str, now: dt.datetime, cost_log: pathlib.Path,
             items_changed: int | None = None) -> None:
    row = {
        "time_utc": iso(now), "mode": mode, "ok": "yes" if ok else "no",
        "model": "+".join(usage.served_by) or MODEL, "requests": usage.requests,
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cache_write_tokens": usage.cache_write_tokens, "cache_read_tokens": usage.cache_read_tokens,
        "web_searches": usage.web_searches, "cost_usd": f"{usage.cost_usd():.4f}", "note": note[:200],
        "web_fetches": usage.web_fetches, "items_changed": "" if items_changed is None else items_changed,
    }
    print(f"usage: requests={usage.requests} input={usage.input_tokens} output={usage.output_tokens} "
          f"cache_write={usage.cache_write_tokens} cache_read={usage.cache_read_tokens} "
          f"web_searches={usage.web_searches} web_fetches={usage.web_fetches} stop={','.join(usage.stop_reasons)} served_by={row['model']}")
    print(f"estimated cost: ${usage.cost_usd():.4f} USD ({mode}, {'ok' if ok else 'FAILED'})")
    if items_changed is not None:
        print(f"items changed: {items_changed}/{len(MARKET_KEYS)}")
    _migrate_csv(cost_log)
    new = not cost_log.exists() or cost_log.stat().st_size == 0
    cost_log.parent.mkdir(parents=True, exist_ok=True)
    with cost_log.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(
                f"### อัปเดตข้อมูล ({mode}) {'สำเร็จ' if ok else 'ไม่สำเร็จ'}\n\n"
                f"| รายการ | ค่า |\n|---|---|\n"
                f"| โมเดล | {row['model']} |\n| คำขอ API | {usage.requests} |\n"
                f"| input tokens | {usage.input_tokens:,} |\n| output tokens | {usage.output_tokens:,} |\n"
                f"| cache write / read | {usage.cache_write_tokens:,} / {usage.cache_read_tokens:,} |\n"
                f"| web searches | {usage.web_searches} (เพดาน {MAX_SEARCHES.get(mode, '-')}) |\n"
                f"| web fetches | {usage.web_fetches} (เพดาน {MAX_FETCHES.get(mode, '-')}) |\n"
                + (f"| ราคาที่เปลี่ยน | {items_changed}/{len(MARKET_KEYS)} |\n" if items_changed is not None else "")
                + f"| ค่าใช้จ่ายโดยประมาณ | **${usage.cost_usd():.4f}** |\n\n"
                + (f"หมายเหตุ: {note}\n\n" if note else "")
            )


# ----------------------------------------------------------------- the model call
def _short(x: Any, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(x if x is not None else "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def trace_lines(content: Any) -> list[str]:
    """One line per server-tool call/result and per text note, for the Actions log (no secrets in here)."""
    out = []
    for b in content or []:
        t = getattr(b, "type", "")
        if t == "server_tool_use":
            out.append(f"{getattr(b, 'name', '?')} {_short(json.dumps(getattr(b, 'input', {}), ensure_ascii=False), 200)}")
        elif t == "web_search_tool_result":
            c = getattr(b, "content", None)
            if isinstance(c, list):
                tops = "; ".join(f"{_short(getattr(r, 'title', ''), 60)} [{getattr(r, 'page_age', '') or '-'}]" for r in c[:3])
                out.append(f"  search -> {len(c)} results: {tops}")
            else:
                out.append(f"  search -> error {getattr(c, 'error_code', c)}")
        elif t == "web_fetch_tool_result":
            c = getattr(b, "content", None)
            if getattr(c, "type", "") == "web_fetch_result":
                doc = getattr(c, "content", None)
                src = getattr(doc, "source", None)
                size = len(getattr(src, "data", "") or "") if src is not None else 0
                out.append(f"  fetch -> {getattr(c, 'url', '?')} retrieved {getattr(c, 'retrieved_at', '?')} ({size} chars)")
            else:
                out.append(f"  fetch -> error {getattr(c, 'error_code', c)}")
        elif t in ("bash_code_execution_tool_result", "code_execution_tool_result"):
            c = getattr(b, "content", None)
            out.append(f"  code -> rc={getattr(c, 'return_code', '?')} stdout: {_short(getattr(c, 'stdout', ''), 300)}")
        elif t == "text" and getattr(b, "text", "").strip():
            out.append(f"text: {_short(b.text, 300)}")
        elif t == "tool_use":
            out.append(f"{getattr(b, 'name', '?')} (submit)")
    return out


def make_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=anthropic.Timeout(600.0, connect=15.0))


def _maybe_json(v: Any) -> Any:
    if isinstance(v, str) and v.strip()[:1] in ("{", "["):
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


ITEM_FIELDS = ("value", "change_th", "trend", "as_of", "source")


def normalize_submission(mode: str, data: Any) -> Any:
    """Repair the shapes a non-strict tool call is known to produce before validating it:
    nested objects sent as JSON strings, market items sent as a list of {key, ...} (the file format),
    items placed directly in `market`, or the market fields placed at the top level."""
    data = _maybe_json(data)
    if not isinstance(data, dict):
        return data
    data = dict(data)
    if "market" not in data and ("items" in data or any(k in data for k in MARKET_KEYS)) and isinstance(data.get("items", {}), (dict, list)):
        moved = {k: data.pop(k) for k in list(data) if k in ("items", "note_th") or k in MARKET_KEYS}
        data = {"market": moved, **data}
    market = _maybe_json(data.get("market"))
    if isinstance(market, dict):
        market = dict(market)
        items = _maybe_json(market.get("items"))
        if items is None and any(k in market for k in MARKET_KEYS):
            items = {k: market.pop(k) for k in list(market) if k in MARKET_KEYS}
        if isinstance(items, list):
            items = {str(i.get("key")): i for i in items if isinstance(i, dict) and i.get("key")}
        if isinstance(items, dict):
            fixed = {}
            for k, v in items.items():
                v = _maybe_json(v)
                if isinstance(v, dict):
                    v = {f: x for f, x in v.items() if f in ITEM_FIELDS}
                    if isinstance(v.get("value"), (int, float)) and not isinstance(v.get("value"), bool):
                        v["value"] = str(v["value"])
                fixed[k] = v
            items = fixed
        if items is not None:
            market["items"] = items
        data["market"] = market
    if mode == "full" and "headlines" in data:
        data["headlines"] = _maybe_json(data.get("headlines"))
    return data


def submission_errors(mode: str, data: Any, skip_prices: bool = False) -> list[str]:
    import jsonschema

    v = jsonschema.Draft202012Validator(submit_tool(mode, skip_prices)["input_schema"])
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {_short(e.message, 160)}" for e in v.iter_errors(data)]


def shape_of(data: Any) -> str:
    def t(v):
        return type(v).__name__ + (f"({len(v)})" if isinstance(v, (list, dict)) else "")
    if not isinstance(data, dict):
        return t(data)
    parts = []
    for k, v in data.items():
        if isinstance(v, dict):
            parts.append(f"{k}{{" + _short(", ".join(f"{ik}:{t(iv)}" for ik, iv in v.items()), 200) + "}")
        else:
            parts.append(f"{k}:{t(v)}")
    return "; ".join(parts)


def call_model(client: Any, mode: str, prev: dict, now: dt.datetime, usage: Usage, skip_prices: bool = False) -> tuple[dict, bool]:
    """Run the search + submit loop. Returns (the submit tool's input, whether a full run searched the news)."""
    import anthropic

    submit_name = "submit_prices" if mode == "prices" else "submit_full"
    tools = tools_for(mode, skip_prices)        # identical on every request of the run
    system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
    messages: list[dict] = [{"role": "user", "content": [
        {"type": "text", "text": user_message(mode, prev, now, skip_prices), "cache_control": {"type": "ephemeral"}}]}]
    nudged = fixed_once = news_nudged = False
    started = time.monotonic()
    for _ in range(MAX_REQUESTS):
        if time.monotonic() - started > DEADLINE_S:
            raise UpdateError("deadline reached", "ใช้เวลานานเกินกำหนด")
        try:
            with client.beta.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                tools=tools,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": EFFORT},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                resp = stream.get_final_message()
        except anthropic.AuthenticationError as e:
            raise UpdateError(f"authentication failed ({type(e).__name__})", "คีย์ API ใช้ไม่ได้") from None
        except anthropic.PermissionDeniedError as e:
            raise UpdateError(f"permission denied ({type(e).__name__})", "คีย์ API ไม่มีสิทธิ์ใช้โมเดลหรือการค้นเว็บ") from None
        except anthropic.NotFoundError as e:
            raise UpdateError(f"not found: {getattr(e, 'message', e)}", "ไม่พบโมเดลหรือ endpoint") from None
        except anthropic.RateLimitError as e:
            raise UpdateError(f"rate limited: {getattr(e, 'message', e)}", "ติดขีดจำกัดอัตราการเรียก API หรือวงเงินรายเดือน") from None
        except anthropic.BadRequestError as e:
            raise UpdateError(f"bad request: {getattr(e, 'message', e)}", "คำขอ API ไม่ถูกต้อง") from None
        except anthropic.APIStatusError as e:
            raise UpdateError(f"API error {e.status_code}: {getattr(e, 'message', e)}", f"เซิร์ฟเวอร์ API ขัดข้อง ({e.status_code})") from None
        except anthropic.APIConnectionError as e:
            raise UpdateError(f"connection error: {type(e).__name__}", "เชื่อมต่อ API ไม่ได้") from None
        usage.add(resp)
        for line in trace_lines(resp.content):
            print("trace: " + line)

        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            raise UpdateError(f"model declined (refusal, category={cat})", "โมเดลปฏิเสธคำขอรอบนี้")
        submit = next((b for b in resp.content if getattr(b, "type", None) == "tool_use" and getattr(b, "name", None) == submit_name), None)
        if submit is not None:
            data = normalize_submission(mode, submit.input)
            if skip_prices and isinstance(data, dict):
                data.pop("market", None)          # prices are fresh this run; ignore any market sent anyway
            print("trace: submitted shape " + shape_of(data))
            errs = submission_errors(mode, data, skip_prices)
            if not errs and mode == "full" and usage.web_searches < MIN_NEWS_SEARCHES:
                if news_nudged:
                    print(f"trace: full run submitted after only {usage.web_searches} searches; headlines will not be replaced")
                    return data, False
                news_nudged = True
                print(f"trace: submit_full rejected: only {usage.web_searches} web searches so far")
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": submit.id, "is_error": True,
                    "content": f"Rejected: the headlines were not researched (only {usage.web_searches} web searches this run). "
                               f"Search the news published since {headlines_since(prev['headlines'])} with at least {MIN_NEWS_SEARCHES} grouped searches "
                               f"({'; '.join(NEWS_TOPICS)}), then call submit_full again. Keep at most about 5 of the previous headlines.",
                }]})
                continue
            if not errs:
                return data, mode == "full"
            # the submit tool is not strict (its grammar is too large), so a malformed call gets one
            # is_error tool_result asking for a corrected call; the history stays append-only
            if fixed_once:
                raise UpdateError("submit input still invalid: " + "; ".join(errs[:3]), "ผลลัพธ์จากโมเดลไม่อยู่ในรูปแบบที่กำหนด")
            fixed_once = True
            print("trace: submit rejected: " + "; ".join(errs[:5]))
            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": submit.id, "is_error": True,
                "content": f"Rejected: the input does not match the {submit_name} schema: " + "; ".join(errs[:8])
                           + f". Call {submit_name} again with the corrected, complete input. Do not search again.",
            }]})
            continue
        if resp.stop_reason == "max_tokens":
            raise UpdateError("hit max_tokens before submitting", "คำตอบยาวเกินกำหนดก่อนส่งผลลัพธ์")
        # keep the history append-only (preserved thinking + prompt cache)
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason == "pause_turn":
            if usage.web_searches >= MAX_SEARCHES[mode]:
                raise UpdateError(f"search budget used up ({usage.web_searches}) and the turn paused",
                                  "ใช้งบค้นเว็บครบแล้วแต่ยังไม่ได้ผลลัพธ์")
            continue                              # server resumes the paused turn
        if nudged:
            raise UpdateError(f"no {submit_name} call (stop_reason={resp.stop_reason})", "โมเดลไม่ส่งผลลัพธ์ผ่านเครื่องมือที่กำหนด")
        nudged = True
        messages.append({"role": "user", "content": f"Do not search any more. Call {submit_name} now with your best data; keep previous values where you could not check."})
    raise UpdateError("too many requests without a result", "เรียก API หลายรอบแต่ยังไม่ได้ผลลัพธ์")


# ----------------------------------------------------------------- files
def load_previous(data_dir: pathlib.Path) -> tuple[dict, list[str]]:
    prev, errs = {}, []
    for name in DOCS:
        path = data_dir / f"{name}.json"
        try:
            prev[name] = load_json(path)
        except (OSError, ValueError) as e:
            errs.append(f"{name}: cannot read {path.name}: {e}")
            continue
        errs += validate_doc(name, prev[name])
    return prev, errs


def write_docs(data_dir: pathlib.Path, docs: dict[str, dict]) -> None:
    """Validate everything first, then replace the files atomically (temp file + os.replace)."""
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


def failure_status(prev_status: dict | None, message_th: str, now: dt.datetime) -> dict:
    return {
        "updated_at": iso(now),
        "run_count": int((prev_status or {}).get("run_count", 0)) + 1,
        "ok": False,
        "message_th": clean_th(f"อัปเดตอัตโนมัติไม่สำเร็จ ({message_th}) {bkk_th(now)} แสดงค่าล่าสุดที่ได้รับ", 400),
    }


def build_docs(mode: str, prev: dict, result: dict, now: dt.datetime, skip_prices: bool = False,
               news_searched: bool = True) -> tuple[dict[str, dict], list[str], int | None]:
    docs: dict[str, dict] = {}
    notes: list[str] = []
    changed: int | None = None
    if skip_prices:
        age = prices_age_min(prev["market"], now) or 0
        tail = f"ราคาคงชุดรอบราคาเมื่อ {age:.0f} นาทีก่อน"
    else:
        market_in = result.get("market") or {}
        items, notes = sanity_market(prev["market"], market_in.get("items") or {})
        missing = [n for n in notes if n.endswith(": missing")]
        if len(missing) > 3:      # never overwrite good data with a page full of stale markers
            raise UpdateError(f"{len(missing)} market items missing from the submission",
                              f"ผลลัพธ์จากโมเดลขาดราคา {len(missing)} รายการ")
        docs["market"] = {"updated_at": iso(now), "note_th": clean_th(market_in.get("note_th"), 500) or prev["market"]["note_th"], "items": items}
        changed = count_changed(prev["market"]["items"], items)
        total = len(items)
        rejected = sum(1 for n in notes if "older than" not in n)
        tail = (f"ราคาเปลี่ยน {changed}/{total} รายการ" if changed else f"รอบนี้ไม่พบราคาใหม่กว่ารอบก่อน (เปลี่ยน 0/{total} รายการ)") \
            + (f" ไม่ผ่านการตรวจ {rejected} รายการ" if rejected else "")
    if mode == "full":
        summary = clean_th(result.get("status_message_th"), 400)
        if not news_searched:
            news = "ข่าวไม่ได้อัปเดตรอบนี้ (ไม่ได้ค้นข่าวใหม่) คงชุดเดิม"
            notes.append("headlines: not researched, kept the previous file")
        else:
            h = build_headlines(result.get("headlines") or [], now, prev["headlines"])
            fresh = count_new_headlines(prev["headlines"], h["items"])
            if fresh == 0:
                news = f"ไม่พบข่าวใหม่ คงชุดเดิม {len(prev['headlines'].get('items', []))} ข่าว"
                notes.append("headlines: nothing new, kept the previous file")
            else:
                docs["headlines"] = h
                news = f"ข่าวใหม่ {fresh} จาก {len(h['items'])} ข่าว"
        message = clean_th(f"{summary} · {tail} · {news}" if summary else f"อัปเดตเต็มรอบอัตโนมัติ {bkk_th(now)} · {tail} · {news}", 600)
    else:
        message = f"อัปเดตราคาอัตโนมัติ {bkk_th(now)} · {tail} · ข่าวคงชุดเดิม"
    docs["status"] = {"updated_at": iso(now), "run_count": int(prev["status"].get("run_count", 0)) + 1, "ok": True, "message_th": message}
    return docs, notes, changed


def run(mode: str, data_dir: pathlib.Path = DATA_DIR, client: Any = None, cost_log: pathlib.Path | None = None,
        now: dt.datetime | None = None) -> int:
    now = now or utcnow()
    cost_log = cost_log or COST_LOG
    prev, errs = load_previous(data_dir)
    if errs:
        print("previous data files are invalid; refusing to run:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 2
    usage = Usage()
    try:
        age = prices_age_min(prev["market"], now)
        skip_prices = mode == "full" and age is not None and 0 <= age < PRICES_FRESH_MIN
        if skip_prices:
            print(f"prices are {age:.0f} min old: this full run researches news only")
        result, news_searched = call_model(client, mode, prev, now, usage, skip_prices)
        docs, notes, changed = build_docs(mode, prev, result, now, skip_prices, news_searched)
        write_docs(data_dir, docs)
    except UpdateError as e:
        print(f"update FAILED: {e}", file=sys.stderr)
        try:
            write_docs(data_dir, {"status": failure_status(prev.get("status"), e.message_th, now)})
        except UpdateError as e2:  # pragma: no cover - the failure status is built from fixed text
            print(f"could not write the failure status: {e2}", file=sys.stderr)
        log_cost(mode, False, usage, str(e), now, cost_log)
        return 1
    for n in notes:
        print(f"sanity: {n}")
    print(f"wrote {', '.join(f'{n}.json' for n in docs)} in {data_dir}")
    log_cost(mode, True, usage, "; ".join(notes), now, cost_log, items_changed=changed)
    return 0


def dry_run(data_dir: pathlib.Path = DATA_DIR) -> int:
    prev, errs = load_previous(data_dir)
    if not errs:
        # the request we would send must build too
        system_prompt(), tools_for("prices"), tools_for("full"), tools_for("full", True)
        user_message("full", prev, utcnow()), user_message("full", prev, utcnow(), True)
        bad = [c for c in (i["conflict_id"] for i in prev["headlines"]["items"]) if c not in allowed_conflict_ids()]
        errs += [f"headlines: conflict_id {c!r} not allowed" for c in bad]
    if errs:
        print("dry run: INVALID\n  " + "\n  ".join(errs))
        return 1
    m, h, s = prev["market"], prev["headlines"], prev["status"]
    print(f"dry run: OK - market {len(m['items'])} items (updated {m['updated_at']}), "
          f"headlines {len(h['items'])} (updated {h['updated_at']}), status run {s['run_count']} ok={s['ok']}")
    print(f"dry run: model {MODEL}, effort {EFFORT}, search caps {MAX_SEARCHES}, fetch caps {MAX_FETCHES}, no API call made")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", nargs="?", choices=["prices", "full"], help="prices: market values only; full: market + headlines + status")
    ap.add_argument("--dry-run", action="store_true", help="skip the API call; validate the current data files")
    ap.add_argument("--data-dir", type=pathlib.Path, default=DATA_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.dry_run:
        return dry_run(args.data_dir)
    if not args.mode:
        ap.error("mode is required (prices or full) unless --dry-run")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("ANTHROPIC_API_KEY is not set. Add it as a repository secret (Settings > Secrets and variables > "
              "Actions > New repository secret) or export it locally. Nothing was changed.", file=sys.stderr)
        return 2
    return run(args.mode, args.data_dir, client=make_client(key))


if __name__ == "__main__":
    sys.exit(main())
