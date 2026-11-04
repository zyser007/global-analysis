#!/usr/bin/env python3
"""Refresh site/data/{headlines,status}.json with Claude + web search (the 08:00 / 20:00 Bangkok full run).

    python updater/update.py full            # 12-16 headlines + run summary (<= 14 web searches)
    python updater/update.py prices          # no AI: runs updater/prices.py (free direct quote feeds)
    python updater/update.py --dry-run       # no API call: validate the current files and exit

Market prices are not researched here any more: updater/prices.py fetches the 13 quotes from free feeds every
hour (and right before every full run in the workflow). The full run reads the fresh market.json only to
write its summary.

Design
- One Messages API call (claude-sonnet-5-5, adaptive thinking, effort medium) with the
  `web_search_20260209` server tool (max_uses enforced) and one client tool (`submit_full`) that carries
  the result. Web search always attaches citations, which structured outputs (output_config.format) rejects,
  so the JSON comes back as the tool's input instead; tool_choice stays "auto" (forced tool choice is a 400
  on this model) and the prompt tells the model to finish with the tool.
- The stable instructions and allowed conflict ids sit in a cached system prompt; the previous headlines and
  the latest prices go in the user turn.
- `pause_turn` is resumed (append-only history, identical tools) while the search budget lasts.
- `stop_reason == "refusal"` fails the run; server-side fallbacks ("default") are opted in.
- Output is validated against updater/schema/*.json (livedata.validate_doc); files are written atomically and
  only when everything is valid; on any failure the old headlines stay and status.json gets ok=false with a
  Thai message.
- Token usage, web-search count and an estimated USD cost are printed, appended to
  updater/cost-log.csv and written to $GITHUB_STEP_SUMMARY when set.
- The API key is read only from $ANTHROPIC_API_KEY and is never printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import re
import sys
import time
from dataclasses import dataclass, field
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from livedata import (  # noqa: E402,F401 - re-exported: tests and backfill_gold_history.py use update.<name>
    BUY_SPREAD_MAX, COST_LOG, CSV_FIELDS, DATA_DIR, DOCS, GOLD_TH_EXTRA, HISTORY, HISTORY_CAP, HISTORY_FULL_DAYS, ISO_RE,
    MARKET_KEYS, MAX_MOVE, NUM_RE, ORNAMENT_PREMIUM_MAX, ROOT, SCHEMA_DIR, STALE_PREFIX, TH_MONTHS, UpdateError,
    _bkk_day, _migrate_csv, _short, _stale, _ts, allowed_conflict_ids, append_cost_row, append_history, bkk_th,
    clean_th, compact_history, count_changed, dump_json, failure_status, history_docs, history_point, iso, load_docs,
    load_history, load_json, normalize_value, parse_number, sanity_market, scrub_gold_th, utcnow, validate_doc,
    write_docs,
)

MODEL = "claude-sonnet-5-5"          # user's choice (cost); fallbacks="default" may serve a declined turn on claude-sonnet-5
EFFORT = "medium"                    # skill: medium for multistep tool use on Sonnet 5.5
MAX_TOKENS = 64000                   # streaming request, thinking counts toward it
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_SEARCHES = {"full": 14}          # news only (the 6 price searches of the old plan are gone)
# web fetch has no per-use fee (tokens only); max_content_tokens caps each page that enters the context
MAX_FETCHES = {"full": 4}
FETCH_MAX_CONTENT_TOKENS = 8000
HEADLINES_MIN, HEADLINES_MAX = 12, 16
MIN_NEWS_SEARCHES = 4                # a full run must search the news at least this often before submitting
NEWS_TOPICS = ("Iran / Hormuz", "US markets, the Fed and US data", "the US midterm elections", "Ukraine-Russia", "China",
               "Thai politics and economy, the baht and Thai gold", "Yemen / Saudi Arabia")
MAX_REQUESTS = 5                     # first call + pause_turn continuations + one nudge + one schema fix
DEADLINE_S = 11 * 60                 # the workflow job times out at 15 min

# USD per million tokens (Claude Sonnet 5.5, Claude API first-party) and per web search.
# Cache read is $0.20/MTok per the claude-api skill pricing table (2026-10-06); edit here if it changes.
PRICE = {"input": 2.00, "output": 10.00, "cache_write_5m": 2.50, "cache_read": 0.10}
WEB_SEARCH_USD = 10.0 / 1000

TAGS_EXTRA = {"thailand": "Thailand domestic news that is not the Thai-Cambodian border",
              "economy": "markets / economy / central banks",
              "disaster": "a major natural disaster (strong earthquake, typhoon or cyclone making landfall, major flood, "
                          "eruption, wildfire), especially in Thailand and Southeast Asia",
              "world": "other world news"}


def _check_mode(mode: str) -> None:
    if mode != "full":
        raise ValueError(f"update.py only runs mode 'full' with Claude (got {mode!r}); prices come from prices.py")


# ----------------------------------------------------------------- headlines
def _match_kept(cands: list[dict], row: dict) -> dict | None:
    """The previous item a submitted headline repeats: the only one with that URL, or (live blogs share a URL)
    the one with the same title or the same time."""
    if len(cands) == 1:
        return cands[0]
    for c in cands:
        if _norm_title(c.get("title_th")) == _norm_title(row["title_th"]) or c.get("time") == row["time"]:
            return c
    return None


def build_headlines(items: list[dict], now: dt.datetime, prev: dict | None = None) -> dict:
    allowed = set(allowed_conflict_ids())
    by_source: dict[str, list[dict]] = {}
    for i in (prev or {}).get("items", []):
        by_source.setdefault(i.get("source"), []).append(i)
    rows, seen = [], set()
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
        old = _match_kept(by_source.get(src) or [], row)
        if old:   # a kept headline is copied verbatim (no retyped titles, no refreshed times)
            row = {k: old[k] for k in ("conflict_id", "title_th", "time", "source", "source_name")}
        key = (row["source"], _norm_title(row["title_th"]))
        if row["title_th"] and re.match(r"^https?://\S+$", src) and '"' not in src and row["source_name"] and key not in seen:
            seen.add(key)
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
    """Stable across runs (cached). Never put the date or the previous data here."""
    ids = "\n".join(f"- {c}" for c in allowed_conflict_ids())
    extra = "\n".join(f"- {k}: {v}" for k, v in TAGS_EXTRA.items())
    return f"""You maintain the live news files of a public Thai-language website: a 3D globe of world conflicts, economies and markets, with a gold-price panel. Readers are in Thailand. You run unattended on a schedule; nobody reads your text replies, only the data you submit through the submit tool.

