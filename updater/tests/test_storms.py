"""Unit tests for updater/storms.py - no network.

The feed samples in fixtures/feeds/ are real responses saved on 5 Nov 2026: the GDACS tropical cyclone list and the
geometry of MURASU-26 (per-time wind radii removed to keep the fixture small; the page does not use them).
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import pathlib
import sys
import urllib.error

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "updater"))
import storms as S  # noqa: E402

FEEDS = HERE / "fixtures" / "feeds"
NOW = dt.datetime(2026, 11, 4, 19, 0, 0, tzinfo=dt.timezone.utc)


def sample(name):
    return json.loads((FEEDS / name).read_text(encoding="utf-8"))


def body(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tests must not touch the network")
    monkeypatch.setattr(S.dz.urllib.request, "urlopen", boom)


class Fetch:
    """Fake fetcher: the list by its path, geometry by event id; a value may be (status, bytes) or an exception."""

    def __init__(self, lst=None, geom=None, geom_for=None):
        self.lst = lst if lst is not None else (200, body(sample("gdacs_tc_list.json")))
        self.geom = geom if geom is not None else (200, body(sample("gdacs_tc_geometry.json")))
        self.geom_for = geom_for or {}
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        v = self.lst
        if "getgeometry" in url:
            v = self.geom
            for k, g in self.geom_for.items():
                if f"eventid={k}" in url:
                    v = g
        if isinstance(v, Exception):
            raise v
        return v


def run_once(tmp_path, fetch, now=NOW):
    rc = S.run(tmp_path, fetch=fetch, now=now)
    path = tmp_path / S.FILE_NAME
    return rc, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else None)


def test_list_keeps_current_storms_and_recently_ended():
    items = S.parse_list(sample("gdacs_tc_list.json"), NOW)
    ids = [i["id"] for i in items]
    # MURASU (red, current) and IN-FA (green, current); VANCE ended 30 Oct, more than two days ago
    assert ids == ["gdacs-tc-1001346", "gdacs-tc-1001343"]
    m = items[0]
    assert (m["name"], m["alert_level"], m["ongoing"], m["agency"], m["wind_kmh"]) == ("MURASU-26", "red", True, "JTWC", 157)
    assert (m["lat"], m["lon"]) == (15.8, 80.2)
    assert m["source_url"].startswith("https://")
    assert m["country_th"] == "อินเดีย"


def test_recently_ended_storm_stays_for_two_days_then_goes():
    doc = sample("gdacs_tc_list.json")
    at = dt.datetime(2026, 10, 31, 12, 0, 0, tzinfo=dt.timezone.utc)
    assert "gdacs-tc-1001341" in [i["id"] for i in S.parse_list(doc, at)]       # VANCE, ended 30 Oct 03:00
    at = dt.datetime(2026, 11, 2, 12, 0, 0, tzinfo=dt.timezone.utc)
    assert "gdacs-tc-1001341" not in [i["id"] for i in S.parse_list(doc, at)]


def test_junk_list_is_a_feed_error():
    with pytest.raises(S.dz.FeedError):
        S.parse_list({"type": "nope"}, NOW)
    bad = {"type": "FeatureCollection", "features": [{"x": 1}, {"y": 2}, {"z": 3}]}
    with pytest.raises(S.dz.FeedError):
        S.parse_list(bad, NOW)


def test_geometry_track_is_ordered_with_forecast_flags():
    g = S.parse_geometry(sample("gdacs_tc_geometry.json"))
    t = g["track"]
    assert t[0] == [11.6, 86.6, 0]                 # the start of the storm comes first although GDACS lists it last
    assert t[-1] == [16.4, 79.9, 1]                # the last forecast point
    assert [p[2] for p in t] == [0, 0, 0, 0, 0, 0, 0, 1, 1, 1]
    assert sorted(g["wind_areas"]) == ["120", "60", "90"]
    for ring in list(g["wind_areas"].values()) + [g["cone"]]:
        assert 3 <= len(ring) <= S.MAX_RING
        assert all(-90 <= a <= 90 and -180 <= b <= 180 for a, b in ring)


def test_geometry_without_a_track_is_a_feed_error():
    with pytest.raises(S.dz.FeedError):
        S.parse_geometry({"type": "FeatureCollection", "features": []})


def test_broken_chain_is_not_presented_as_a_track():
    assert S._chain([((1.0, 1.0), (2.0, 2.0), False), ((5.0, 5.0), (6.0, 6.0), False)]) == []


def test_run_writes_a_small_valid_file(tmp_path):
    f = Fetch()
    rc, doc = run_once(tmp_path, f)
    assert rc == 0 and doc["ok"] is True and doc["message_th"] == ""
    assert [i["name"] for i in doc["items"]] == ["MURASU-26", "IN-FA-26"]
    assert doc["items"][0]["track"][0][:2] == [11.6, 86.6]
    assert S.validate(doc) == []
    assert (tmp_path / S.FILE_NAME).stat().st_size < 50 * 1024
    assert sum("getgeometry" in u for u in f.urls) == 2
    assert all(u.startswith("https://www.gdacs.org/") for u in f.urls)


def test_same_episode_reuses_geometry_and_a_new_episode_fetches_again(tmp_path):
    run_once(tmp_path, Fetch())
    f = Fetch()
    rc, doc = run_once(tmp_path, f, NOW + dt.timedelta(hours=1))
    assert rc == 0 and doc["ok"] is True
    assert sum("getgeometry" in u for u in f.urls) == 0
    assert doc["items"][0]["track"]
    newer = sample("gdacs_tc_list.json")
    for x in newer["features"]:
        if x["properties"]["eventid"] == 1001346:
            x["properties"]["episodeid"] += 1
    f = Fetch(lst=(200, body(newer)))
    run_once(tmp_path, f, NOW + dt.timedelta(hours=2))
    assert sum("getgeometry" in u for u in f.urls) == 1


def test_list_failure_keeps_the_last_good_data(tmp_path):
    _, good = run_once(tmp_path, Fetch())
    later = NOW + dt.timedelta(hours=3)
    rc, doc = run_once(tmp_path, Fetch(lst=urllib.error.URLError("down")), later)
    assert rc == 1 and doc["ok"] is False
    assert doc["items"] == good["items"]
    assert doc["updated"] == good["updated"] and doc["checked"] != good["checked"]
    assert doc["feed"]["ok"] is False and doc["feed"]["fetched"] == good["feed"]["fetched"] and "down" in doc["feed"]["error"]
    assert "ไม่สำเร็จ" in doc["message_th"]
    assert S.validate(doc) == []


def test_list_failure_with_no_previous_file_writes_nothing(tmp_path):
    rc, doc = run_once(tmp_path, Fetch(lst=(500, b"oops")))
    assert rc == 1 and doc is None


def test_storms_too_old_leave_even_while_the_feed_is_down(tmp_path):
    run_once(tmp_path, Fetch())
    rc, doc = run_once(tmp_path, Fetch(lst=(503, b"")), NOW + dt.timedelta(days=20))
    assert rc == 1 and doc["items"] == []


def test_one_geometry_failure_keeps_old_geometry_and_says_so(tmp_path):
    _, good = run_once(tmp_path, Fetch())
    newer = sample("gdacs_tc_list.json")
    for x in newer["features"]:
        x["properties"]["episodeid"] += 1
    rc, doc = run_once(tmp_path, Fetch(lst=(200, body(newer)), geom_for={1001346: urllib.error.URLError("timeout")}), NOW + dt.timedelta(hours=1))
    assert rc == 0 and doc["ok"] is False and "MURASU-26" in doc["message_th"]
    murasu = doc["items"][0]
    assert murasu["track"] == good["items"][0]["track"] and murasu["episode"] == good["items"][0]["episode"] + 1


def test_new_storm_whose_geometry_fails_shows_its_position_only(tmp_path):
    rc, doc = run_once(tmp_path, Fetch(geom_for={1001343: (500, b"")}))
    assert rc == 0 and doc["ok"] is False
    infa = [i for i in doc["items"] if i["name"] == "IN-FA-26"][0]
    assert infa["track"] == [] and infa["lat"] == 25.8


def test_no_events_is_an_empty_ok_file(tmp_path):
    rc, doc = run_once(tmp_path, Fetch(lst=(204, b"")))
    assert rc == 0 and doc["ok"] is True and doc["items"] == []


def test_corrupt_previous_file_is_ignored(tmp_path):
    (tmp_path / S.FILE_NAME).write_text("{not json", encoding="utf-8")
    rc, doc = run_once(tmp_path, Fetch())
    assert rc == 0 and doc["items"]


def test_size_budget_drops_the_least_urgent_detail_first():
    item = S.parse_list(sample("gdacs_tc_list.json"), NOW)[0]
    item.update(S.parse_geometry(sample("gdacs_tc_geometry.json")))
    ring = [[float(i % 80), float(i % 170)] for i in range(S.MAX_RING)]
    item["wind_areas"] = {"60": ring, "90": ring, "120": ring}
    item["cone"] = ring
    item["track"] = [[float(i % 80), float(i % 170), 0] for i in range(120)]
    items = []
    for n in range(8):
        it = copy.deepcopy(item)
        it["id"] = f"gdacs-tc-{n}"
        items.append(it)
    doc = {"updated": "2026-11-04T19:00:00Z", "checked": "2026-11-04T19:00:00Z", "ok": True, "message_th": "",
           "feed": {"ok": True, "fetched": None, "count": 8, "url": "https://www.gdacs.org/x"}, "items": items}
    budget = S.MAX_FILE_BYTES
    try:
        S.MAX_FILE_BYTES = len(S.dumps(doc).encode("utf-8")) - 500
        S.fit_budget(doc)
        assert len(S.dumps(doc).encode("utf-8")) <= S.MAX_FILE_BYTES
        assert doc["items"][-1]["cone"] == [] and doc["items"][0]["cone"]
    finally:
        S.MAX_FILE_BYTES = budget


def test_check_mode(tmp_path, capsys):
    assert S.check(tmp_path) == 1
    run_once(tmp_path, Fetch())
    assert S.check(tmp_path) == 0
    (tmp_path / S.FILE_NAME).write_text('{"ok": true}', encoding="utf-8")
    assert S.check(tmp_path) == 1
