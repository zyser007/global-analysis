"""Unit tests for updater/prices.py - no network, no API key.

The fixtures in fixtures/prices/ are real responses of every feed, saved on Wed 4 Nov 2026 around 06:09-06:21 UTC
(13:09 Bangkok: FX, oil and gold trading, Nikkei open, SET in its lunch break, the US cash session closed).
"""
from __future__ import annotations

import copy
import csv
import datetime as dt
import json
import pathlib
import shutil
import sys
import urllib.error

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "updater"))
import livedata as ld  # noqa: E402
import prices  # noqa: E402
import update  # noqa: E402

FIX = HERE / "fixtures" / "prices"
SEED = HERE / "fixtures" / "data"
UTC = dt.timezone.utc
FEED_NOW = dt.datetime(2026, 11, 4, 6, 21, 30, tzinfo=UTC)      # just after the last fixture was saved


def T(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


# host + symbol fragment -> fixture file
ROUTES = [
    ("quote.cnbc.com", "%40LCO.1", "cnbc_brent.json"), ("quote.cnbc.com", "%40CL.1", "cnbc_wti.json"),
    ("quote.cnbc.com", "XAU%3D", "cnbc_gold.json"), ("quote.cnbc.com", ".DXY", "cnbc_dxy.json"),
    ("quote.cnbc.com", "THB%3D", "cnbc_usdthb.json"), ("quote.cnbc.com", "US10Y", "cnbc_us10y.json"),
    ("quote.cnbc.com", ".SETI", "cnbc_set.json"), ("quote.cnbc.com", ".SPX", "cnbc_spx.json"),
    ("quote.cnbc.com", ".NDX", "cnbc_ndx.json"), ("quote.cnbc.com", ".VIX", "cnbc_vix.json"),
    ("quote.cnbc.com", ".N225", "cnbc_nikkei.json"),
    ("finance.yahoo.com", "/BZ%3DF", "yahoo_brent.json"), ("finance.yahoo.com", "/CL%3DF", "yahoo_wti.json"),
    ("finance.yahoo.com", "/DX-Y.NYB", "yahoo_dxy.json"), ("finance.yahoo.com", "/%5EGSPC", "yahoo_spx.json"),
    ("finance.yahoo.com", "/%5ENDX", "yahoo_ndx.json"), ("finance.yahoo.com", "/%5EVIX", "yahoo_vix.json"),
    ("finance.yahoo.com", "/THB%3DX", "yahoo_usdthb.json"), ("finance.yahoo.com", "/%5ESET.BK", "yahoo_set.json"),
    ("finance.yahoo.com", "/%5EN225", "yahoo_nikkei.json"), ("finance.yahoo.com", "/%5ETNX", "yahoo_us10y.json"),
    ("cboe.com", "_SPX.json", "cboe_spx.json"), ("cboe.com", "_NDX.json", "cboe_ndx.json"), ("cboe.com", "_VIX.json", "cboe_vix.json"),
    ("indexes.nikkei.co.jp", "nk225", "nikkei.json"), ("api.coingecko.com", "bitcoin", "coingecko.json"),
    ("api.exchange.coinbase.com", "/ticker", "coinbase_ticker.json"), ("api.exchange.coinbase.com", "/stats", "coinbase_stats.json"),
    ("swissquote.com", "XAU/USD", "swissquote_xau.json"), ("home.treasury.gov", "daily_treasury_yield_curve", "treasury.csv"),
    ("www.goldtraders.or.th", "GoldPrices/Latest", "gta_latest.json"), ("classic.goldtraders.or.th", "UpdatePriceList", "gta_classic.html"),
]


class FixtureFetch:
    """Stands in for HttpFetcher: serves the saved responses, records calls, fails hosts / files on request."""

    def __init__(self, fail=(), override=None):
        self.fail = tuple(fail)              # substrings of URLs (hosts) or fixture names that answer HTTP 503
        self.override = override or {}       # fixture name -> bytes
        self.calls: list[str] = []
        self.requests = 0

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        self.requests += 1
        for host, frag, name in ROUTES:
            if host in url and frag in url:
                if any(f in url or f == name for f in self.fail):
                    raise prices.FeedError("HTTP 503")
                return self.override.get(name) or (FIX / name).read_bytes()
        raise prices.FeedError(f"no fixture for {url}")


def fixture(name: str) -> bytes:
    return (FIX / name).read_bytes()


def edit_json(name: str, fn) -> bytes:
    d = json.loads(fixture(name))
    fn(d)
    return json.dumps(d).encode()


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    shutil.copytree(SEED, d)
    return d


@pytest.fixture(autouse=True)
def _no_real_cost_log(tmp_path, monkeypatch):
    monkeypatch.setattr(ld, "COST_LOG", tmp_path / "real-cost-log-guard.csv")


def read(d: pathlib.Path, name: str) -> dict:
    return json.loads((d / f"{name}.json").read_text(encoding="utf-8"))


def by_key(m: dict) -> dict:
    return {i["key"]: i for i in m["items"]}


def run_prices(data_dir, fetch=None, now=FEED_NOW, cost_log=None):
    fetch = fetch or FixtureFetch()
    cost_log = cost_log or data_dir.parent / "cost.csv"
    return prices.run(data_dir, fetch=fetch, now=now, cost_log=cost_log), fetch


# ----------------------------------------------------------------- every feed parses its saved response
NOWX = dict(now=FEED_NOW, page="https://example.com/p")


@pytest.mark.parametrize("parse,name,value,as_of,prev", [
    (prices.parse_cnbc, "cnbc_brent.json", 103.59, "2026-11-04T05:58:47Z", 103.6),
    (prices.parse_cnbc, "cnbc_wti.json", 96.06, None, None),
    (prices.parse_cnbc, "cnbc_gold.json", 4005.4, "2026-11-04T06:02:01Z", 3928.25),
    (prices.parse_cnbc, "cnbc_us10y.json", 4.939, "2026-11-04T06:07:56Z", 4.95),       # "4.939%" -> 4.939
    (prices.parse_cnbc, "cnbc_usdthb.json", 33.71, None, None),
    (prices.parse_cnbc, "cnbc_set.json", 1489.66, "2026-11-04T05:30:05Z", 1491.01),     # "1,489.66", +0700
    (prices.parse_yahoo, "yahoo_spx.json", 7568.92, "2026-11-03T21:30:13Z", 7541.4),
    (prices.parse_yahoo, "yahoo_us10y.json", 4.952, "2026-11-03T19:59:55Z", 4.894),
    (prices.parse_cboe, "cboe_spx.json", 7568.9199, "2026-11-03T21:14:59Z", 7541.4),   # naive New York time
    (prices.parse_cboe, "cboe_vix.json", 20.83, "2026-11-03T21:15:01Z", 21.15),
    (prices.parse_nikkei, "nikkei.json", 62079.17, "2026-11-04T06:09:00Z", 63081.86),  # 'Nov/04/2026(15:09)' Tokyo
    (prices.parse_nikkei, "nikkei_close.json", 62188.63, "2026-11-04T06:30:00Z", 63081.86),  # 'Nov/04/2026(Close)' = 15:30
    (prices.parse_coingecko, "coingecko.json", 77785.0, "2026-11-04T06:08:02Z", None),
    (prices.parse_swissquote, "swissquote_xau.json", 4000.955, "2026-11-04T06:09:07Z", None),
    (prices.parse_treasury, "treasury.csv", 4.95, "2026-11-03T20:30:00Z", 4.91),       # 11/03/2026 15:30 New York
    (prices.parse_gta_latest, "gta_latest.json", 63950.0, "2026-11-04T06:03:00Z", 63900.0),
    (prices.parse_gta_classic, "gta_classic.html", 63900.0, "2026-11-04T06:02:00Z", 63850.0),  # 04/11/2569 13:02
])
def test_parsers_read_the_saved_responses(parse, name, value, as_of, prev):
    q = parse(fixture(name), **NOWX)
    assert q.value == pytest.approx(value)
    if as_of:
        assert ld.iso(q.as_of) == as_of
    if prev is not None:
        assert q.prev == pytest.approx(prev)
    assert q.as_of.tzinfo is not None and q.page == "https://example.com/p"


def test_coinbase_uses_the_ticker_time_and_the_24h_open():
    q = prices.parse_coinbase(fixture("coinbase_ticker.json"), fixture("coinbase_stats.json"), **NOWX)
    assert q.value == 77700.43 and ld.iso(q.as_of) == "2026-11-04T06:09:04Z"   # nanoseconds trimmed
    assert q.prev == 76455.25 and q.basis == "24h"


def test_coingecko_reference_comes_from_the_24h_change():
    q = prices.parse_coingecko(fixture("coingecko.json"), **NOWX)
    pct = json.loads(fixture("coingecko.json"))["bitcoin"]["usd_24h_change"]
    assert (q.value / q.prev - 1) * 100 == pytest.approx(pct) and q.basis == "24h"


def test_gta_latest_carries_the_whole_announcement():
    q = prices.parse_gta_latest(fixture("gta_latest.json"), **NOWX)
    assert q.extra == {"seq": 28, "buy": 63750, "ornament_sell": 64750, "day_change": 1450.0}
    assert isinstance(q.extra["buy"], int) and q.basis == "announcement"


def test_gta_classic_table_newest_row_buddhist_year_and_thai_digits():
    q = prices.parse_gta_classic(fixture("gta_classic.html"), **NOWX)
    assert q.extra == {"seq": 27, "buy": 63700, "ornament_sell": 64700}
    thai = fixture("gta_classic.html").decode("utf-8").translate(str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙"))
    q2 = prices.parse_gta_classic(thai.encode("utf-8"), **NOWX)
    assert (q2.value, q2.as_of, q2.prev, q2.extra) == (q.value, q.as_of, q.prev, q.extra)
    with pytest.raises(prices.FeedError):
        prices.parse_gta_classic(b"<html><table><tr><td>no rows</td></tr></table></html>", **NOWX)


def test_cnbc_closed_index_gives_a_date_only_and_gets_the_session_close():
    q = prices.parse_cnbc(fixture("cnbc_spx.json"), FEED_NOW, "p", "us")
    assert ld.iso(q.as_of) == "2026-11-03T21:00:00Z"                 # 16:00 New York (EST)
    raw = edit_json("cnbc_spx.json", lambda d: d["FormattedQuoteResult"]["FormattedQuote"][0].update(last_time="2026-07-02"))
    assert ld.iso(prices.parse_cnbc(raw, FEED_NOW, "p", "us").as_of) == "2026-07-02T20:00:00Z"   # EDT
    q = prices.parse_cnbc(fixture("cnbc_vix.json"), FEED_NOW, "p", "vix")
    assert ld.iso(q.as_of) == "2026-11-03T21:15:00Z"


@pytest.mark.parametrize("raw,expected", [
    ("2026-11-04T01:04:30.000-0500", "2026-11-04T06:04:30Z"),
    ("2026-11-04T12:30:05.000+0700", "2026-11-04T05:30:05Z"),
    ("2026-11-03T13:59:55.128000-06:00", "2026-11-03T19:59:55Z"),
    ("2026-11-04T06:03:24.825283226Z", "2026-11-04T06:03:24Z"),
    ("2026-11-03T16:14:59", "2026-11-03T21:14:59Z"),          # naive -> New York (EST)
    ("2026-07-01 16:00", "2026-07-01T20:00:00Z"),             # naive in summer (EDT)
])
def test_parse_ts_time_zones(raw, expected):
    assert ld.iso(prices.parse_ts(raw, prices.NY)) == expected


@pytest.mark.parametrize("bad", ["", "yesterday", "2026-11-04", "04/11/2026 13:00", None])
def test_parse_ts_rejects_junk(bad):
    with pytest.raises(prices.FeedError):
        prices.parse_ts(bad, prices.NY)


@pytest.mark.parametrize("parse,raw", [
    (prices.parse_cnbc, b"<html>blocked</html>"),
    (prices.parse_cnbc, b'{"FormattedQuoteResult":{"FormattedQuote":[{"symbol":"X","code":1}]}}'),
    (prices.parse_yahoo, b'{"chart":{"result":null,"error":{"code":"Not Found"}}}'),
    (prices.parse_cboe, b'{"data":{"current_price":0,"last_trade_time":"2026-11-03T16:00:00"}}'),
    (prices.parse_nikkei, b'{"price":"61,915.82","datedtime":"later"}'),
    (prices.parse_coingecko, b"{}"),
    (prices.parse_swissquote, b"[]"),
    (prices.parse_treasury, b"Date,10 Yr\n"),
    (prices.parse_gta_latest, b"[]"),
    (prices.parse_gta_latest, b'{"asTime":"2026-11-04T13:03:00","seq":28,"bL_SellPrice":"n/a"}'),
])
def test_junk_responses_are_feed_errors(parse, raw):
    with pytest.raises(prices.FeedError):
        parse(raw, **NOWX)


# ----------------------------------------------------------------- sessions and wording
@pytest.mark.parametrize("group,when,state", [
    ("globex", "2026-11-04T06:00:00Z", "open"),
    ("globex", "2026-11-07T03:00:00Z", "weekend"),      # Saturday
    ("globex", "2026-11-08T22:00:00Z", "weekend"),      # Sunday 17:00 New York
    ("globex", "2026-11-08T23:30:00Z", "open"),         # Sunday 18:30 New York
    ("globex", "2026-11-06T22:30:00Z", "weekend"),      # Friday 17:30 New York
    ("us", "2026-11-04T15:00:00Z", "open"),             # 10:00 New York
    ("us", "2026-11-04T21:10:00Z", "closed"),           # 16:10 New York
    ("vix", "2026-11-04T21:10:00Z", "open"),            # VIX until 16:15
    ("set", "2026-11-04T06:00:00Z", "lunch"),           # 13:00 Bangkok
    ("set", "2026-11-04T04:00:00Z", "open"),
    ("set", "2026-11-04T10:00:00Z", "closed"),          # 17:00 Bangkok
    ("set", "2026-11-07T04:00:00Z", "weekend"),
    ("tokyo", "2026-11-04T03:00:00Z", "lunch"),         # 12:00 Tokyo
    ("tokyo", "2026-11-04T06:00:00Z", "open"),          # 15:00 Tokyo (session to 15:30)
    ("tokyo", "2026-11-04T06:40:00Z", "closed"),
    ("always", "2026-11-07T03:00:00Z", "open"),
])
def test_session_state(group, when, state):
    assert prices.session_state(group, T(when)) == state


def Q(value, as_of, prev=None, **kw):
    return prices.Quote(value, T(as_of), "https://example.com", prev, **kw)


@pytest.mark.parametrize("key,q,now,text,trend", [
    ("wti", Q(97.17, "2026-11-04T05:00:00Z", 96.46), "2026-11-04T05:10:00Z", "+0.74% (+0.71) จากปิดก่อนหน้า", "up"),
    ("spx", Q(7568.92, "2026-11-03T21:14:59Z", 7541.40), "2026-11-04T06:00:00Z", "ปิด 3 พ.ย. +0.36% (+27.52)", "up"),
    ("set", Q(1491.01, "2026-11-03T09:30:00Z", 1507.14), "2026-11-03T10:00:00Z", "ปิด 3 พ.ย. −1.07% (−16.13)", "down"),
    ("set", Q(1489.66, "2026-11-04T05:30:05Z", 1491.01), "2026-11-04T06:00:00Z", "ปิดภาคเช้า 4 พ.ย. −0.09% (−1.35)", "down"),
    ("spx", Q(7600.0, "2026-11-06T21:15:00Z", 7600.0), "2026-11-07T03:00:00Z", "ปิด 6 พ.ย. 0.00% (0.00) · ตลาดปิดเสาร์–อาทิตย์", "flat"),
    ("brent", Q(104.0, "2026-11-06T21:59:00Z", 103.0), "2026-11-07T03:00:00Z", "ปิด 6 พ.ย. +0.97% (+1.00) · ตลาดปิดเสาร์–อาทิตย์", "up"),
    # Japan's Culture Day: Tokyo is "open" by the clock, the newest quote is Monday's close
    ("nikkei", Q(63081.86, "2026-11-02T06:30:00Z", 63290.0), "2026-11-03T03:00:00Z",
     "ปิด 2 พ.ย. −0.33% (−208.14) · ยังไม่มีการซื้อขายใหม่ (อาจเป็นวันหยุดตลาด)", "down"),
    ("us10y", Q(4.939, "2026-11-04T06:07:56Z", 4.95), "2026-11-04T06:10:00Z", "−1.1 bp จากปิดก่อนหน้า", "down"),
    ("us10y", Q(4.95, "2026-11-03T20:30:00Z", 4.91, daily=True), "2026-11-04T06:10:00Z", "ปิด 3 พ.ย. +4.0 bp", "up"),
    ("btc", Q(77785, "2026-11-04T06:08:02Z", 76424.28, basis="24h"), "2026-11-04T06:10:00Z", "+1.78% (+1,361) ใน 24 ชม.", "up"),
])
def test_change_th_wording(key, q, now, text, trend):
    st = prices.quote_state(key, q, T(now))
    assert prices.change_text(key, q, st, None, T(now)) == (text, trend)
    assert "-" not in text and '"' not in text        # Unicode minus only, no raw quotes


def test_spot_gold_falls_back_to_the_cnbc_quote_and_then_to_the_previous_update(data_dir):
    src = prices.sources(FEED_NOW)["gold"]
    q = src[0].get(FixtureFetch(), FEED_NOW)
    assert (q.prev, q.basis) == (3928.25, "prev_close")
    q = src[0].get(FixtureFetch(fail=["quote.cnbc.com"]), FEED_NOW)        # no reference: vs the previous update
    assert (q.prev, q.basis) == (None, "prev_update")
    fetch = FixtureFetch(fail=["swissquote.com"])
    assert run_prices(data_dir, fetch)[0] == 0
    g = by_key(read(data_dir, "market"))["gold"]
    assert (g["value"], g["source"], g["change_th"]) == ("4005.40", "https://www.cnbc.com/quotes/XAU=", "+1.96% (+77.15) จากปิดก่อนหน้า")


def test_change_vs_the_previous_update_when_a_feed_has_no_close():
    q = Q(4000.96, "2026-11-04T06:09:07Z", basis="prev_update")
    prev = {"value": "3935.06", "as_of": "2026-11-04T01:10:00Z"}
    text, trend = prices.change_text("gold", q, "open", prev, T("2026-11-04T06:10:00Z"))
    assert text == "+1.67% (+65.90) จากค่ารอบก่อน (4 พ.ย. 2569 08:10 น.)" and trend == "up"


@pytest.mark.parametrize("extra,prev,now,text,trend", [
    ({"seq": 5, "day_change": 450.0}, 62400, "2026-11-04T05:00:00Z", "ประกาศครั้งที่ 5 เวลา 11:20 น. +100 บาท · +450 จากวันก่อน", "up"),
    ({"seq": 1, "day_change": 450.0}, 62050, "2026-11-04T05:00:00Z", "ประกาศครั้งที่ 1 เวลา 11:20 น. +450 บาท", "up"),
    ({"seq": 9}, 62600, "2026-11-04T05:00:00Z", "ประกาศครั้งที่ 9 เวลา 11:20 น. −100 บาท", "down"),
    ({"seq": 3, "day_change": 0.0}, 62500, "2026-11-04T05:00:00Z", "ประกาศครั้งที่ 3 เวลา 11:20 น. ไม่เปลี่ยนแปลง · เท่ากับวันก่อน", "flat"),
    ({"seq": 12, "day_change": -1250.0}, 62550, "2026-11-07T03:00:00Z",       # Saturday: Wednesday's last announcement
     "ประกาศ 4 พ.ย. ครั้งที่ 12 เวลา 11:20 น. −50 บาท · −1,250 จากวันก่อน", "down"),
])
def test_gold_th_wording(extra, prev, now, text, trend):
    q = Q(62500, "2026-11-04T04:20:00Z", prev, basis="announcement", extra=extra)
    assert prices.change_text("gold_th", q, "open", None, T(now)) == (text, trend)


# ----------------------------------------------------------------- full runs on the saved responses
def test_run_writes_all_13_from_the_primary_feeds(data_dir, tmp_path, capsys):
    log = tmp_path / "cost.csv"
    code, fetch = run_prices(data_dir, cost_log=log)
    assert code == 0
    m, s = read(data_dir, "market"), read(data_dir, "status")
    assert ld.validate_doc("market", m) == [] and ld.validate_doc("status", s) == []
    it = by_key(m)
    seed_items = by_key(json.loads((SEED / "market.json").read_text(encoding="utf-8")))
    assert [i["key"] for i in m["items"]] == list(ld.MARKET_KEYS)
    for k, i in it.items():
        assert (i["label_th"], i["unit"]) == (seed_items[k]["label_th"], seed_items[k]["unit"])
        assert ld.ISO_RE.match(i["as_of"]) and i["source"].startswith("https://")
    assert (it["brent"]["value"], it["brent"]["as_of"], it["brent"]["source"]) == ("103.59", "2026-11-04T05:58:47Z", "https://www.cnbc.com/quotes/@LCO.1")
    assert (it["spx"]["value"], it["spx"]["source"]) == ("7568.92", "https://www.cboe.com/us/indices/dashboard/spx/")
    assert (it["nikkei"]["value"], it["nikkei"]["source"]) == ("62079.17", "https://indexes.nikkei.co.jp/en/nkave")
    assert (it["btc"]["value"], it["us10y"]["value"], it["usdthb"]["value"]) == ("77785", "4.939", "33.710")
    # gold: Swissquote's live mid, CNBC XAU='s previous close as the reference
    assert (it["gold"]["value"], it["gold"]["as_of"], it["gold"]["source"]) == ("4000.95", "2026-11-04T06:09:07Z", "https://www.swissquote.com/")
    assert it["gold"]["change_th"] == "+1.85% (+72.70) จากปิดก่อนหน้า"
    g = it["gold_th"]
    assert (g["value"], g["buy"], g["ornament_sell"], g["as_of"]) == ("63950", 63750, 64750, "2026-11-04T06:03:00Z")
    assert g["change_th"] == "ประกาศครั้งที่ 28 เวลา 13:03 น. +50 บาท · +1,450 จากวันก่อน"
    assert it["spx"]["change_th"] == "ปิด 3 พ.ย. +0.36% (+27.52)" and it["set"]["change_th"].startswith("ปิดภาคเช้า 4 พ.ย.")
    assert m["updated_at"] == "2026-11-04T06:21:30Z"
    assert "ราคาเปลี่ยน 13/13 รายการ" in s["message_th"] and "13:21 น." in s["message_th"] and s["ok"] is True
    assert s["run_count"] == json.loads((SEED / "status.json").read_text(encoding="utf-8"))["run_count"] + 1
    assert "ไม่ผ่าน AI" in m["note_th"] and "ราคาระหว่างวัน: Brent, WTI" in m["note_th"] and "ราคาปิดล่าสุด: S&P 500" in m["note_th"]
    assert "ครั้งที่ 28" in m["note_th"] and "ดึงไม่สำเร็จ" not in m["note_th"]
    # one request per symbol, primaries only (gold adds CNBC's previous close); Bitcoin and Thai gold included
    assert fetch.requests == 14 and len(set(fetch.calls)) == 14
    assert not any("yahoo" in u for u in fetch.calls)
    row = list(csv.DictReader(log.open(encoding="utf-8")))[-1]
    assert (row["mode"], row["ok"], row["model"], row["cost_usd"], row["items_changed"], row["requests"]) == \
        ("prices", "yes", "free-feeds", "0.0000", "13", "14")
    assert list(row) == ld.CSV_FIELDS
    h = read(data_dir, "gold_history")
    assert h["points"][-1] == {"time": "2026-11-04T06:21:30Z", "spot": 4000.95, "spot_as_of": "2026-11-04T06:09:07Z",
                               "th_sell": 63950, "th_as_of": "2026-11-04T06:03:00Z"}
    assert not list(data_dir.glob("*.tmp"))
    out = capsys.readouterr().out
    assert "items changed: 13/13" in out and "FAILED" not in out


def test_second_run_with_the_same_quotes_changes_nothing(data_dir):
    run_prices(data_dir)
    hist = read(data_dir, "gold_history")
    code, _ = run_prices(data_dir, now=FEED_NOW + dt.timedelta(minutes=30))
    assert code == 0
    s = read(data_dir, "status")
    assert "ไม่พบราคาใหม่กว่ารอบก่อน (เปลี่ยน 0/13 รายการ)" in s["message_th"] and s["ok"] is True
    assert read(data_dir, "gold_history") == hist                 # as_of did not move: no new point


def test_primary_down_uses_each_fallback(data_dir):
    fetch = FixtureFetch(fail=["quote.cnbc.com", "cdn.cboe.com", "indexes.nikkei.co.jp", "api.coingecko.com", "www.goldtraders.or.th"])
    code, _ = run_prices(data_dir, fetch)
    assert code == 0
    it = by_key(read(data_dir, "market"))
    assert it["brent"]["source"] == "https://finance.yahoo.com/quote/BZ=F/" and it["brent"]["value"] == "103.59"
    assert it["gold"]["source"] == "https://www.swissquote.com/" and it["gold"]["value"] == "4000.95"
    assert it["gold"]["change_th"].startswith("+2.51% (+97.83) จากค่ารอบก่อน")          # vs the seed's 3903.12
    assert it["gold_th"]["source"] == "https://classic.goldtraders.or.th/UpdatePriceList.aspx" and it["gold_th"]["value"] == "63900"
    assert it["btc"]["source"] == "https://exchange.coinbase.com/trade/BTC-USD"
    assert it["us10y"]["source"] == "https://finance.yahoo.com/quote/^TNX/"
    assert it["us10y"]["change_th"] == "ปิด 3 พ.ย. +5.8 bp"          # Cboe computes ^TNX 08:00-15:00 New York only
    assert it["spx"]["source"] == "https://finance.yahoo.com/quote/^GSPC/" and it["nikkei"]["source"] == "https://finance.yahoo.com/quote/^N225/"
    m = read(data_dir, "market")
    assert "ใช้แหล่งสำรอง:" in m["note_th"] and ld.validate_doc("market", m) == []
    # the classic GTA table has no day change: only the change vs the previous announcement
    assert it["gold_th"]["change_th"] == "ประกาศครั้งที่ 27 เวลา 13:02 น. +50 บาท"


def test_treasury_is_the_last_resort_for_the_10_year(data_dir):
    code, fetch = run_prices(data_dir, FixtureFetch(fail=["quote.cnbc.com", "finance.yahoo.com"]))
    assert code == 0
    us = by_key(read(data_dir, "market"))["us10y"]
    assert (us["value"], us["as_of"], us["change_th"]) == ("4.950", "2026-11-03T20:30:00Z", "ปิด 3 พ.ย. +4.0 bp")
    assert us["source"].startswith("https://home.treasury.gov/") and any("2026/all" in u for u in fetch.calls)


def test_a_key_with_every_feed_down_keeps_its_old_item_and_says_so(data_dir, capsys):
    before = by_key(json.loads((SEED / "market.json").read_text(encoding="utf-8")))["btc"]
    fetch = FixtureFetch(fail=["api.coingecko.com", "api.exchange.coinbase.com"])
    assert run_prices(data_dir, fetch)[0] == 0
    btc = by_key(read(data_dir, "market"))["btc"]
    assert (btc["value"], btc["as_of"]) == (before["value"], before["as_of"])
    assert btc["change_th"] == f"{prices.FAIL_PREFIX} · {before['change_th']}"
    s, m = read(data_dir, "status"), read(data_dir, "market")
    assert s["ok"] is True and "ดึงไม่สำเร็จ 1 รายการ (คงค่าเดิม)" in s["message_th"] and "ราคาเปลี่ยน 12/13 รายการ" in s["message_th"]
    assert "ดึงไม่สำเร็จ คงค่าเดิม: Bitcoin" in m["note_th"]
    assert "::warning::" in capsys.readouterr().out
    # the next failing run does not stack the prefix
    run_prices(data_dir, fetch, now=FEED_NOW + dt.timedelta(hours=1))
    assert by_key(read(data_dir, "market"))["btc"]["change_th"] == btc["change_th"]


@pytest.mark.parametrize("n_failed,code", [(6, 0), (7, 1)])
def test_more_than_six_failed_keys_fail_the_run(data_dir, tmp_path, n_failed, code):
    hosts = {"brent": "%40LCO.1", "wti": "%40CL.1", "dxy": ".DXY", "usdthb": "THB%3D", "set": ".SETI"}
    fail = ["finance.yahoo.com"] + list(hosts.values())[:5] + (["api.coingecko.com", "api.exchange.coinbase.com"] if n_failed >= 6 else [])
    if n_failed == 7:
        fail += ["XAU%3D", "swissquote.com"]
    before = (data_dir / "market.json").read_bytes()
    log = tmp_path / "c.csv"
    assert run_prices(data_dir, FixtureFetch(fail=fail), cost_log=log)[0] == code
    s = read(data_dir, "status")
    row = list(csv.DictReader(log.open(encoding="utf-8")))[-1]
    if code:
        assert (data_dir / "market.json").read_bytes() == before
        assert s["ok"] is False and "ดึงราคาไม่สำเร็จ 7/13 รายการ" in s["message_th"] and ld.validate_doc("status", s) == []
        assert row["ok"] == "no" and row["cost_usd"] == "0.0000"
    else:
        assert s["ok"] is True and "ดึงไม่สำเร็จ 6 รายการ" in s["message_th"] and row["ok"] == "yes"


def test_every_feed_down_keeps_all_data(data_dir):
    before = {n: (data_dir / f"{n}.json").read_bytes() for n in ("market", "headlines")}
    assert run_prices(data_dir, FixtureFetch(fail=[r[0] for r in ROUTES]))[0] == 1
    assert {n: (data_dir / f"{n}.json").read_bytes() for n in before} == before
    assert read(data_dir, "status")["ok"] is False


def test_moves_over_15_percent_are_rejected(data_dir):
    m = read(data_dir, "market")
    by_key(m)["gold"]["value"] = "3400"                    # 4005.40 would be +17.8 %
    (data_dir / "market.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    assert run_prices(data_dir)[0] == 0
    g = by_key(read(data_dir, "market"))["gold"]
    assert g["value"] == "3400" and g["change_th"].startswith(ld.STALE_PREFIX) and "+18%" in g["change_th"]
    s, mk = read(data_dir, "status"), read(data_dir, "market")
    assert "ไม่ผ่านการตรวจ 1 รายการ" in s["message_th"] and "ไม่ผ่านการตรวจ คงค่าเดิม: ทองคำ spot" in mk["note_th"]


def test_an_older_quote_never_replaces_a_newer_one_and_a_newer_fallback_wins(data_dir):
    m = read(data_dir, "market")
    it = by_key(m)
    it["nikkei"].update(value="62500", as_of="2026-11-04T06:15:00Z")   # newer than every Nikkei fixture
    it["spx"]["as_of"] = "2026-11-03T21:20:00Z"                        # Cboe 21:14:59 is older, Yahoo 21:30:13 newer
    (data_dir / "market.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    code, fetch = run_prices(data_dir)
    assert code == 0
    new = by_key(read(data_dir, "market"))
    assert new["nikkei"] == it["nikkei"]                                # untouched, not flagged as failed
    assert new["spx"]["source"] == "https://finance.yahoo.com/quote/^GSPC/" and new["spx"]["as_of"] == "2026-11-03T21:30:13Z"
    note = read(data_dir, "market")["note_th"]
    assert "ยังไม่มีค่าใหม่กว่ารอบก่อน: Nikkei 225" in note and "ดึงไม่สำเร็จ" not in note
    assert sum("nikkei" in u or "N225" in u for u in fetch.calls) == 3   # tried all three, once each


def test_future_and_ancient_quotes_are_feed_errors(data_dir):
    future = edit_json("cboe_vix.json", lambda d: d["data"].update(last_trade_time="2026-11-05T10:00:00"))
    ancient = edit_json("nikkei.json", lambda d: d.update(datedtime="Oct/01/2026(15:30)"))
    code, _ = run_prices(data_dir, FixtureFetch(override={"cboe_vix.json": future, "nikkei.json": ancient}))
    assert code == 0
    it = by_key(read(data_dir, "market"))
    assert it["vix"]["source"] == "https://finance.yahoo.com/quote/^VIX/"
    assert it["nikkei"]["source"] == "https://finance.yahoo.com/quote/^N225/"
    q = prices.check_quote(Q(1.0, "2026-11-04T06:25:00Z"), FEED_NOW)     # 3.5 min ahead: clock skew, clamped
    assert q.as_of == FEED_NOW


def test_weekend_run_says_the_markets_are_shut(data_dir):
    sat = dt.datetime(2026, 11, 7, 3, 0, tzinfo=UTC)
    assert run_prices(data_dir, now=sat)[0] == 0
    it = by_key(read(data_dir, "market"))
    assert it["spx"]["change_th"] == "ปิด 3 พ.ย. +0.36% (+27.52) · ตลาดปิดเสาร์–อาทิตย์"
    assert it["brent"]["change_th"].endswith("· ตลาดปิดเสาร์–อาทิตย์")
    assert it["gold_th"]["change_th"].startswith("ประกาศ 4 พ.ย. ครั้งที่ 28 เวลา 13:03 น.")
    assert it["btc"]["change_th"].endswith("ใน 24 ชม.")
    assert "ราคาระหว่างวัน" not in read(data_dir, "market")["note_th"]


def test_invalid_previous_files_refuse_to_run(data_dir):
    (data_dir / "market.json").write_text("{}", encoding="utf-8")
    assert run_prices(data_dir)[0] == 2


def test_note_and_change_texts_are_schema_safe(data_dir):
    run_prices(data_dir)
    m = read(data_dir, "market")
    assert all('"' not in i["change_th"] and len(i["change_th"]) <= 220 for i in m["items"])
    assert '"' not in m["note_th"] and len(m["note_th"]) <= 500


# ----------------------------------------------------------------- the HTTP layer and the CLI
class FakeResp:
    def __init__(self, body=b"{}", status=200):
        self.body, self.status = body, status

    def read(self, n=-1):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_http_fetcher_sends_a_named_agent_times_out_and_caches(monkeypatch):
    seen = []

    def urlopen(req, timeout):
        seen.append((req.full_url, req.get_header("User-agent"), timeout))
        return FakeResp(b'{"ok":1}')
    monkeypatch.setattr(prices.urllib.request, "urlopen", urlopen)
    f = prices.HttpFetcher()
    assert f("https://a.example/x") == b'{"ok":1}' and f("https://a.example/x") == b'{"ok":1}'
    assert f.requests == 1 and len(seen) == 1
    assert seen[0][1] == prices.USER_AGENT and "world-globe-live" in seen[0][1] and seen[0][2] == prices.TIMEOUT_S


@pytest.mark.parametrize("exc,msg", [
    (urllib.error.HTTPError("https://a.example", 429, "Too Many Requests", {}, None), "HTTP 429"),
    (urllib.error.URLError("dns"), "URLError"),
    (TimeoutError("slow"), "TimeoutError"),
])
def test_http_errors_become_feed_errors(monkeypatch, exc, msg):
    def urlopen(req, timeout):
        raise exc
    monkeypatch.setattr(prices.urllib.request, "urlopen", urlopen)
    with pytest.raises(prices.FeedError, match=msg):
        prices.HttpFetcher()("https://a.example/x")


def test_oversized_response_is_refused(monkeypatch):
    monkeypatch.setattr(prices.urllib.request, "urlopen", lambda req, timeout: FakeResp(b"x" * (prices.MAX_BYTES + 1)))
    with pytest.raises(prices.FeedError, match="too large"):
        prices.HttpFetcher()("https://a.example/x")


def test_update_py_prices_mode_delegates_without_a_key(data_dir, monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(prices, "HttpFetcher", lambda: FixtureFetch())
    monkeypatch.setattr(prices.ld, "utcnow", lambda: FEED_NOW)
    monkeypatch.setattr(prices.ld, "COST_LOG", tmp_path / "c.csv")
    assert update.main(["prices", "--data-dir", str(data_dir)]) == 0
    assert by_key(read(data_dir, "market"))["brent"]["value"] == "103.59"
    assert list(csv.DictReader((tmp_path / "c.csv").open(encoding="utf-8")))[-1]["model"] == "free-feeds"


def test_source_table_covers_every_key_with_https_pages():
    table = prices.sources(FEED_NOW)
    assert list(table) == list(ld.MARKET_KEYS)
    for key, srcs in table.items():
        assert srcs, key
        for s in srcs:
            assert all(u.startswith("https://") for u in s.urls) and s.page.startswith("https://") and '"' not in s.page
    assert len(table["brent"]) >= 2 and all(len(v) >= 2 for v in table.values())
    assert "/2026/all" in table["us10y"][-1].urls[0]


def test_step_summary_lists_the_13_items(data_dir, tmp_path, monkeypatch):
    summ = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summ))
    run_prices(data_dir)
    txt = summ.read_text(encoding="utf-8")
    assert "ราคาเปลี่ยน 13/13 รายการ" in txt and "| gold_th | 63950 |" in txt and "ค่าใช้จ่าย $0" in txt


def test_main_cli_writes_into_the_given_copy(data_dir, tmp_path, monkeypatch):
    monkeypatch.setattr(prices, "HttpFetcher", lambda: FixtureFetch())
    monkeypatch.setattr(prices.ld, "utcnow", lambda: FEED_NOW)
    log = tmp_path / "x.csv"
    assert prices.main(["--data-dir", str(data_dir), "--cost-log", str(log)]) == 0
    assert log.exists() and not ld.COST_LOG.exists()
    assert copy.deepcopy(read(data_dir, "market"))["updated_at"] == "2026-11-04T06:21:30Z"
