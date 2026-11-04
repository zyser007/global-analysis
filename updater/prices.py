#!/usr/bin/env python3
"""Refresh site/data/market.json from free public quote feeds (no AI, no API key).

    python -I updater/prices.py                                # fetch the 13 quotes, write market.json + status.json
    python -I updater/prices.py --data-dir DIR --cost-log FILE # same, into another copy of site/data

Python standard library for fetching (urllib); jsonschema (already in requirements.txt) to validate.

Sources (SOURCES below; tried in order, the next one only when a feed fails or has nothing newer than the
previous file's as_of). One request per symbol per run, a named User-Agent, short timeouts, no retries.

| key     | primary                                          | fallback(s)                                      |
|---------|--------------------------------------------------|--------------------------------------------------|
| brent   | CNBC quote API @LCO.1 (ICE Brent front month)    | Yahoo Finance chart BZ=F                         |
| wti     | CNBC @CL.1 (NYMEX WTI front month)               | Yahoo CL=F                                       |
| gold    | Swissquote public bid/ask XAU/USD (mid), with    | CNBC XAU=                                        |
|         | CNBC XAU='s previous close as the reference      |                                                  |
| gold_th | Gold Traders Association API (goldtraders.or.th, | GTA classic announcement table                   |
|         | the association's own price board)               | (classic.goldtraders.or.th/UpdatePriceList.aspx) |
| dxy     | CNBC .DXY (ICE US Dollar Index)                  | Yahoo DX-Y.NYB                                   |
| spx     | Cboe delayed quotes _SPX                         | Yahoo ^GSPC, CNBC .SPX                           |
| ndx     | Cboe delayed quotes _NDX                         | Yahoo ^NDX, CNBC .NDX                            |
| btc     | CoinGecko simple price                           | Coinbase Exchange ticker + 24 h stats            |
| usdthb  | CNBC THB=                                        | Yahoo THB=X                                      |
| us10y   | CNBC US10Y (Tradeweb, intraday)                  | Yahoo ^TNX, US Treasury daily par yield CSV      |
| vix     | Cboe delayed quotes _VIX (Cboe computes VIX)     | Yahoo ^VIX, CNBC .VIX                            |
| set     | CNBC .SETI                                       | Yahoo ^SET.BK                                    |
| nikkei  | Nikkei Indexes real-time data (official)         | Yahoo ^N225, CNBC .N225                          |

Not used: Stooq (now behind a JavaScript bot check), set.or.th / settrade.com (Incapsula bot protection),
Bank of Thailand API (needs a registered key).

Rules (shared with update.py through livedata.py)
- as_of is the quote's own timestamp (UTC); source is the human page of that quote.
- change_th is generated from the numbers (vs the previous close, 24 h for Bitcoin, the previous announcement for
  Thai gold) with market-closed wording from the exchange hours (weekday sessions; local holidays show as
  "no new trades" when an open session has no quote for 3 hours).
- A move > 15 % vs the previous value is rejected, an older as_of never replaces a newer one, label/unit come from
  the previous file, and gold_th buy / ornament_sell must be plausible (sanity_market, scrub_gold_th).
- A key whose feeds all fail keeps its previous item, flagged in change_th and note_th. More than MAX_FAILED
  failed keys = a failed run: market.json stays, status.json gets ok=false, exit code 1.
- Files are validated against updater/schema/*.json and written atomically; gold_history.json gets a point;
  updater/cost-log.csv gets a row with cost 0 and the changed count.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import math
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import livedata as ld  # noqa: E402

UTC = dt.timezone.utc
NY, BKK, TOKYO = ZoneInfo("America/New_York"), ZoneInfo("Asia/Bangkok"), ZoneInfo("Asia/Tokyo")
USER_AGENT = "world-globe-live/1.0 (+https://github.com/zyser007/global-analysis; prices.py)"
TIMEOUT_S = 15
MAX_BYTES = 2 * 1024 * 1024
DEADLINE_S = 150                     # the whole fetch loop; the workflow step times out at 5 min
MAX_FAILED = 6                       # more failed keys than this = a failed run (old market.json kept)
MAX_QUOTE_AGE_DAYS = 10              # a feed whose newest quote is older than this is treated as broken
FUTURE_SLACK_S = 600                 # clock skew allowed before a quote time counts as "in the future"
IDLE_AFTER_H = 3                     # an "open" session without a quote for this long = no trading (holiday)
MODEL_TAG = "free-feeds"             # cost-log "model" column for these runs

# value decimals in market.json (plain number strings)
DECIMALS = {"brent": 2, "wti": 2, "gold": 2, "gold_th": 0, "dxy": 3, "spx": 2, "ndx": 2, "btc": 0,
            "usdthb": 3, "us10y": 3, "vix": 2, "set": 2, "nikkei": 2}
SHORT_TH = {"brent": "Brent", "wti": "WTI", "gold": "ทองคำ spot", "gold_th": "ทองคำแท่งไทย", "dxy": "DXY",
            "spx": "S&P 500", "ndx": "Nasdaq 100", "btc": "Bitcoin", "usdthb": "ดอลลาร์/บาท", "us10y": "ยีลด์ 10 ปี",
            "vix": "VIX", "set": "SET", "nikkei": "Nikkei 225"}
# trading-hours group of each key (weekday local sessions in minutes; see session_state)
GROUP = {"brent": "globex", "wti": "globex", "gold": "globex", "dxy": "globex", "usdthb": "globex", "us10y": "globex",
         "spx": "us", "ndx": "us", "vix": "vix", "btc": "always", "set": "set", "nikkei": "tokyo", "gold_th": "gta"}
GROUP_TZ = {"globex": NY, "us": NY, "vix": NY, "tnx": NY, "always": UTC, "set": BKK, "tokyo": TOKYO, "gta": BKK}
SESSIONS = {"us": [(570, 960)], "vix": [(570, 975)], "tnx": [(480, 900)], "set": [(600, 750), (870, 990)], "tokyo": [(540, 690), (750, 930)]}
CLOSE_AT = {"globex": (17, 0), "us": (16, 0), "tnx": (15, 0), "vix": (16, 15), "set": (16, 30), "tokyo": (15, 30), "always": (0, 0), "gta": (17, 30)}
FAIL_PREFIX = "ค่าเดิม (ดึงราคาไม่สำเร็จรอบนี้)"
MINUS = "−"


class FeedError(Exception):
    """A feed could not be read or parsed."""


# ----------------------------------------------------------------- quotes and sources
@dataclass
class Quote:
    value: float
    as_of: dt.datetime                    # aware; the quote's own time
    page: str                             # human page of this quote (market.json "source")
    prev: float | None = None             # reference: previous close / 24 h open / previous announcement
    basis: str = "prev_close"             # prev_close | 24h | prev_update | announcement
    daily: bool = False                   # end-of-day series (Treasury): always "close" wording
    extra: dict = field(default_factory=dict)
    group: str | None = None              # trading-hours group when it differs from the key's (Yahoo ^TNX)


Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class Source:
    name: str
    urls: tuple[str, ...]
    page: str
    parse: Callable[..., Quote]           # parse(*raw_bodies, now=..., page=...) -> Quote
    group: str | None = None              # trading hours of this feed when they differ from the key's

    def get(self, fetch: Fetch, now: dt.datetime) -> Quote:
        bodies = [fetch(u) for u in self.urls]
        q = self.parse(*bodies, now=now, page=self.page)
        q.group = self.group or q.group
        return q


class HttpFetcher:
    """GET with a named User-Agent and a timeout; counts requests; caches by URL for the run."""

    def __init__(self, timeout: float = TIMEOUT_S):
        self.timeout = timeout
        self.requests = 0
        self._cache: dict[str, bytes] = {}

    def __call__(self, url: str) -> bytes:
        if url in self._cache:
            return self._cache[url]
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json, text/csv, text/html;q=0.8, */*;q=0.5"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:  # noqa: S310 - fixed https URLs in SOURCES
                body = r.read(MAX_BYTES + 1)
                status = r.status
        except urllib.error.HTTPError as e:
            raise FeedError(f"HTTP {e.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise FeedError(f"{type(e).__name__}: {getattr(e, 'reason', e)}") from None
        if status != 200:
            raise FeedError(f"HTTP {status}")
        if len(body) > MAX_BYTES:
            raise FeedError("response too large")
        self._cache[url] = body
        return body


# ----------------------------------------------------------------- parsing helpers
TS_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?\s*(Z|[+-]\d{2}:?\d{2})?$")


def parse_ts(s: Any, default_tz: dt.tzinfo) -> dt.datetime:
    """'2026-11-04T01:04:30.000-0500' / '...Z' / '2026-11-04T06:03:24.825283226Z' / naive (in default_tz) -> aware UTC."""
    m = TS_RE.match(str(s or "").strip())
    if not m:
        raise FeedError(f"unreadable time {str(s)[:40]!r}")
    y, mo, d, h, mi, sec, frac, tz = m.groups()
    t = dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(sec or 0), int((frac or "0")[:6].ljust(6, "0")))
    if tz is None:
        t = t.replace(tzinfo=default_tz)
    elif tz == "Z":
        t = t.replace(tzinfo=UTC)
    else:
        sign = 1 if tz[0] == "+" else -1
        t = t.replace(tzinfo=dt.timezone(sign * dt.timedelta(hours=int(tz[1:3]), minutes=int(tz[-2:]))))
    return t.astimezone(UTC).replace(microsecond=0)


def from_epoch(v: Any) -> dt.datetime:
    n = ld.parse_number(v)
    if n is None or n <= 0:
        raise FeedError(f"unreadable epoch {v!r}")
    if n > 1e11:                      # milliseconds
        n /= 1000
    return dt.datetime.fromtimestamp(int(n), UTC)


def num(v: Any, what: str) -> float:
    n = ld.parse_number(str(v).replace("%", "").strip() if isinstance(v, str) else v)
    if n is None:
        raise FeedError(f"{what} is not a number ({str(v)[:30]!r})")
    return n


def _json(raw: bytes) -> Any:
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise FeedError("not JSON") from None


def session_close(group: str, day: dt.date) -> dt.datetime:
    h, m = CLOSE_AT[group]
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=GROUP_TZ[group]).astimezone(UTC)


# ----------------------------------------------------------------- parsers (one per feed; raw bytes in, Quote out)
def parse_cnbc(raw: bytes, now: dt.datetime, page: str, group: str = "globex") -> Quote:
    """quote.cnbc.com restQuote JSON: last, last_time (with offset, or a date for a closed index), previous_day_closing."""
    q = (((_json(raw) or {}).get("FormattedQuoteResult") or {}).get("FormattedQuote") or [None])[0]
    if not isinstance(q, dict) or str(q.get("code", "0")) != "0" or q.get("last") in (None, "", "UNCH"):
        raise FeedError("no quote in the CNBC response")
    value = num(q["last"], "last")
    lt = str(q.get("last_time") or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", lt):
        as_of = session_close(group, dt.date.fromisoformat(lt))
    else:
        as_of = parse_ts(lt, NY)
    prev = ld.parse_number(str(q.get("previous_day_closing") or "").replace("%", ""))
    if prev is None and q.get("change") not in (None, ""):
        prev = value - num(q["change"], "change")
    return Quote(value, as_of, page, prev)


def parse_yahoo(raw: bytes, now: dt.datetime, page: str) -> Quote:
    """query1.finance.yahoo.com/v8/finance/chart: meta.regularMarketPrice / regularMarketTime / chartPreviousClose."""
    res = ((_json(raw) or {}).get("chart") or {}).get("result")
    if not res:
        raise FeedError("no chart result")
    m = res[0].get("meta") or {}
    value = num(m.get("regularMarketPrice"), "regularMarketPrice")
    prev = ld.parse_number(m.get("chartPreviousClose")) or ld.parse_number(m.get("previousClose"))
    return Quote(value, from_epoch(m.get("regularMarketTime")), page, prev)


def parse_cboe(raw: bytes, now: dt.datetime, page: str) -> Quote:
    """cdn.cboe.com delayed_quotes: data.current_price, price_change, last_trade_time (New York time unless offset)."""
    d = (_json(raw) or {}).get("data") or {}
    value = num(d.get("current_price"), "current_price")
    if value <= 0:
        raise FeedError("current_price is 0")
    chg = ld.parse_number(d.get("price_change"))
    return Quote(value, parse_ts(d.get("last_trade_time"), NY), page, None if chg is None else value - chg)


def parse_nikkei(raw: bytes, now: dt.datetime, page: str) -> Quote:
    """indexes.nikkei.co.jp get_real_data: price '61,915.82', diff '-1,166.04', datedtime 'Nov/04/2026(15:03)' (Tokyo)
    during the session and 'Nov/04/2026(Close)' after it (= 15:30 Tokyo)."""
    d = _json(raw) or {}
    value = num(d.get("price"), "price")
    m = re.fullmatch(r"(\w{3}/\d{2}/\d{4})\((\d{1,2}:\d{2}|Close)\)", str(d.get("datedtime") or "").strip())
    try:
        if not m:
            raise ValueError
        hm = "%02d:%02d" % CLOSE_AT["tokyo"] if m.group(2) == "Close" else m.group(2)
        t = dt.datetime.strptime(f"{m.group(1)} {hm}", "%b/%d/%Y %H:%M").replace(tzinfo=TOKYO)
    except ValueError:
        raise FeedError(f"unreadable datedtime {d.get('datedtime')!r}") from None
    diff = ld.parse_number(d.get("diff"))
    return Quote(value, t.astimezone(UTC), page, None if diff is None else value - diff)


def parse_coingecko(raw: bytes, now: dt.datetime, page: str) -> Quote:
    b = (_json(raw) or {}).get("bitcoin") or {}
    value = num(b.get("usd"), "usd")
    pct = ld.parse_number(b.get("usd_24h_change"))
    return Quote(value, from_epoch(b.get("last_updated_at")), page, None if pct is None else value / (1 + pct / 100), basis="24h")


def parse_coinbase(ticker: bytes, stats: bytes, now: dt.datetime, page: str) -> Quote:
    t, s = _json(ticker) or {}, _json(stats) or {}
    value = num(t.get("price"), "price")
    return Quote(value, parse_ts(t.get("time"), UTC), page, ld.parse_number(s.get("open")), basis="24h")


def parse_swissquote(raw: bytes, now: dt.datetime, page: str) -> Quote:
    """forex-data-feed.swissquote.com public bboquotes: mid of the first platform's first spread profile; ts in ms.
    No previous close in this feed: the change is against the previous update unless SpotGold adds a reference."""
    rows = _json(raw)
    if not isinstance(rows, list) or not rows:
        raise FeedError("no Swissquote quotes")
    r = rows[0]
    p = (r.get("spreadProfilePrices") or [None])[0] or {}
    bid, ask = num(p.get("bid"), "bid"), num(p.get("ask"), "ask")
    if not 0 < bid <= ask:
        raise FeedError("bid/ask out of order")
    return Quote(round((bid + ask) / 2, 3), from_epoch(r.get("ts")), page, None, basis="prev_update")


def parse_treasury(raw: bytes, now: dt.datetime, page: str) -> Quote:
    """home.treasury.gov daily par yield curve CSV (newest row first): the "10 Yr" column; closes at ~15:30 New York."""
    rows = [r for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig", "replace"))) if (r.get("10 Yr") or "").strip()]
    if not rows:
        raise FeedError("no 10 Yr rows")

    def day(r: dict) -> dt.date:
        try:
            return dt.datetime.strptime(r["Date"].strip(), "%m/%d/%Y").date()
        except (KeyError, ValueError):
            raise FeedError(f"unreadable Date {r.get('Date')!r}") from None
    rows.sort(key=day, reverse=True)
    d0 = day(rows[0])
    as_of = dt.datetime(d0.year, d0.month, d0.day, 15, 30, tzinfo=NY).astimezone(UTC)
    prev = ld.parse_number(rows[1]["10 Yr"]) if len(rows) > 1 else None
    return Quote(num(rows[0]["10 Yr"], "10 Yr"), as_of, page, prev, daily=True)


def _gta_quote(as_of: dt.datetime, seq: Any, sell: Any, buy: Any, orn: Any, row_chg: Any, day_chg: Any, page: str) -> Quote:
    s = num(sell, "bar sell")
    extra = {"seq": int(num(seq, "announcement number"))}
    for k, v in (("buy", buy), ("ornament_sell", orn)):
        n = ld.parse_number(v)
        if n is not None and n > 0:
            extra[k] = int(n) if n == int(n) else n
    rc, dc = ld.parse_number(row_chg), ld.parse_number(day_chg)
    if dc is not None:
        extra["day_change"] = dc
    return Quote(s, as_of, page, None if rc is None else s - rc, basis="announcement", extra=extra)


def parse_gta_latest(raw: bytes, now: dt.datetime, page: str) -> Quote:
    """goldtraders.or.th /api/GoldPrices/Latest (the association's own board): asTime is Bangkok time."""
    d = _json(raw)
    if not isinstance(d, dict):
        raise FeedError("no GTA price object")
    return _gta_quote(parse_ts(d.get("asTime"), BKK), d.get("seq"), d.get("bL_SellPrice"), d.get("bL_BuyPrice"),
                      d.get("oM965_SellPrice"), d.get("priceChangeFromPrevRow"), d.get("priceChangeFromPrevDayLast"), page)


GTA_ROW_RE = re.compile(r"<tr[^>]*>\s*((?:<td[^>]*>.*?</td>\s*){9})</tr>", re.S | re.I)
GTA_CELL_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S | re.I)


