"""gold_th buy / ornament_sell checks, gold_history.json append / skip / thin / cap, and the git backfill fold.
No network, no API key."""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import shutil
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "updater"))
import update  # noqa: E402
import backfill_gold_history as backfill  # noqa: E402
import prices  # noqa: E402
from test_prices import FEED_NOW, FixtureFetch, edit_json  # noqa: E402
from test_update import NOW, SEED, seed  # noqa: E402

UTC = dt.timezone.utc


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    shutil.copytree(SEED, d)
    return d


@pytest.fixture(autouse=True)
def _no_real_cost_log(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "COST_LOG", tmp_path / "real-cost-log-guard.csv")


def market(spot="3903.12", spot_as_of="2026-11-02T07:45:00Z", sell="62500", th_as_of="2026-11-02T07:38:00Z",
           updated="2026-11-02T08:05:00Z", **th_extra):
    m = seed("market")
    m["updated_at"] = updated
    for it in m["items"]:
        if it["key"] == "gold":
            it.update(value=spot, as_of=spot_as_of)
        if it["key"] == "gold_th":
            it.update(value=sell, as_of=th_as_of, **th_extra)
    return m


def th_item(m):
    return next(i for i in m["items"] if i["key"] == "gold_th")


# ----------------------------------------------------------------- buy / ornament_sell
@pytest.mark.parametrize("buy,orn,keep_buy,keep_orn", [
    (62300, 63300, True, True),        # the real 2 Nov board: spread 200, ornament +800
    (61500, 65000, True, True),        # limits: spread 1000, ornament +2500
    (62500, 63300, False, True),       # buy == sell
    (62600, 63300, False, True),       # buy above sell
    (61400, 63300, False, True),       # spread over 1000
    (62300, 62500, True, False),       # ornament == sell
    (62300, 62400, True, False),       # ornament below sell
    (62300, 65100, True, False),       # ornament over sell + 2500
    ("62300", True, False, False),     # not numbers
])
def test_scrub_gold_th_bounds(buy, orn, keep_buy, keep_orn):
    m = market(buy=buy, ornament_sell=orn)
    notes = update.scrub_gold_th(m)
    it = th_item(m)
    assert ("buy" in it) is keep_buy and ("ornament_sell" in it) is keep_orn
    assert it["value"] == "62500" and it["key"] == "gold_th"      # the item itself always stays
    assert len(notes) == (not keep_buy) + (not keep_orn)
    assert update.validate_doc("market", m) == []


def test_schema_allows_extras_only_on_gold_th():
    m = market(buy=62300, ornament_sell=63300)
    assert update.validate_doc("market", m) == []
    bad = copy.deepcopy(m)
    next(i for i in bad["items"] if i["key"] == "gold")["buy"] = 3900
    assert update.validate_doc("market", bad)
    bad2 = copy.deepcopy(m)
    th_item(bad2)["buy"] = "62300"
    assert update.validate_doc("market", bad2)


def test_buy_and_ornament_come_from_the_same_announcement_as_the_sell():
    q = prices.parse_gta_latest(edit_json("gta_latest.json", lambda d: None), now=FEED_NOW, page="p")
    assert (q.value, q.extra["buy"], q.extra["ornament_sell"], q.extra["seq"]) == (63950, 63750, 64750, 28)


def _run_with(data_dir, gta: dict, now=FEED_NOW):
    """prices.py on the saved feed responses, with fields of the GTA announcement replaced."""
    def patch(d):
        d.update(gta)
    fetch = FixtureFetch(override={"gta_latest.json": edit_json("gta_latest.json", patch)})
    assert prices.run(data_dir, fetch=fetch, now=now, cost_log=data_dir / "cost.csv") == 0
    return json.loads((data_dir / "market.json").read_text(encoding="utf-8"))


def test_run_keeps_valid_extras_as_numbers(data_dir, capsys):
    m = _run_with(data_dir, {"bL_SellPrice": 62700.0, "bL_BuyPrice": 62500.0, "oM965_SellPrice": 63500.0})
    it = th_item(m)
    assert (it["value"], it["buy"], it["ornament_sell"]) == ("62700", 62500, 63500)
    assert isinstance(it["buy"], int) and "dropped" not in capsys.readouterr().out


