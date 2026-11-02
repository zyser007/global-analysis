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
HEADLINES_MIN, HEADLINES_MAX = 12, 16
MAX_MOVE = 0.15                      # reject a market value that moved more than 15 %
MAX_REQUESTS = 4                     # first call + pause_turn continuations + one nudge
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


def _stale(old: dict, why: str) -> dict:
    item = copy.deepcopy(old)
    item["change_th"] = clean_th(f"{STALE_PREFIX} ({why})", 220)
    return item


def build_headlines(items: list[dict], now: dt.datetime) -> dict:
    allowed = set(allowed_conflict_ids())
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
        if row["title_th"] and re.match(r"^https?://\S+$", src) and '"' not in src and row["source_name"]:
            rows.append(row)
    rows.sort(key=lambda r: r["time"], reverse=True)
    rows = rows[:HEADLINES_MAX]
    if len(rows) < HEADLINES_MIN:
        raise UpdateError(f"only {len(rows)} usable headlines (need {HEADLINES_MIN}-{HEADLINES_MAX})",
                          f"ได้พาดหัวข่าวที่ใช้ได้เพียง {len(rows)} ข่าว ต้องมี {HEADLINES_MIN}–{HEADLINES_MAX} ข่าว")
    return {"updated_at": iso(now), "items": [{"id": f"h{i + 1}", **r} for i, r in enumerate(rows)]}