def parse_gta_classic(raw: bytes, now: dt.datetime, page: str) -> Quote:
    """classic.goldtraders.or.th/UpdatePriceList.aspx: today's announcements, newest first.
    Columns: time 'dd/mm/2569 HH:MM' (Buddhist year, Bangkok), number, bar buy, bar sell, ornament buy (tax base),
    ornament sell, gold spot, baht/US$, change vs the previous announcement."""
    html = raw.decode("utf-8", "replace")
    for m in GTA_ROW_RE.finditer(html):
        cells = [re.sub(r"<[^>]+>|&nbsp;|\s+", " ", c).strip().translate(ld.THAI_DIGITS) for c in GTA_CELL_RE.findall(m.group(1))]
        tm = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2})", cells[0])
        if not tm:
            continue
        d, mo, y, h, mi = (int(x) for x in tm.groups())
        as_of = dt.datetime(y - 543 if y > 2400 else y, mo, d, h, mi, tzinfo=BKK).astimezone(UTC)
        return _gta_quote(as_of, cells[1], cells[3], cells[2], cells[5], cells[8], None, page)
    raise FeedError("no announcement row in the GTA table")


class SpotGold(Source):
    """Swissquote's live XAU/USD (ms timestamps; CNBC's XAU= can sit unchanged for half an hour) with the previous
    close from CNBC XAU= as the reference. Without the reference the change is against the previous update."""

    def get(self, fetch: Fetch, now: dt.datetime) -> Quote:
        q = parse_swissquote(fetch(self.urls[0]), now, self.page)
        try:
            ref = parse_cnbc(fetch(self.urls[1]), now, self.page).prev
        except FeedError:
            ref = None
        if ref:
            q.prev, q.basis = ref, "prev_close"
        return q