def test_run_drops_implausible_extras_but_keeps_the_item(data_dir, capsys):
    m = _run_with(data_dir, {"bL_SellPrice": 62700.0, "bL_BuyPrice": 57700.0, "oM965_SellPrice": 71700.0})
    it = th_item(m)
    assert "buy" not in it and "ornament_sell" not in it and it["value"] == "62700"
    out = capsys.readouterr().out
    assert "dropped buy" in out and "dropped ornament_sell" in out


def test_unreadable_extras_are_dropped_before_validation(data_dir):
    m = _run_with(data_dir, {"bL_BuyPrice": "n/a", "oM965_SellPrice": None})
    it = th_item(m)
    assert it["value"] == "63950" and "buy" not in it and "ornament_sell" not in it
    assert update.validate_doc("market", m) == []


def test_stale_gold_th_keeps_its_own_old_extras():
    prev = {"market": market(buy=62300, ornament_sell=63300)}
    sub = {k: {"value": "1", "change_th": "x", "trend": "up", "as_of": "2026-11-03T00:00:00Z", "source": "https://e.x"}
           for k in update.MARKET_KEYS}           # every value moves > 15 % -> old items kept
    items, _ = update.sanity_market(prev["market"], sub)
    it = next(i for i in items if i["key"] == "gold_th")
    assert it["value"] == "62500" and it["buy"] == 62300 and it["ornament_sell"] == 63300


def test_new_sell_without_extras_never_carries_the_old_buy():
    prev = market(buy=62300, ornament_sell=63300)
    sub = {i["key"]: {"value": i["value"], "change_th": "x", "trend": "up", "as_of": "2026-11-03T05:00:00Z",
                      "source": "https://e.x"} for i in prev["items"]}
    sub["gold_th"]["value"] = "62700"
    items, _ = update.sanity_market(prev, sub)
    it = next(i for i in items if i["key"] == "gold_th")
    assert it["value"] == "62700" and "buy" not in it and "ornament_sell" not in it


# ----------------------------------------------------------------- history
def test_history_point_reads_gold_and_gold_th():
    assert update.history_point(market()) == {"time": "2026-11-02T08:05:00Z", "spot": 3903.12, "spot_as_of": "2026-11-02T07:45:00Z",
                                              "th_sell": 62500, "th_as_of": "2026-11-02T07:38:00Z"}
    broken = market(spot="0")
    assert update.history_point(broken) is None


def test_append_skips_unchanged_as_of_and_adds_when_either_moves():
    t0 = dt.datetime(2026, 11, 2, 8, 5, tzinfo=UTC)
    h, ch = update.append_history(None, market(), t0)
    assert ch and len(h["points"]) == 1 and update.validate_doc(update.HISTORY, h) == []
    same, ch = update.append_history(h, market(updated="2026-11-02T12:00:00Z"), t0 + dt.timedelta(hours=4))
    assert not ch and same["points"] == h["points"] and same["updated_at"] == h["updated_at"]
    th_only, ch = update.append_history(h, market(sell="62400", th_as_of="2026-11-02T08:59:00Z", updated="2026-11-02T12:00:00Z"),
                                        t0 + dt.timedelta(hours=4))
    assert ch and len(th_only["points"]) == 2 and th_only["points"][-1]["th_sell"] == 62400
    assert th_only["updated_at"] == "2026-11-02T12:05:00Z"
    assert h["points"] and len(h["points"]) == 1          # the input doc is not mutated


def _hourly(n, start=dt.datetime(2026, 9, 1, 0, 0, tzinfo=UTC)):
    out = []
    for i in range(n):
        t = update.iso(start + dt.timedelta(hours=i))
        out.append({"time": t, "spot": 3900 + i, "spot_as_of": t, "th_sell": 62000, "th_as_of": t})
    return out


def test_compact_thins_old_points_to_one_per_bangkok_day_and_caps():
    pts = _hourly(24 * 60)                                            # 60 days, hourly
    now = dt.datetime.fromisoformat(pts[-1]["time"].replace("Z", "+00:00"))
    out = update.compact_history(pts, now, cap=10_000, full_days=30)
    recent = [p for p in pts if update._ts(p["time"]) >= now.timestamp() - 30 * 86400]
    old = out[: len(out) - len(recent)]
    assert out[len(old):] == recent
    days = [update._bkk_day(p["time"]) for p in old]
    assert len(days) == len(set(days)) and 29 <= len(old) <= 31
    # the kept point of each whole old day is its last one before Bangkok midnight (16:00Z = 23:00 Bangkok);
    # the first day starts at 07:00 Bangkok and the last old day is cut by the 30-day line
    assert all((dt.datetime.fromisoformat(p["time"].replace("Z", "+00:00")) + dt.timedelta(hours=7)).hour == 23 for p in old[:-1])
    capped = update.compact_history(pts, now, cap=400)
    assert len(capped) == 400 and capped[-1] == pts[-1]