## Job
Research and write 12 to 16 fresh headlines and a one-paragraph run summary, then call submit_full exactly once with the complete result. The user turn gives the current UTC and Bangkok time, the tool budgets, the previous headlines file and the latest market prices.
Market prices are not your job: a separate script refreshes the 13 market quotes every hour from direct data feeds. Do not search or fetch prices; use the latest prices in the user turn only for the run summary.

## Submitting
The submit tool's input must follow its schema exactly: "headlines" is a list of objects and "status_message_th" is a string. Pass objects as objects, not as JSON strings.

## Headlines
- Research the news with web_search before submitting (at least 4 searches, grouped by theme), covering the time since the newest previous headline given in the user turn. Themes: Iran / Hormuz; US markets, the Fed and US data; the US midterm elections; Ukraine-Russia; China; Thai politics and economy, the baht and Thai gold; Yemen / Saudi Arabia; plus any other conflict on the globe that made news, and any major natural disaster (big earthquakes, typhoons hitting land, major floods, especially in Thailand and Southeast Asia).
- 12 to 16 items, newest first, about the conflicts on the globe, the world economy and Thailand. Keep at most about 5 older items that are still among the most important; every other item must be newer than the newest previous headline whenever such news exists.
- Sources: prefer primary, major outlets: Reuters, AP, AFP, Bloomberg, BBC, Al Jazeera, CNBC, ไทยรัฐ, มติชน, Bangkok Post, ประชาชาติธุรกิจ, กรุงเทพธุรกิจ, Kyiv Independent. Avoid syndication and aggregator sites (local TV sites re-running wire copy, regional papers re-running IANS, aggregators) when the original is available. One source URL per headline: the article itself, https.
- title_th: a Thai headline of at most about 120 characters, factual, no clickbait, written by you (do not copy foreign headlines word for word).
- time: the publication time of the source article (or the time of the event it reports, if earlier and stated), ISO 8601 UTC, never later than the current time. source_name: the outlet name.
- conflict_id must be one of these ids (the globe links a headline to its conflict pin):
{ids}
  Extra tags:
{extra}
  Tag natural-disaster news as disaster even when it hits Thailand.