# ----------------------------------------------------------------- the source table
CNBC_API = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols={}"
            "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json&events=1")


def cnbc(sym: str, group: str = "globex") -> Source:
    return Source("CNBC", (CNBC_API.format(urllib.parse.quote(sym, safe="")),), f"https://www.cnbc.com/quotes/{sym}",
                  lambda raw, now, page: parse_cnbc(raw, now, page, group))


def yahoo(sym: str, group: str | None = None) -> Source:
    return Source("Yahoo Finance", (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym, safe='')}?range=1d&interval=1h",),
                  f"https://finance.yahoo.com/quote/{sym}/", parse_yahoo, group)


def cboe(sym: str) -> Source:
    return Source("Cboe", (f"https://cdn.cboe.com/api/global/delayed_quotes/quotes/_{sym}.json",),
                  f"https://www.cboe.com/us/indices/dashboard/{sym.lower()}/", parse_cboe)


def treasury(now: dt.datetime | None = None) -> Source:
    y = (now or ld.utcnow()).astimezone(NY).year
    return Source("US Treasury", (f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/{y}/all"
                                  f"?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv",),
                  f"https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve&field_tdr_date_value={y}",
                  parse_treasury)


def sources(now: dt.datetime | None = None) -> dict[str, list[Source]]:
    return {
        "brent": [cnbc("@LCO.1"), yahoo("BZ=F")],
        "wti": [cnbc("@CL.1"), yahoo("CL=F")],
        "gold": [SpotGold("Swissquote", ("https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD",
                                         CNBC_API.format("XAU%3D")), "https://www.swissquote.com/", parse_swissquote),
                 cnbc("XAU=")],           # same URL as SpotGold's reference: served from the run's cache
        "gold_th": [Source("สมาคมค้าทองคำ", ("https://www.goldtraders.or.th/api/GoldPrices/Latest?readjson=false",),
                           "https://www.goldtraders.or.th/", parse_gta_latest),
                    Source("สมาคมค้าทองคำ (classic)", ("https://classic.goldtraders.or.th/UpdatePriceList.aspx",),
                           "https://classic.goldtraders.or.th/UpdatePriceList.aspx", parse_gta_classic)],
        "dxy": [cnbc(".DXY"), yahoo("DX-Y.NYB")],
        "spx": [cboe("SPX"), yahoo("^GSPC"), cnbc(".SPX", "us")],
        "ndx": [cboe("NDX"), yahoo("^NDX"), cnbc(".NDX", "us")],
        "btc": [Source("CoinGecko", ("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
                                     "&include_24hr_change=true&include_last_updated_at=true",),
                       "https://www.coingecko.com/en/coins/bitcoin", parse_coingecko),
                Source("Coinbase", ("https://api.exchange.coinbase.com/products/BTC-USD/ticker",
                                    "https://api.exchange.coinbase.com/products/BTC-USD/stats"),
                       "https://exchange.coinbase.com/trade/BTC-USD", parse_coinbase)],
        "usdthb": [cnbc("THB="), yahoo("THB=X")],
        "us10y": [cnbc("US10Y"), yahoo("^TNX", "tnx"), treasury(now)],   # Cboe's ^TNX is computed 08:00-15:00 New York
        "vix": [cboe("VIX"), yahoo("^VIX"), cnbc(".VIX", "vix")],
        "set": [cnbc(".SETI", "set"), yahoo("^SET.BK")],
        "nikkei": [Source("Nikkei Indexes", ("https://indexes.nikkei.co.jp/en/nkave/get_real_data?idx=nk225",),
                          "https://indexes.nikkei.co.jp/en/nkave", parse_nikkei),
                   yahoo("^N225"), cnbc(".N225", "tokyo")],
    }