def test_history_cap_holds_through_append():
    pts = _hourly(400)
    h = {"updated_at": pts[-1]["time"], "points": pts}
    t = dt.datetime.fromisoformat(pts[-1]["time"].replace("Z", "+00:00")) + dt.timedelta(hours=1)
    m = market(spot="3950", spot_as_of=update.iso(t), th_as_of=update.iso(t), updated=update.iso(t))
    new, ch = update.append_history(h, m, t)
    assert ch and len(new["points"]) <= update.HISTORY_CAP and new["points"][-1]["spot"] == 3950
    assert update.validate_doc(update.HISTORY, new) == []


def test_run_appends_history_and_skips_when_as_of_did_not_move(data_dir):
    _run_with(data_dir, {})
    h = json.loads((data_dir / "gold_history.json").read_text(encoding="utf-8"))
    assert len(h["points"]) == 1 and h["points"][0]["spot_as_of"] == "2026-11-04T06:09:07Z"
    assert h["points"][0]["th_as_of"] == "2026-11-04T06:03:00Z" and h["points"][0]["th_sell"] == 63950
    assert update.validate_doc(update.HISTORY, h) == []
    _run_with(data_dir, {}, now=FEED_NOW + dt.timedelta(hours=1))     # same as_of again
    assert json.loads((data_dir / "gold_history.json").read_text(encoding="utf-8")) == h
    assert not list(data_dir.glob("*.tmp"))


def test_broken_history_never_fails_the_run(data_dir, capsys):
    (data_dir / "gold_history.json").write_text("{not json", encoding="utf-8")
    _run_with(data_dir, {})
    assert (data_dir / "gold_history.json").read_text(encoding="utf-8") == "{not json"
    assert "left unchanged" in capsys.readouterr().out
    assert update.dry_run(data_dir) == 0
    assert "gold_history.json INVALID (not fatal" in capsys.readouterr().out


def test_dry_run_reports_history(capsys):
    assert update.main(["--dry-run"]) == 0
    assert "gold_history.json OK" in capsys.readouterr().out


def test_live_history_file_is_valid_and_ordered():
    doc = json.loads((ROOT / "site" / "data" / "gold_history.json").read_text(encoding="utf-8"))
    assert update.validate_doc(update.HISTORY, doc) == []
    keys = [(p["spot_as_of"], p["th_as_of"]) for p in doc["points"]]
    assert len(keys) == len(set(keys)) and keys == sorted(keys)


# ----------------------------------------------------------------- backfill
def test_backfill_folds_versions_one_point_per_distinct_as_of():
    versions = [
        market(),
        market(updated="2026-11-02T11:51:22Z"),                                                 # nothing moved
        market(spot="3901.81", spot_as_of="2026-11-02T11:59:00Z", sell="62400", th_as_of="2026-11-02T08:59:00Z", updated="2026-11-02T11:59:11Z"),
        market(spot="3901.81", spot_as_of="2026-11-02T11:59:00Z", sell="62400", th_as_of="2026-11-02T08:59:00Z", updated="2026-11-02T12:02:00Z"),
        {"updated_at": "2026-11-02T12:30:00Z", "items": []},                                   # unusable version
        market(spot="3950", spot_as_of="2026-11-02T23:19:00Z", sell="62700", th_as_of="2026-11-03T04:38:00Z", updated="2026-11-03T05:10:22Z"),
    ]
    h = backfill.history_from_markets(list(reversed(versions)))        # order of input does not matter
    assert [p["spot"] for p in h["points"]] == [3903.12, 3901.81, 3950]
    assert [p["time"] for p in h["points"]] == ["2026-11-02T08:05:00Z", "2026-11-02T11:59:11Z", "2026-11-03T05:10:22Z"]
    assert h["updated_at"] == "2026-11-03T05:10:22Z" and update.validate_doc(update.HISTORY, h) == []


def test_backfill_of_nothing_is_an_empty_valid_doc():
    h = backfill.history_from_markets([], now=NOW)
    assert h == {"updated_at": "2026-11-02T13:00:00Z", "points": []} and update.validate_doc(update.HISTORY, h) == []
