"""Unit tests for updater/disasters.py - no network.

The feed samples in fixtures/feeds/ are real responses saved on 2 Nov 2026 (GDACS event search,
USGS M4.5+ week feed trimmed to M5+, and three USGS month-feed records for the de-dup case).
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
import disasters as D  # noqa: E402
import update  # noqa: E402

FEEDS = HERE / "fixtures" / "feeds"
NOW = dt.datetime(2026, 11, 2, 16, 40, 0, tzinfo=dt.timezone.utc)


def sample(name):
    return json.loads((FEEDS / name).read_text(encoding="utf-8"))


def body(obj) -> bytes:
    return json.dumps(obj).encode("utf-8")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tests must not touch the network")
    monkeypatch.setattr(D.urllib.request, "urlopen", boom)


class Fetch:
    """Fake fetcher: answers by host; a value may be (status, bytes) or an exception to raise."""

    def __init__(self, gdacs=None, usgs=None):
        self.gdacs = gdacs if gdacs is not None else (200, body(sample("gdacs_search.json")))
        self.usgs = usgs if usgs is not None else (200, body(sample("usgs_4.5_week.json")))
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        v = self.gdacs if "gdacs.org" in url else self.usgs
        if isinstance(v, Exception):
            raise v
        return v


def run_once(tmp_path, fetch, now=NOW):
    rc = D.run(tmp_path, fetch=fetch, now=now)
    path = tmp_path / D.FILE_NAME
    return rc, (json.loads(path.read_text(encoding="utf-8")) if path.exists() else None)


# ----------------------------------------------------------------- parsers (real samples)
def test_gdacs_sample_parses_orange_red_current_events():
    items = D.parse_gdacs(sample("gdacs_search.json"), NOW)
    ids = [i["id"] for i in items]
    # MURASU (red, running), ARNAB (red, ended 28 Oct), China M7.0 (orange, 22 Oct), three droughts to 31 Oct
    assert sorted(ids) == sorted(["gdacs-tc-1001346", "gdacs-tc-1001345", "gdacs-eq-1573141",
                                  "gdacs-dr-1027450", "gdacs-dr-1027449", "gdacs-dr-1018332"])
    assert all(i["alert_level"] in ("orange", "red") and i["source_name"] == "GDACS" for i in items)
    # ended long ago: Panama M7.7 (9 Oct), CHAMPI (to 25 Oct > 7 days), Kanlaon (10 Oct), India flood (to 7 Oct)
    for gone in ("gdacs-eq-1570339", "gdacs-tc-1001338", "gdacs-vo-1000152", "gdacs-fl-1104121"):
        assert gone not in ids
    by = {i["id"]: i for i in items}
    tc = by["gdacs-tc-1001346"]
    assert tc["title_th"] == "พายุหมุนเขตร้อน MURASU-26 ลมสูงสุด 120 กม./ชม. กระทบอินเดีย"
    assert (tc["type"], tc["country"], tc["country_th"], tc["severity_unit"]) == ("cyclone", "India", "อินเดีย", "km/h")
    assert tc["source_url"] == "https://www.gdacs.org/report.aspx?eventid=1001346&episodeid=7&eventtype=TC"
    assert (tc["lat"], tc["lon"], tc["start"]) == (14.7, 80.7, "2026-11-01T00:00:00Z")
    eq = by["gdacs-eq-1573141"]
    assert eq["title_th"] == "แผ่นดินไหวขนาด 7.0 ในจีน" and eq["severity_th"] == "ขนาด 7.0 ลึก 18 กม."
    assert eq["severity_value"] == 7.0 and eq["start"] == "2026-10-22T14:33:40Z"
    dr = by["gdacs-dr-1018332"]
    assert dr["title_th"] == "ภัยแล้งในยุโรป ครอบคลุม 29 ประเทศ"
    assert dr["severity_th"] == "ภัยแล้งด้านการเกษตร พื้นที่ราว 2.0 ล้าน ตร.กม."
    assert dr["country_th"].endswith("และอีก 26 แห่ง") and len(dr["countries"]) == 29


def test_gdacs_types_and_titles_for_every_hazard():
    feats = sample("gdacs_search.json")["features"]
    later = dt.datetime(2026, 10, 10, 12, tzinfo=dt.timezone.utc)   # when Kanlaon / Taal / the India flood were current
    items = {i["id"]: i for i in D.parse_gdacs({"type": "FeatureCollection", "features": feats}, later)}
    assert items["gdacs-vo-1000152"]["title_th"] == "ภูเขาไฟ Kanlaon ปะทุ ในฟิลิปปินส์"
    assert items["gdacs-fl-1104121"]["title_th"] == "น้ำท่วมในอินเดีย"
    assert items["gdacs-tc-1001338"]["country_th"] == "ฟิลิปปินส์ กวม ญี่ปุ่น และอีก 2 แห่ง"
    wf = D._gdacs_item({"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.1, 44.2]}, "properties": {
        "eventtype": "WF", "eventid": 1029628, "alertlevel": "Red", "fromdate": "2026-07-22T00:00:00", "todate": "2026-08-01T00:00:00",
        "datemodified": "2026-08-02T00:00:00", "country": "France", "affectedcountries": [{"countryname": "France"}],
        "severitydata": {"severity": 47910.0, "severitytext": "Red impact for forestfire in 47910 ha", "severityunit": "ha"},
        "name": "Forest fires in France", "eventname": ""}})
    assert wf["title_th"] == "ไฟป่าในฝรั่งเศส พื้นที่ไหม้ราว 47,910 เฮกตาร์" and wf["type"] == "wildfire"


def test_gdacs_no_content_is_an_empty_list_not_a_failure(tmp_path):
    rc, doc = run_once(tmp_path, Fetch(gdacs=(204, b"")))
    assert rc == 0 and doc["ok"] is True
    assert {i["source_name"] for i in doc["items"]} == {"USGS"}


def test_usgs_sample_keeps_significant_quakes_only():
    items = D.parse_usgs(sample("usgs_4.5_week.json"), NOW)
    assert [i["id"] for i in items] == ["usgs-us7000ttxz"]          # M6.4 Easter Island, sig 630
    it = items[0]
    assert it["title_th"] == "แผ่นดินไหวขนาด 6.4 บริเวณเกาะอีสเตอร์"
    assert (it["alert_level"], it["severity_th"], it["country"]) == ("green", "ขนาด 6.4 ลึก 10 กม.", "")
    assert it["source_url"] == "https://earthquake.usgs.gov/earthquakes/eventpage/us7000ttxz"
    assert "_sig" not in it
    # M6.0 Vanuatu (sig 554, PAGER green) is in the feed but not notable
    assert any(f["id"] == "us7000tupl" for f in sample("usgs_4.5_week.json")["features"])


def test_usgs_pager_yellow_counts_and_places_resolve():
    m = sample("usgs_4.5_month_sample.json")
    items = {i["id"]: i for i in D.parse_usgs(m, dt.datetime(2026, 10, 25, tzinfo=dt.timezone.utc))}
    assert items["usgs-us6000u1wn"]["alert_level"] == "yellow"
    assert items["usgs-us6000u1wn"]["title_th"] == "แผ่นดินไหวขนาด 6.1 ในปานามา"
    assert D._usgs_place("10 km NE of Ridgecrest, CA") == ("United States", "สหรัฐฯ")
    assert D._usgs_place("Bonin Islands, Japan region") == ("Japan", "ญี่ปุ่น")
    assert D._usgs_place("central Mid-Atlantic Ridge") == ("", "สันเขากลางมหาสมุทรแอตแลนติก")
    assert D.country_th("Atlantis") == "Atlantis"                    # unknown names stay English
    assert D.country_th("México") == "เม็กซิโก"


def test_quake_in_both_feeds_is_kept_once_with_both_sources():
    when = dt.datetime(2026, 10, 23, tzinfo=dt.timezone.utc)
    g = D.parse_gdacs(sample("gdacs_search.json"), when)
    u = D.parse_usgs(sample("usgs_4.5_month_sample.json"), when)
    gg, rest, merged = D.dedupe(g, u)
    assert merged == 2                                              # China M7.0 (22 Oct), Panama M7.7 (9 Oct)
    assert [x["id"] for x in rest] == ["usgs-us6000u1wn"]           # Panama M6.1 aftershock is a separate event
    china = next(x for x in gg if x["id"] == "gdacs-eq-1573141")
    assert china["alt_source_url"] == "https://earthquake.usgs.gov/earthquakes/eventpage/us6000u43g"
    assert china["alt_source_name"] == "USGS" and china["source_name"] == "GDACS"
    # the higher alert wins
    g2 = [dict(china, alert_level="green")]
    assert D.dedupe(g2, [u[0]])[0][0]["alert_level"] == "orange"
    # a quake 10 minutes apart is not the same event
    assert not D.same_quake(china, dict(u[0], start="2026-10-22T14:45:00Z"))


# ----------------------------------------------------------------- whole run
def test_run_writes_a_valid_sorted_file(tmp_path, capsys):
    fetch = Fetch()
    rc, doc = run_once(tmp_path, fetch)
    assert rc == 0 and D.validate(doc) == []
    assert doc["ok"] is True and doc["message_th"] == "" and doc["updated"] == doc["checked"] == "2026-11-02T16:40:00Z"
    assert [i["alert_level"] for i in doc["items"]] == ["red", "red", "orange", "orange", "orange", "orange", "green"]
    assert doc["items"][0]["id"] == "gdacs-tc-1001346"               # red, newest first
    assert doc["feeds"]["gdacs"]["count"] == 6 and doc["feeds"]["usgs"]["count"] == 1
    assert "alertlevel=orange;red" in fetch.urls[0] and "fromDate=2026-09-18" in fetch.urls[0]
    assert fetch.urls[1] == D.USGS_FEED
    assert "wrote disasters.json: 7 events" in capsys.readouterr().out
    assert D.check(tmp_path) == 0


def test_list_is_capped(tmp_path):
    base = sample("gdacs_search.json")["features"][0]
    feats = []
    for i in range(45):
        f = copy.deepcopy(base)
        f["properties"]["eventid"] = 2000000 + i
        f["properties"]["fromdate"] = f"2026-11-0{1 + i % 2}T{i % 24:02d}:00:00"
        feats.append(f)
    rc, doc = run_once(tmp_path, Fetch(gdacs=(200, body({"type": "FeatureCollection", "features": feats}))))
    assert rc == 0 and len(doc["items"]) == D.MAX_ITEMS == 30


@pytest.mark.parametrize("bad", [
    urllib.error.URLError("timed out"),
    (500, b"server error"),
    (200, b"<html>maintenance</html>"),
    (200, b'{"message": "Eventtype is required."}'),
])
def test_one_feed_failing_keeps_its_old_events_and_refreshes_the_other(tmp_path, bad):
    run_once(tmp_path, Fetch(), now=NOW - dt.timedelta(hours=4))
    # next round: GDACS breaks, USGS has a new significant quake
    usgs = sample("usgs_4.5_week.json")
    new = copy.deepcopy(next(f for f in usgs["features"] if f["id"] == "us7000ttxz"))
    new["id"] = "us7000zzzz"
    new["properties"].update(time=1793630000000, updated=1793630000000, mag=6.6, sig=670)
    usgs["features"].append(new)
    rc, doc = run_once(tmp_path, Fetch(gdacs=bad, usgs=(200, body(usgs))), now=NOW)
    assert rc == 0 and D.validate(doc) == []
    ids = [i["id"] for i in doc["items"]]
    assert "gdacs-tc-1001346" in ids and "usgs-us7000zzzz" in ids
    assert doc["ok"] is False and doc["feeds"]["gdacs"]["ok"] is False and doc["feeds"]["usgs"]["ok"] is True
    assert doc["feeds"]["gdacs"]["fetched"] == "2026-11-02T12:40:00Z" and doc["feeds"]["gdacs"]["error"]
    assert "GDACS" in doc["message_th"] and "ไม่สำเร็จ" in doc["message_th"]
    assert doc["updated"] == "2026-11-02T16:40:00Z"


def test_usgs_failing_keeps_its_old_quake_and_kept_gdacs_ages_out(tmp_path):
    run_once(tmp_path, Fetch(), now=NOW)
    later = NOW + dt.timedelta(days=6)
    rc, doc = run_once(tmp_path, Fetch(gdacs=(204, b""), usgs=(503, b"")), now=later)
    assert rc == 0
    assert [i["id"] for i in doc["items"]] == ["usgs-us7000ttxz"]   # GDACS answered "nothing"; USGS kept
    assert doc["feeds"]["usgs"]["ok"] is False and "USGS" in doc["message_th"]


def test_both_feeds_failing_keeps_the_file_and_exits_1(tmp_path):
    run_once(tmp_path, Fetch(), now=NOW - dt.timedelta(hours=4))
    before = json.loads((tmp_path / D.FILE_NAME).read_text(encoding="utf-8"))
    rc, doc = run_once(tmp_path, Fetch(gdacs=(502, b""), usgs=urllib.error.URLError("dns")), now=NOW)
    assert rc == 1
    assert doc["items"] == before["items"] and doc["updated"] == before["updated"]
    assert doc["checked"] == "2026-11-02T16:40:00Z" and doc["ok"] is False
    assert doc["message_th"] == "โหลดข้อมูลภัยพิบัติไม่สำเร็จทุกแหล่งรอบนี้ แสดงรายการล่าสุดที่ได้รับ"


def test_both_failing_without_a_previous_file_writes_nothing(tmp_path):
    rc, doc = run_once(tmp_path, Fetch(gdacs=(500, b""), usgs=(500, b"")))
    assert rc == 1 and doc is None


def test_mostly_unreadable_feed_counts_as_failed():
    feats = sample("gdacs_search.json")["features"]
    junk = [{"type": "Feature", "properties": {"eventtype": "EQ"}} for _ in range(len(feats) + 1)]
    with pytest.raises(D.FeedError):
        D.parse_gdacs({"type": "FeatureCollection", "features": feats + junk}, NOW)
    with pytest.raises(D.FeedError):
        D.parse_usgs({"type": "Feature"}, NOW)


def test_invalid_previous_file_is_replaced(tmp_path):
    (tmp_path / D.FILE_NAME).write_text('{"items": "nope"}', encoding="utf-8")
    assert D.check(tmp_path) == 1
    rc, doc = run_once(tmp_path, Fetch())
    assert rc == 0 and len(doc["items"]) == 7


# ----------------------------------------------------------------- schema
def test_schema_rejects_bad_documents(tmp_path):
    run_once(tmp_path, Fetch())
    good = json.loads((tmp_path / D.FILE_NAME).read_text(encoding="utf-8"))
    assert D.validate(good) == []
    cases = [
        lambda d: d["items"][0].update(title_th='มี "อัญประกาศ"'),
        lambda d: d["items"][0].update(id="quake-1"),
        lambda d: d["items"][0].update(lat=123.0),
        lambda d: d["items"][0].update(alert_level="purple"),
        lambda d: d["items"][0].update(source_url="http://example.com"),
        lambda d: d["items"].reverse(),                                        # wrong order
        lambda d: d["items"].append(dict(d["items"][-1])),                     # duplicate id
        lambda d: d.pop("feeds"),
        lambda d: d.update(updated="2 Nov 2026"),
    ]
    for i, mutate in enumerate(cases):
        doc = copy.deepcopy(good)
        mutate(doc)
        assert D.validate(doc), f"case {i} should be invalid"
        with pytest.raises(ValueError):
            D.write_doc(tmp_path / "out", doc)
    assert not (tmp_path / "out" / D.FILE_NAME).exists()


def test_published_file_is_valid_and_dry_run_reports_it(capsys):
    assert D.main(["--check"]) == 0
    assert update.main(["--dry-run"]) == 0
    assert "dry run: disasters.json OK" in capsys.readouterr().out


def test_broken_disasters_file_is_reported_but_does_not_block_the_claude_dry_run(tmp_path, capsys):
    import shutil
    d = tmp_path / "data"
    shutil.copytree(HERE / "fixtures" / "data", d)
    assert update.dry_run(d) == 0
    assert "disasters.json not present" in capsys.readouterr().out
    (d / "disasters.json").write_text('{"items": []}', encoding="utf-8")
    assert update.dry_run(d) == 0
    assert "disasters.json INVALID" in capsys.readouterr().out