# ----------------------------------------------------------------- sessions and wording
def session_state(group: str, now: dt.datetime) -> str:
    """open | lunch | closed | weekend for a trading-hours group at `now` (weekday hours; holidays are not known)."""
    if group in ("always", "gta"):
        return "open"
    lt = now.astimezone(GROUP_TZ[group])
    m = lt.hour * 60 + lt.minute
    if group == "globex":    # Sunday 18:00 to Friday 17:00 New York (the daily 17-18 pause counts as open)
        wk = lt.weekday() == 5 or (lt.weekday() == 6 and m < 18 * 60) or (lt.weekday() == 4 and m >= 17 * 60)
        return "weekend" if wk else "open"
    ss = SESSIONS[group]
    if lt.weekday() >= 5 or (lt.weekday() == 4 and m >= ss[-1][1]):      # Friday after the close counts as the weekend
        return "weekend"
    if any(a <= m < z for a, z in ss):
        return "open"
    if len(ss) > 1 and ss[0][1] <= m < ss[1][0]:
        return "lunch"
    return "closed"


def quote_state(key: str, q: Quote, now: dt.datetime) -> str:
    """The wording state of this quote: open | lunch | closed | weekend | idle (open session, no trade for hours)."""
    group = q.group or GROUP[key]
    if q.daily:
        return "closed"
    st = session_state(group, now)
    tz = GROUP_TZ[group]
    if st == "open" and group not in ("always", "gta") and (now - q.as_of).total_seconds() > IDLE_AFTER_H * 3600:
        return "idle"
    if st == "lunch" and q.as_of.astimezone(tz).date() != now.astimezone(tz).date():
        return "idle"
    return st