# ----------------------------------------------------------------- prompt + tools
def system_prompt() -> str:
    """Stable across runs and modes (cached). Never put the date or the previous data here."""
    keys = "\n".join(f"- {k}: {v}" for k, v in MARKET_KEYS.items())
    ids = "\n".join(f"- {c}" for c in allowed_conflict_ids())
    extra = "\n".join(f"- {k}: {v}" for k, v in TAGS_EXTRA.items())
    return f"""You maintain the live data files of a public Thai-language website: a 3D globe of world conflicts, economies and markets, with a gold-price panel. Readers are in Thailand. You run unattended on a schedule; nobody reads your text replies, only the data you submit through the submit tool.

## Job
Use the web_search tool to check current values, then call the submit tool exactly once with the complete result. The user turn gives the run mode, the current time, the search budget and the previous files.
- Mode "prices": update the 13 market items only. Call submit_prices.
- Mode "full": update the 13 market items, write 12 to 16 fresh headlines, and a one-paragraph run summary. Call submit_full.
Spend the search budget on what is most likely to have moved: queries that cover several instruments at once (for example a markets wrap or a quotes page) are better than one query per instrument. If the budget runs out, submit what you have: for an instrument you could not re-check, return the previous value, as_of and source unchanged and say in change_th that it is the previous value.

## Market items (key: meaning)
{keys}

Rules for every market item:
- value: a plain decimal number as a string, no thousands separators, no units, no plus sign (e.g. "3903.12", "62500", "4.93").
- Only change what moved. If the market is closed or nothing newer exists, keep the previous value and as_of, and say so in change_th (for example that it is the Friday close).
- as_of: the time the value refers to, ISO 8601 UTC (e.g. "2026-11-02T07:45:00Z"). source: the https URL of the page the value came from (a quote page or a reputable outlet).
- change_th: short Thai text, at most about 140 characters: the change versus the previous close or the last update, with the reason when it is clear (for example "−2.7% วันนี้ จากปิดศุกร์ 113.43 หลังอิหร่านเสนอเปิดฮอร์มุซ"). Use the Unicode minus sign (−) for negative numbers in Thai text.
- trend: "up", "down" or "flat" for the move described in change_th.
- A value that moves more than 15% from the previous value is rejected automatically and the old one is kept, so double-check large moves against a second source before reporting them.
- note_th: one or two Thai sentences on what this round covers (which prices are intraday and which are closes), in the style of the previous note_th.

## Headlines (mode "full" only)
- 12 to 16 items, newest first, from the last 24-36 hours, about the conflicts on the globe, the world economy and Thailand. Prefer wire services and major outlets; one source URL per headline (the article itself, https).
- title_th: a Thai headline of at most about 120 characters, factual, no clickbait, written by you (do not copy foreign headlines word for word).
- time: when the event or article happened, ISO 8601 UTC. source_name: the outlet name.
- conflict_id must be one of these ids (the globe links a headline to its conflict pin):
{ids}
  Extra tags:
{extra}
- Keep a previous headline only if it is still among the most important and still recent.

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


def submit_tool(mode: str) -> dict:
    # strict: true -> the input always matches the schema. eager_input_streaming is left off on purpose:
    # it would turn the server-side validation off and nothing here consumes the partial input.
    if mode == "prices":
        return {
            "name": "submit_prices",
            "description": "Submit the updated 13 market items. Call exactly once, at the end, after searching.",
            "strict": True,
            "input_schema": {"type": "object", "additionalProperties": False, "required": ["market"],
                             "properties": {"market": _market_schema()}},
        }
    return {
        "name": "submit_full",
        "description": "Submit the updated market items, 12-16 headlines and the run summary. Call exactly once, at the end, after searching.",
        "strict": True,
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


def tools_for(mode: str) -> list[dict]:
    return [
        {
            "type": "web_search_20260209",   # dynamic filtering; no separate code_execution tool
            "name": "web_search",
            "max_uses": MAX_SEARCHES[mode],
            "user_location": {"type": "approximate", "timezone": "Asia/Bangkok"},  # web search rejects country TH
        },
        submit_tool(mode),
    ]


def user_message(mode: str, prev: dict, now: dt.datetime) -> str:
    parts = [
        f"Mode: {mode}",
        f"Current time: {iso(now)} (Bangkok {bkk_th(now)})",
        f"Web search budget for this run: {MAX_SEARCHES[mode]} searches in total.",
        "Previous market.json:",
        "```json\n" + json.dumps(prev["market"], ensure_ascii=False, indent=1) + "\n```",
    ]
    if mode == "full":
        parts += ["Previous headlines.json:", "```json\n" + json.dumps(prev["headlines"], ensure_ascii=False, indent=1) + "\n```"]
        parts.append("Search, then call submit_full once with the market items, 12-16 headlines and status_message_th.")
    else:
        parts.append("Search, then call submit_prices once with all 13 market items.")
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
              "cache_write_tokens", "cache_read_tokens", "web_searches", "cost_usd", "note"]


def log_cost(mode: str, ok: bool, usage: Usage, note: str, now: dt.datetime, cost_log: pathlib.Path) -> None:
    row = {
        "time_utc": iso(now), "mode": mode, "ok": "yes" if ok else "no",
        "model": "+".join(usage.served_by) or MODEL, "requests": usage.requests,
        "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
        "cache_write_tokens": usage.cache_write_tokens, "cache_read_tokens": usage.cache_read_tokens,
        "web_searches": usage.web_searches, "cost_usd": f"{usage.cost_usd():.4f}", "note": note[:200],
    }
    print(f"usage: requests={usage.requests} input={usage.input_tokens} output={usage.output_tokens} "
          f"cache_write={usage.cache_write_tokens} cache_read={usage.cache_read_tokens} "
          f"web_searches={usage.web_searches} stop={','.join(usage.stop_reasons)} served_by={row['model']}")
    print(f"estimated cost: ${usage.cost_usd():.4f} USD ({mode}, {'ok' if ok else 'FAILED'})")
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
                f"| ค่าใช้จ่ายโดยประมาณ | **${usage.cost_usd():.4f}** |\n\n"
                + (f"หมายเหตุ: {note}\n\n" if note else "")
            )


# ----------------------------------------------------------------- the model call
def make_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=anthropic.Timeout(600.0, connect=15.0))


def call_model(client: Any, mode: str, prev: dict, now: dt.datetime, usage: Usage) -> dict:
    """Run the search + submit loop. Returns the submit tool's input (a dict)."""
    import anthropic

    submit_name = "submit_prices" if mode == "prices" else "submit_full"
    tools = tools_for(mode)                     # identical on every request of the run
    system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
    messages: list[dict] = [{"role": "user", "content": [
        {"type": "text", "text": user_message(mode, prev, now), "cache_control": {"type": "ephemeral"}}]}]
    nudged = False
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

        if resp.stop_reason == "refusal":
            cat = getattr(getattr(resp, "stop_details", None), "category", None)
            raise UpdateError(f"model declined (refusal, category={cat})", "โมเดลปฏิเสธคำขอรอบนี้")
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == submit_name:
                data = block.input
                if isinstance(data, str):         # defensive: always parse, never string-match
                    data = json.loads(data)
                if not isinstance(data, dict):
                    raise UpdateError("submit input is not an object", "ผลลัพธ์จากโมเดลไม่อยู่ในรูปแบบที่กำหนด")
                return data
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