- A kept previous headline keeps its original time; do not refresh its time. Drop an older market headline whose numbers are superseded by the latest prices (for example an oil or gold level that has since moved) and drop items from syndication sites when you have a primary source.
- Keep the context small: when you search or fetch from code, print only the lines you need, never whole pages or raw result objects.

## Run summary
status_message_th: one Thai paragraph (at most about 400 characters) saying what changed in this round: the biggest market moves (from the latest prices in the user turn) and the main news themes.

## Text rules
- All *_th fields are Thai. Keep tickers, index names and outlet names in their usual Latin spelling.
- Never use the ASCII double-quote character in any text field; use Thai wording or “ ” if a quotation is unavoidable.
- Report facts from your searches only; never invent a number, a time or a URL.
- This is an information page, not investment advice; do not add recommendations."""


def submit_tool(mode: str = "full") -> dict:
    # strict is off (the API rejected the compiled grammar of the larger schema); every submitted input is
    # validated with jsonschema here and in write_docs, so a malformed submission never reaches the site.
    _check_mode(mode)
    return {
        "name": "submit_full",
        "description": "Submit 12-16 headlines and the run summary. Call exactly once, at the end, after searching the news.",
        "strict": False,
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["headlines", "status_message_th"],
            "properties": {
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


def tools_for(mode: str = "full") -> list[dict]:
    _check_mode(mode)
    return [
        {
            "type": "web_search_20260209",   # dynamic filtering; no separate code_execution tool
            "name": "web_search",
            "max_uses": MAX_SEARCHES[mode],
            "user_location": {"type": "approximate", "timezone": "Asia/Bangkok"},  # web search rejects country TH
        },
        {
            # web_fetch_20260309 = dynamic filtering (as 20260209) + use_cache; no per-use fee, only tokens,
            # capped by max_uses x max_content_tokens (for opening an article a search result points to)
            "type": "web_fetch_20260309",
            "name": "web_fetch",
            "max_uses": MAX_FETCHES[mode],
            "max_content_tokens": FETCH_MAX_CONTENT_TOKENS,
            "use_cache": False,
        },
        submit_tool(mode),
    ]


def user_message(mode: str, prev: dict, now: dt.datetime) -> str:
    _check_mode(mode)
    age = prices_age_min(prev["market"], now)
    parts = [
        f"Mode: {mode} (news and run summary; prices come from the hourly feed script)",
        f"Current time: {iso(now)} (Bangkok {bkk_th(now)})",
        f"Budgets for this run: web_search at most {MAX_SEARCHES[mode]} searches; web_fetch at most {MAX_FETCHES[mode]} pages.",
        f"Previous headlines.json (newest item {headlines_since(prev['headlines'])}; search the news published since then):",
        "```json\n" + json.dumps(prev["headlines"], ensure_ascii=False, indent=1) + "\n```",
        f"Latest prices (market.json, updated {age:.0f} minutes ago), for the run summary only - do not search prices:"
        if age is not None else "Latest prices (market.json), for the run summary only - do not search prices:",
        "```json\n" + json.dumps({i["key"]: [i["value"], i["change_th"]] for i in prev["market"]["items"]}, ensure_ascii=False) + "\n```",
        f"Search the news (at least {MIN_NEWS_SEARCHES} searches, grouped by theme), then call submit_full once with 12-16 headlines and status_message_th.",
    ]
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
    append_cost_row(row, cost_log)
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


def normalize_submission(mode: str, data: Any) -> Any:
    """Repair the shapes a non-strict tool call is known to produce before validating it: the whole input or
    the headlines list sent as a JSON string. A stray "market" field (prices are not researched here) is dropped."""
    _check_mode(mode)
    data = _maybe_json(data)
    if not isinstance(data, dict):
        return data
    data = {k: v for k, v in data.items() if k != "market"}
    if "headlines" in data:
        data["headlines"] = _maybe_json(data.get("headlines"))
    return data


def submission_errors(mode: str, data: Any) -> list[str]:
    import jsonschema

    v = jsonschema.Draft202012Validator(submit_tool(mode)["input_schema"])
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {_short(e.message, 160)}" for e in v.iter_errors(data)]


def call_model(client: Any, mode: str, prev: dict, now: dt.datetime, usage: Usage) -> tuple[dict, bool]:
    """Run the search + submit loop. Returns (the submit tool's input, whether the run searched the news)."""
    import anthropic

    _check_mode(mode)
    submit_name = "submit_full"
    tools = tools_for(mode)                     # identical on every request of the run
    system = [{"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}}]
    messages: list[dict] = [{"role": "user", "content": [
        {"type": "text", "text": user_message(mode, prev, now), "cache_control": {"type": "ephemeral"}}]}]
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
            print("trace: submitted shape " + shape_of(data))
            errs = submission_errors(mode, data)
            if not errs and usage.web_searches < MIN_NEWS_SEARCHES:
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
                return data, True
            # the submit tool is not strict, so a malformed call gets one is_error tool_result asking for a
            # corrected call; the history stays append-only
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
        messages.append({"role": "user", "content": f"Do not search any more. Call {submit_name} now with your best headlines and summary."})
    raise UpdateError("too many requests without a result", "เรียก API หลายรอบแต่ยังไม่ได้ผลลัพธ์")


# ----------------------------------------------------------------- files
def load_previous(data_dir: pathlib.Path) -> tuple[dict, list[str]]:
    return load_docs(data_dir, DOCS)


def build_docs(mode: str, prev: dict, result: dict, now: dt.datetime, news_searched: bool = True) -> tuple[dict[str, dict], list[str]]:
    """headlines.json (when there is news) + status.json of a full run. market.json is left to prices.py."""
    _check_mode(mode)
    docs: dict[str, dict] = {}
    notes: list[str] = []
    age = prices_age_min(prev["market"], now)
    tail = (f"ราคาจากรอบดึงตรงทุกชั่วโมง (ล่าสุด {bkk_th(dt.datetime.fromisoformat(prev['market']['updated_at'].replace('Z', '+00:00')))})"
            if age is not None else "ราคาจากรอบดึงตรงทุกชั่วโมง")
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
    message = clean_th(f"{summary} · {news} · {tail}" if summary else f"อัปเดตข่าวอัตโนมัติ {bkk_th(now)} · {news} · {tail}", 600)
    docs["status"] = {"updated_at": iso(now), "run_count": int(prev["status"].get("run_count", 0)) + 1, "ok": True, "message_th": message}
    return docs, notes


def run(mode: str, data_dir: pathlib.Path = DATA_DIR, client: Any = None, cost_log: pathlib.Path | None = None,
        now: dt.datetime | None = None) -> int:
    _check_mode(mode)
    now = now or utcnow()
    cost_log = cost_log or COST_LOG
    prev, errs = load_previous(data_dir)
    if errs:
        print("previous data files are invalid; refusing to run:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 2
    usage = Usage()
    try:
        result, news_searched = call_model(client, mode, prev, now, usage)
        docs, notes = build_docs(mode, prev, result, now, news_searched)
        notes += write_docs(data_dir, docs)
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
    log_cost(mode, True, usage, "; ".join(notes), now, cost_log)
    return 0


def dry_run(data_dir: pathlib.Path = DATA_DIR) -> int:
    prev, errs = load_previous(data_dir)
    if not errs:
        # the request we would send must build too, and the price feed table must cover every key
        system_prompt(), tools_for("full"), user_message("full", prev, utcnow())
        bad = [c for c in (i["conflict_id"] for i in prev["headlines"]["items"]) if c not in allowed_conflict_ids()]
        errs += [f"headlines: conflict_id {c!r} not allowed" for c in bad]
        import prices

        table = prices.sources()
        errs += [f"prices: no feed for {k}" for k in MARKET_KEYS if not table.get(k)]
    if errs:
        print("dry run: INVALID\n  " + "\n  ".join(errs))
        return 1
    m, h, s = prev["market"], prev["headlines"], prev["status"]
    print(f"dry run: OK - market {len(m['items'])} items (updated {m['updated_at']}), "
          f"headlines {len(h['items'])} (updated {h['updated_at']}), status run {s['run_count']} ok={s['ok']}")
    print(f"dry run: model {MODEL}, effort {EFFORT}, search caps {MAX_SEARCHES}, fetch caps {MAX_FETCHES}, no API call made")
    print(disasters_check_line(data_dir))
    print(history_check_line(data_dir))
    return 0


def history_check_line(data_dir: pathlib.Path) -> str:
    """gold_history.json is checked but never fails the dry run (the chart falls back to the embedded series)."""
    doc, problem = load_history(data_dir)
    if problem:
        return f"dry run: {HISTORY}.json INVALID (not fatal; the next run leaves it unchanged)\n  {problem}"
    if doc is None:
        return f"dry run: {HISTORY}.json not present (the next run that writes market.json starts it)"
    pts = doc["points"]
    span = f", {pts[0]['spot_as_of']} .. {pts[-1]['spot_as_of']}" if pts else ""
    return f"dry run: {HISTORY}.json OK - {len(pts)} points{span}"


def disasters_check_line(data_dir: pathlib.Path) -> str:
    """disasters.json comes from updater/disasters.py (GDACS + USGS, no AI). It is reported here but never
    fails this check, so a problem with that feed cannot block the Claude update in the workflow."""
    path = data_dir / "disasters.json"
    if not path.exists():
        return "dry run: disasters.json not present (written by updater/disasters.py)"
    try:
        errs = validate_doc("disasters", load_json(path))
    except (OSError, ValueError) as e:
        errs = [f"disasters: cannot read {path.name}: {e}"]
    if errs:
        return "dry run: disasters.json INVALID (separate feed, not fatal here; run updater/disasters.py --check)\n  " + "\n  ".join(errs[:5])
    d = load_json(path)
    return f"dry run: disasters.json OK - {len(d['items'])} events (updated {d['updated']}, feeds ok={d['ok']})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("mode", nargs="?", choices=["prices", "full"],
                    help="full: headlines + status with Claude; prices: the free feed script updater/prices.py (no AI, no key)")
    ap.add_argument("--dry-run", action="store_true", help="skip the API call; validate the current data files")
    ap.add_argument("--data-dir", type=pathlib.Path, default=DATA_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if args.dry_run:
        return dry_run(args.data_dir)
    if not args.mode:
        ap.error("mode is required (prices or full) unless --dry-run")
    if args.mode == "prices":
        import prices

        return prices.main(["--data-dir", str(args.data_dir)])
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        print("ANTHROPIC_API_KEY is not set. Add it as a repository secret (Settings > Secrets and variables > "
              "Actions > New repository secret) or export it locally. Nothing was changed.", file=sys.stderr)
        return 2
    return run(args.mode, args.data_dir, client=make_client(key))


if __name__ == "__main__":
    sys.exit(main())