def fmt_num(x: float, d: int) -> str:
    s = f"{abs(x):,.{d}f}"
    return (MINUS if x < 0 and float(s.replace(",", "")) != 0 else "") + s


def fmt_signed(x: float, d: int) -> str:
    s = f"{abs(x):,.{d}f}"
    if float(s.replace(",", "")) == 0:
        return s
    return ("+" if x > 0 else MINUS) + s


def th_day(t: dt.datetime, tz: dt.tzinfo) -> str:
    lt = t.astimezone(tz)
    return f"{lt.day} {ld.TH_MONTHS[lt.month - 1]}"


def trend_of(delta: float | None, scale: float) -> str:
    if delta is None or abs(delta) <= scale * 1e-4:      # < 0.01 % of the value counts as flat
        return "flat"
    return "up" if delta > 0 else "down"


def change_text(key: str, q: Quote, state: str, prev_item: dict | None, now: dt.datetime) -> tuple[str, str]:
    """(change_th, trend) generated from the numbers."""
    tz = GROUP_TZ[q.group or GROUP[key]]
    d = DECIMALS[key]
    if key == "gold_th":
        t = q.as_of.astimezone(BKK)
        when = f"ประกาศครั้งที่ {q.extra.get('seq')} เวลา {t:%H:%M} น."
        if t.date() != now.astimezone(BKK).date():
            when = f"ประกาศ {th_day(q.as_of, BKK)} ครั้งที่ {q.extra.get('seq')} เวลา {t:%H:%M} น."
        row = None if q.prev is None else q.value - q.prev
        parts = [when]
        if row is not None:
            parts.append("ไม่เปลี่ยนแปลง" if row == 0 else f"{fmt_signed(row, 0)} บาท")
        dc = q.extra.get("day_change")
        if dc is not None and q.extra.get("seq") != 1:
            parts.append(f"· {fmt_signed(dc, 0)} จากวันก่อน" if dc else "· เท่ากับวันก่อน")
        return " ".join(parts), trend_of(row if row else dc, q.value)
    ref = q.prev
    if q.basis == "prev_update":
        ref = ld.parse_number((prev_item or {}).get("value"))
    if ref is None or ref == 0:
        base = {"open": "ราคาระหว่างวัน", "lunch": "ปิดภาคเช้า", "idle": "ยังไม่มีการซื้อขายใหม่", "weekend": "ปิดสุดสัปดาห์"}.get(state)
        return base or f"ปิด {th_day(q.as_of, tz)}", "flat"
    delta = q.value - ref
    if key == "us10y":
        move = f"{fmt_signed(delta * 100, 1)} bp"
    else:
        move = f"{fmt_signed(delta / abs(ref) * 100, 2)}% ({fmt_signed(delta, d)})"
    trend = trend_of(delta, q.value)
    if q.basis == "24h":
        return f"{move} ใน 24 ชม.", trend
    if q.basis == "prev_update":
        when = ld.bkk_th(ld.parse_ts_iso((prev_item or {}).get("as_of"))) if prev_item else ""
        return (f"{move} จากค่ารอบก่อน" + (f" ({when})" if when else "")), trend
    day = th_day(q.as_of, tz)
    if state == "open":
        return f"{move} จากปิดก่อนหน้า", trend
    if state == "lunch":
        return f"ปิดภาคเช้า {day} {move}", trend
    if state == "weekend":
        return f"ปิด {day} {move} · ตลาดปิดเสาร์–อาทิตย์", trend
    if state == "idle":
        return f"ปิด {day} {move} · ยังไม่มีการซื้อขายใหม่ (อาจเป็นวันหยุดตลาด)", trend
    return f"ปิด {day} {move}", trend