def build_docs(mode: str, prev: dict, result: dict, now: dt.datetime) -> tuple[dict[str, dict], list[str]]:
    market_in = result.get("market") or {}
    items, notes = sanity_market(prev["market"], market_in.get("items") or {})
    market = {"updated_at": iso(now), "note_th": clean_th(market_in.get("note_th"), 500) or prev["market"]["note_th"], "items": items}
    docs = {"market": market}
    kept = len(notes)
    tail = f"{len(items) - kept}/{len(items)} รายการ" + (f" คงค่าเดิม {kept} รายการที่ตรวจไม่ผ่าน" if kept else "")
    if mode == "full":
        docs["headlines"] = build_headlines(result.get("headlines") or [], now)
        summary = clean_th(result.get("status_message_th"), 400)
        message = clean_th(f"{summary} · ราคา {tail} ข่าว {len(docs['headlines']['items'])} ข่าว" if summary
                           else f"อัปเดตเต็มรอบอัตโนมัติ {bkk_th(now)} ราคา {tail} ข่าว {len(docs['headlines']['items'])} ข่าว", 600)
    else:
        message = f"อัปเดตราคาอัตโนมัติ {bkk_th(now)} ราคา {tail} ข่าวคงชุดเดิม"
    docs["status"] = {"updated_at": iso(now), "run_count": int(prev["status"].get("run_count", 0)) + 1, "ok": True, "message_th": message}
    return docs, notes


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
        result = call_model(client, mode, prev, now, usage)
        docs, notes = build_docs(mode, prev, result, now)
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
        print(f"sanity: kept previous value for {n}")
    print(f"wrote {', '.join(f'{n}.json' for n in docs)} in {data_dir}")
    log_cost(mode, True, usage, "; ".join(notes), now, cost_log)
    return 0


def dry_run(data_dir: pathlib.Path = DATA_DIR) -> int:
    prev, errs = load_previous(data_dir)
    if not errs:
        # the request we would send must build too
        system_prompt(), tools_for("prices"), tools_for("full"), user_message("full", prev, utcnow())
        bad = [c for c in (i["conflict_id"] for i in prev["headlines"]["items"]) if c not in allowed_conflict_ids()]
        errs += [f"headlines: conflict_id {c!r} not allowed" for c in bad]
    if errs:
        print("dry run: INVALID\n  " + "\n  ".join(errs))
        return 1
    m, h, s = prev["market"], prev["headlines"], prev["status"]
    print(f"dry run: OK - market {len(m['items'])} items (updated {m['updated_at']}), "
          f"headlines {len(h['items'])} (updated {h['updated_at']}), status run {s['run_count']} ok={s['ok']}")
    print(f"dry run: model {MODEL}, effort {EFFORT}, search caps {MAX_SEARCHES}, no API call made")
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