# ----------------------------------------------------------------- the run
@dataclass
class Result:
    quote: Quote | None = None
    source: Source | None = None
    rank: int = 0                          # 0 = primary
    errors: list[str] = field(default_factory=list)
    older: bool = False                    # feeds answered, but nothing newer than the previous as_of


def check_quote(q: Quote, now: dt.datetime) -> Quote:
    if not (math.isfinite(q.value) and q.value > 0):
        raise FeedError(f"implausible value {q.value!r}")
    ahead = (q.as_of - now).total_seconds()
    if ahead > FUTURE_SLACK_S:
        raise FeedError(f"quote time {ld.iso(q.as_of)} is in the future")
    if ahead > 0:
        q.as_of = now
    if (now - q.as_of).days > MAX_QUOTE_AGE_DAYS:
        raise FeedError(f"newest quote {ld.iso(q.as_of)} is older than {MAX_QUOTE_AGE_DAYS} days")
    return q


def collect(fetch: Fetch, prev_market: dict, now: dt.datetime, table: dict[str, list[Source]] | None = None,
            deadline_s: float = DEADLINE_S) -> dict[str, Result]:
    """Try each key's sources in order; stop at the first quote at least as new as the previous item."""
    table = table or sources(now)
    prev_as_of = {i["key"]: i.get("as_of") for i in prev_market.get("items", [])}
    started = time.monotonic()
    out: dict[str, Result] = {}
    for key in ld.MARKET_KEYS:
        res = Result()
        for rank, src in enumerate(table[key]):
            if time.monotonic() - started > deadline_s:
                res.errors.append(f"{src.name}: skipped (run deadline)")
                continue
            try:
                q = check_quote(src.get(fetch, now), now)
            except FeedError as e:
                res.errors.append(f"{src.name}: {e}")
                continue
            if res.quote is None or q.as_of > res.quote.as_of:
                res.quote, res.source, res.rank = q, src, rank
            old = prev_as_of.get(key)
            if old and ld.ISO_RE.match(str(old)) and q.as_of.timestamp() < ld._ts(old):
                res.older = True
                res.errors.append(f"{src.name}: {ld.iso(q.as_of)} older than the previous {old}")
                continue
            res.quote, res.source, res.rank, res.older = q, src, rank, False
            break
        out[key] = res
    return out


def _fail_text(old: dict) -> str:
    base = re.sub(r"^" + re.escape(FAIL_PREFIX) + r"( · )?", "", str(old.get("change_th") or ""))
    base = "" if base.startswith(ld.STALE_PREFIX) else base
    return ld.clean_th(f"{FAIL_PREFIX} · {base}" if base else FAIL_PREFIX, 220)


def build_market(prev_market: dict, results: dict[str, Result], now: dt.datetime) -> tuple[dict, list[str], dict]:
    """market.json doc + sanity notes + a summary (failed / fallback / states / rejected keys)."""
    prev_items = {i["key"]: i for i in prev_market["items"]}
    sub: dict[str, dict] = {}
    states: dict[str, str] = {}
    for key, r in results.items():
        if r.quote is None:
            continue
        q = r.quote
        q.value = round(q.value, DECIMALS[key])          # the change is computed from the number shown
        st = quote_state(key, q, now)
        states[key] = st
        text, trend = change_text(key, q, st, prev_items.get(key), now)
        item = {"value": f"{q.value:.{DECIMALS[key]}f}", "change_th": text, "trend": trend, "as_of": ld.iso(q.as_of), "source": q.page}
        if key == "gold_th":
            item.update({k: q.extra[k] for k in ld.GOLD_TH_EXTRA if k in q.extra})
        sub[key] = item
    items, notes = ld.sanity_market(prev_market, sub)
    failed = [k for k, r in results.items() if r.quote is None]
    for it in items:
        if it["key"] in failed:
            it["change_th"] = _fail_text(prev_items[it["key"]])
    notes = [n for n in notes if not any(n.startswith(f"{k}: missing") for k in failed)]
    rejected = [n.split(":")[0] for n in notes if "older than" not in n]
    info = {"failed": failed, "rejected": rejected, "states": states,
            "fallback": [k for k, r in results.items() if r.quote is not None and r.rank > 0 and not r.older],
            "older": [k for k, r in results.items() if r.older]}
    doc = {"updated_at": ld.iso(now), "note_th": note_th(results, info, now), "items": items}
    return doc, notes, info


def note_th(results: dict[str, Result], info: dict, now: dt.datetime) -> str:
    names = lambda ks: ", ".join(SHORT_TH[k] for k in ks)  # noqa: E731
    st = info["states"]
    fresh = [k for k in ld.MARKET_KEYS if k in st and k not in info["older"] and k not in info["rejected"]]
    intraday = [k for k in fresh if st[k] == "open" and k not in ("btc", "gold_th")]
    closes = [k for k in fresh if st[k] in ("closed", "weekend", "idle", "lunch")]
    parts = [f"ดึงราคาตรงจากแหล่งข้อมูลฟรี ไม่ผ่าน AI เมื่อ {ld.bkk_th(now)}"]
    if intraday:
        parts.append(f"ราคาระหว่างวัน: {names(intraday)}")
    if closes:
        parts.append(f"ราคาปิดล่าสุด: {names(closes)}")
    if "btc" in fresh:
        parts.append("Bitcoin ซื้อขายตลอด 24 ชม.")
    gq = results.get("gold_th")
    if "gold_th" in fresh and gq and gq.quote:
        parts.append(f"ทองคำแท่งไทยตามประกาศสมาคมค้าทองคำครั้งที่ {gq.quote.extra.get('seq')}")
    if info["older"]:
        parts.append(f"ยังไม่มีค่าใหม่กว่ารอบก่อน: {names(info['older'])}")
    if info["fallback"]:
        parts.append(f"ใช้แหล่งสำรอง: {names(info['fallback'])}")
    if info["rejected"]:
        parts.append(f"ไม่ผ่านการตรวจ คงค่าเดิม: {names(info['rejected'])}")
    if info["failed"]:
        parts.append(f"ดึงไม่สำเร็จ คงค่าเดิม: {names(info['failed'])}")
    return ld.clean_th(" · ".join(parts), 500)


def status_doc(prev_status: dict, changed: int, info: dict, now: dt.datetime) -> dict:
    total = len(ld.MARKET_KEYS)
    msg = f"อัปเดตราคาอัตโนมัติ {ld.bkk_th(now)} · " + (f"ราคาเปลี่ยน {changed}/{total} รายการ" if changed
                                                        else f"รอบนี้ไม่พบราคาใหม่กว่ารอบก่อน (เปลี่ยน 0/{total} รายการ)")
    if info["failed"]:
        msg += f" · ดึงไม่สำเร็จ {len(info['failed'])} รายการ (คงค่าเดิม)"
    if info["rejected"]:
        msg += f" · ไม่ผ่านการตรวจ {len(info['rejected'])} รายการ"
    msg += " · ดึงตรงจากแหล่งข้อมูลฟรี"
    return {"updated_at": ld.iso(now), "run_count": int(prev_status.get("run_count", 0)) + 1, "ok": True, "message_th": ld.clean_th(msg, 600)}


def print_table(results: dict[str, Result], market: dict | None) -> None:
    items = {i["key"]: i for i in (market or {}).get("items", [])}
    print(f"{'key':8} {'value':>12}  {'as_of (Bangkok)':17} {'source':28} change_th")
    for key, r in results.items():
        it = items.get(key, {})
        src = (r.source.name + (" (fallback)" if r.rank else "")) if r.source else "FAILED"
        t = ld.parse_ts_iso(it.get("as_of")) if it.get("as_of") else None
        when = t.astimezone(BKK).strftime("%Y-%m-%d %H:%M") if t else "-"
        print(f"{key:8} {it.get('value', '-'):>12}  {when:17} {src:28} {it.get('change_th', '')}")
        for e in r.errors:
            print(f"{'':8} note: {e}")


def write_summary(results: dict[str, Result], market: dict | None, ok: bool, changed: int | None, note: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    items = {i["key"]: i for i in (market or {}).get("items", [])}
    lines = [f"### ราคาตลาด (ดึงตรง ไม่ผ่าน AI) {'สำเร็จ' if ok else 'ไม่สำเร็จ'}", "",
             f"ราคาเปลี่ยน {changed if changed is not None else 0}/{len(ld.MARKET_KEYS)} รายการ · ค่าใช้จ่าย $0", "",
             "| รายการ | ค่า | เวลา (กรุงเทพฯ) | แหล่ง | หมายเหตุ |", "|---|---|---|---|---|"]
    for key, r in results.items():
        it = items.get(key, {})
        t = ld.parse_ts_iso(it.get("as_of")) if it.get("as_of") else None
        src = (r.source.name + (" (สำรอง)" if r.rank else "")) if r.source else "ล้มเหลว"
        lines.append(f"| {key} | {it.get('value', '-')} | {t.astimezone(BKK):%d/%m %H:%M} | {src} | {it.get('change_th', '')} |"
                     if t else f"| {key} | - | - | {src} | |")
    if note:
        lines += ["", f"หมายเหตุ: {note}"]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


def log_run(ok: bool, requests: int, note: str, now: dt.datetime, cost_log: pathlib.Path, changed: int | None) -> None:
    ld.append_cost_row({"time_utc": ld.iso(now), "mode": "prices", "ok": "yes" if ok else "no", "model": MODEL_TAG,
                        "requests": requests, "input_tokens": 0, "output_tokens": 0, "cache_write_tokens": 0,
                        "cache_read_tokens": 0, "web_searches": 0, "cost_usd": "0.0000", "note": note[:200],
                        "web_fetches": 0, "items_changed": "" if changed is None else changed}, cost_log)
    print(f"http requests: {requests}; cost $0 ({'ok' if ok else 'FAILED'})"
          + (f"; items changed: {changed}/{len(ld.MARKET_KEYS)}" if changed is not None else ""))


def run(data_dir: pathlib.Path = ld.DATA_DIR, fetch: Fetch | None = None, now: dt.datetime | None = None,
        cost_log: pathlib.Path | None = None, table: dict[str, list[Source]] | None = None) -> int:
    now = now or ld.utcnow()
    cost_log = cost_log or ld.COST_LOG
    fetcher = fetch or HttpFetcher()
    prev, errs = ld.load_docs(data_dir, ("market", "status"))
    if errs:
        print("previous data files are invalid; refusing to run:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 2
    results = collect(fetcher, prev["market"], now, table)
    requests = getattr(fetcher, "requests", 0)
    failed = [k for k, r in results.items() if r.quote is None]
    market: dict | None = None
    changed: int | None = None
    try:
        if len(failed) > MAX_FAILED:
            raise ld.UpdateError(f"{len(failed)} of {len(ld.MARKET_KEYS)} feeds failed: {', '.join(failed)}",
                                 f"ดึงราคาไม่สำเร็จ {len(failed)}/{len(ld.MARKET_KEYS)} รายการ")
        market, notes, info = build_market(prev["market"], results, now)
        changed = ld.count_changed(prev["market"]["items"], market["items"])
        docs = {"market": market, "status": status_doc(prev["status"], changed, info, now)}
        extra, hist_notes = ld.history_docs(data_dir, docs, now)
        notes += ld.write_docs(data_dir, {**docs, **extra}) + hist_notes
        notes += [f"{k}: all feeds failed" for k in failed]
    except ld.UpdateError as e:
        print(f"prices FAILED: {e}", file=sys.stderr)
        print_table(results, prev["market"])
        try:
            ld.write_docs(data_dir, {"status": ld.failure_status(prev.get("status"), e.message_th, now)})
        except ld.UpdateError as e2:  # pragma: no cover - the failure status is built from fixed text
            print(f"could not write the failure status: {e2}", file=sys.stderr)
        log_run(False, requests, str(e), now, cost_log, None)
        write_summary(results, prev["market"], False, None, str(e))
        return 1
    print_table(results, market)
    for n in notes:
        print(f"sanity: {n}")
    if failed:
        print(f"::warning::prices.py: no feed answered for {', '.join(failed)} - previous values kept")
    print(f"wrote market.json, status.json{', gold_history.json' if extra else ''} in {data_dir}")
    log_run(True, requests, "; ".join(notes), now, cost_log, changed)
    write_summary(results, market, True, changed, "; ".join(notes))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data-dir", type=pathlib.Path, default=ld.DATA_DIR, help="site/data directory to update")
    ap.add_argument("--cost-log", type=pathlib.Path, default=None, help="cost log CSV (default updater/cost-log.csv)")
    args = ap.parse_args(argv)
    return run(args.data_dir, cost_log=args.cost_log)


if __name__ == "__main__":
    sys.exit(main())
