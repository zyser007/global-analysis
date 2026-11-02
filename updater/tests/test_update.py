"""Unit tests for updater/update.py - no network, no API key.

Fake response objects stand in for the SDK's BetaMessage; one test drives the real SDK
against an in-process mock transport to check the request it builds and the stream parsing.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import pathlib
import shutil
import sys
from types import SimpleNamespace as NS

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT / "updater"))
import update  # noqa: E402

NOW = dt.datetime(2026, 11, 2, 13, 0, 0, tzinfo=dt.timezone.utc)
SEED = HERE / "fixtures" / "data"   # frozen copy of the live4 seed (08:05Z), independent of bot commits


# ----------------------------------------------------------------- fixtures / fakes
@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    shutil.copytree(SEED, d)
    return d


@pytest.fixture()
def cost_log(tmp_path):
    return tmp_path / "cost-log.csv"


@pytest.fixture(autouse=True)
def _no_real_cost_log(tmp_path, monkeypatch):
    monkeypatch.setattr(update, "COST_LOG", tmp_path / "real-cost-log-guard.csv")


def seed(name):
    return json.loads((SEED / f"{name}.json").read_text(encoding="utf-8"))


def usage(inp=1000, out=200, cw=0, cr=0, searches=0):
    return NS(input_tokens=inp, output_tokens=out, cache_creation_input_tokens=cw, cache_read_input_tokens=cr,
              server_tool_use=NS(web_search_requests=searches, web_fetch_requests=0))


def resp(content, stop="tool_use", u=None, model="claude-sonnet-5-5"):
    return NS(content=content, stop_reason=stop, usage=u or usage(), model=model, stop_details=None)


def submit_block(name, data):
    return NS(type="tool_use", id="toolu_1", name=name, input=data)


def market_input(scale=1.0, note="ราคาระหว่างวัน"):
    items = {}
    for it in seed("market")["items"]:
        v = float(it["value"]) * scale
        items[it["key"]] = {"value": f"{v:.2f}", "change_th": "+0.1% วันนี้", "trend": "up",
                            "as_of": "2026-11-02T12:30:00Z", "source": "https://example.com/" + it["key"]}
    return {"note_th": note, "items": items}


def headlines_input(n=14):
    ids = ["iran_us_israel_war", "ukraine_russia", "economy", "world", "thailand", "gaza_israel", "sudan_civil_war"]
    return [{"conflict_id": ids[i % len(ids)], "title_th": f"ข่าวทดสอบลำดับ {i}", "time": f"2026-11-02T{12 - i % 12:02d}:00:00Z",
             "source": f"https://example.com/news/{i}", "source_name": "Example"} for i in range(n)]


class FakeStream:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.r


class FakeClient:
    """client.beta.messages.stream(...) -> context manager yielding queued responses; records kwargs."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kw):
        self.calls.append({**kw, "messages": list(kw["messages"])})  # snapshot: the caller appends later
        return FakeStream(self.responses.pop(0))


# ----------------------------------------------------------------- validation + sanity
def test_seed_files_pass_dry_run(capsys):
    assert update.main(["--dry-run"]) == 0                       # the live site/data files
    assert update.dry_run(SEED) == 0                             # the frozen fixture
    assert "dry run: OK" in capsys.readouterr().out


def test_dry_run_flags_broken_files(data_dir, capsys):
    m = seed("market"); m["items"][0]["value"] = "abc"
    (data_dir / "market.json").write_text(json.dumps(m), encoding="utf-8")
    assert update.dry_run(data_dir) == 1
    assert "INVALID" in capsys.readouterr().out


@pytest.mark.parametrize("raw,expected", [("3,903.12", 3903.12), ("−2.5", -2.5), (" 62500 ", 62500.0), ("4.93", 4.93),
                                          ("abc", None), ("1.2.3", None), ("", None), (None, None), (True, None), (7, 7.0)])
def test_parse_number(raw, expected):
    assert update.parse_number(raw) == expected


def test_schemas_cover_world_data_conflicts():
    world = json.loads((ROOT / "data" / "world-data.json").read_text(encoding="utf-8"))
    allowed = set(update.allowed_conflict_ids())
    assert {c["id"] for c in world["conflicts"]} <= allowed
    assert {"economy", "world", "thailand"} <= allowed
    assert {i["conflict_id"] for i in seed("headlines")["items"]} <= allowed


def test_no_raw_double_quotes_in_thai_text():
    assert update.clean_th('ทรัมป์ "เตือน" อิหร่าน') == "ทรัมป์ “เตือน” อิหร่าน"
    doc = seed("status"); doc["message_th"] = 'มี "อัญประกาศ"'
    assert update.validate_doc("status", doc)  # the schema rejects raw quotes


def test_sanity_accepts_small_moves_and_keeps_label_unit():
    items, notes = update.sanity_market(seed("market"), market_input(1.02)["items"])
    assert notes == []
    prev = {i["key"]: i for i in seed("market")["items"]}
    for it in items:
        assert it["label_th"] == prev[it["key"]]["label_th"] and it["unit"] == prev[it["key"]]["unit"]
        assert it["as_of"] == "2026-11-02T12:30:00Z"
    assert [i["key"] for i in items] == [i["key"] for i in seed("market")["items"]]


def test_sanity_rejects_moves_over_15_percent():
    sub = market_input(1.0)["items"]
    sub["gold"]["value"] = "4600"          # +17.9 % from 3903.12
    sub["btc"]["value"] = "65000"          # -16.7 % from 78022
    sub["wti"]["value"] = "113.0"          # +12.1 % -> accepted
    items, notes = update.sanity_market(seed("market"), sub)
    by = {i["key"]: i for i in items}
    prev = {i["key"]: i for i in seed("market")["items"]}
    assert by["gold"]["value"] == prev["gold"]["value"] and by["gold"]["as_of"] == prev["gold"]["as_of"]
    assert by["gold"]["change_th"].startswith(update.STALE_PREFIX) and "+18%" in by["gold"]["change_th"]
    assert by["btc"]["value"] == prev["btc"]["value"] and "−" not in by["btc"]["change_th"] and "-17%" in by["btc"]["change_th"]
    assert by["wti"]["value"] == "113.0"
    assert sorted(n.split(":")[0] for n in notes) == ["btc", "gold"]


def test_sanity_rejects_non_numeric_and_missing():
    sub = market_input()["items"]
    sub["set"]["value"] = "n/a"
    del sub["nikkei"]
    items, notes = update.sanity_market(seed("market"), sub)
    by = {i["key"]: i for i in items}
    assert by["set"]["value"] == seed("market")["items"][11]["value"]
    assert by["set"]["change_th"].startswith(update.STALE_PREFIX)
    assert by["nikkei"]["change_th"].startswith(update.STALE_PREFIX)
    assert len(notes) == 2


def test_values_are_normalised():
    sub = market_input()["items"]
    sub["gold_th"]["value"] = "62,550"
    items, _ = update.sanity_market(seed("market"), sub)
    assert {i["key"]: i for i in items}["gold_th"]["value"] == "62550"


def test_headlines_count_rules():
    h = update.build_headlines(headlines_input(18), NOW)
    assert len(h["items"]) == 16 and [i["id"] for i in h["items"]][:3] == ["h1", "h2", "h3"]
    assert h["items"][0]["time"] >= h["items"][-1]["time"]
    with pytest.raises(update.UpdateError):
        update.build_headlines(headlines_input(11), NOW)
    bad = headlines_input(14); bad[0]["conflict_id"] = "atlantis"
    assert update.build_headlines(bad, NOW)["items"]  # unknown ids fall back to "world"
    assert all(i["conflict_id"] in update.allowed_conflict_ids() for i in update.build_headlines(bad, NOW)["items"])


# ----------------------------------------------------------------- cost
def test_cost_calculation():
    u = update.Usage()
    u.add(resp([], u=usage(inp=50_000, out=4_000, cw=3_000, cr=10_000, searches=6)))
    u.add(resp([], u=usage(inp=10_000, out=1_000, cw=0, cr=3_000, searches=0)))
    # 60k*2 + 5k*10 + 3k*2.5 + 13k*0.10 per MTok + 6 searches * $0.01
    expected = 60_000 * 2 / 1e6 + 5_000 * 10 / 1e6 + 3_000 * 2.5 / 1e6 + 13_000 * 0.10 / 1e6 + 6 * 0.01
    assert u.cost_usd() == pytest.approx(expected)
    assert (u.requests, u.web_searches, u.input_tokens) == (2, 6, 60_000)


def test_cost_log_csv_and_step_summary(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    log = tmp_path / "log.csv"
    u = update.Usage(); u.add(resp([], u=usage(inp=1_000_000, out=0, searches=0)))
    update.log_cost("prices", True, u, "", NOW, log)
    update.log_cost("full", False, u, "boom", NOW, log)
    rows = list(csv.DictReader(log.open(encoding="utf-8")))
    assert [r["mode"] for r in rows] == ["prices", "full"] and rows[0]["cost_usd"] == "2.0000" and rows[1]["ok"] == "no"
    assert "$2.0000" in summary.read_text(encoding="utf-8")
    assert "estimated cost: $2.0000" in capsys.readouterr().out


# ----------------------------------------------------------------- end to end with a fake client
def test_prices_run_writes_valid_files(data_dir, cost_log):
    old_headlines = (data_dir / "headlines.json").read_bytes()
    client = FakeClient([resp([NS(type="server_tool_use", name="web_search", id="srv1", input={"query": "gold"}),
                               submit_block("submit_prices", {"market": market_input(1.01)})],
                              u=usage(inp=40_000, out=3_000, cw=4_000, searches=5))])
    assert update.run("prices", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    m = json.loads((data_dir / "market.json").read_text(encoding="utf-8"))
    s = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
    assert update.validate_doc("market", m) == [] and update.validate_doc("status", s) == []
    assert m["updated_at"] == "2026-11-02T13:00:00Z" and s["ok"] is True and s["run_count"] == seed("status")["run_count"] + 1
    assert "20:00 น." in s["message_th"] and "2569" in s["message_th"]
    assert (data_dir / "headlines.json").read_bytes() == old_headlines
    assert not list(data_dir.glob("*.tmp"))
    # request shape
    kw = client.calls[0]
    assert kw["model"] == "claude-sonnet-5-5" and kw["output_config"] == {"effort": "medium"}
    assert kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]
    ws = [t for t in kw["tools"] if t.get("type") == "web_search_20260209"][0]
    assert ws["max_uses"] == 6
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["system"][0]["text"] == update.system_prompt() and "13:00" not in kw["system"][0]["text"]  # cached prefix is stable
    assert '"brent"' in kw["messages"][0]["content"][0]["text"]   # previous file passed as input
    row = list(csv.DictReader(cost_log.open(encoding="utf-8")))[0]
    assert row["ok"] == "yes" and row["web_searches"] == "5"


def test_full_run_writes_all_three(data_dir, cost_log):
    client = FakeClient([resp([submit_block("submit_full", {"market": market_input(0.99), "headlines": headlines_input(14),
                                                            "status_message_th": 'น้ำมันลง "เล็กน้อย" ข่าวอิหร่านเด่น'})],
                              u=usage(searches=17))])
    assert update.run("full", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    h = json.loads((data_dir / "headlines.json").read_text(encoding="utf-8"))
    s = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
    assert len(h["items"]) == 14 and update.validate_doc("headlines", h) == []
    assert '"' not in s["message_th"] and "“เล็กน้อย”" in s["message_th"]
    assert [t for t in client.calls[0]["tools"] if t.get("name") == "web_search"][0]["max_uses"] == 20


def test_pause_turn_is_resumed_append_only(data_dir, cost_log):
    paused = [NS(type="server_tool_use", name="web_search", id="srv1", input={"query": "brent"})]
    client = FakeClient([resp(paused, stop="pause_turn", u=usage(searches=3)),
                         resp([submit_block("submit_prices", {"market": market_input()})], u=usage(searches=2))])
    assert update.run("prices", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    assert len(client.calls) == 2
    second = client.calls[1]["messages"]
    assert second[0] == client.calls[0]["messages"][0] and second[1] == {"role": "assistant", "content": paused}
    assert client.calls[1]["tools"] == client.calls[0]["tools"]
    assert list(csv.DictReader(cost_log.open(encoding="utf-8")))[0]["web_searches"] == "5"


def test_missing_submit_gets_one_nudge_then_fails(data_dir, cost_log):
    text = [NS(type="text", text="done")]
    client = FakeClient([resp(text, stop="end_turn"), resp(text, stop="end_turn")])
    assert update.run("prices", data_dir, client=client, cost_log=cost_log, now=NOW) == 1
    assert len(client.calls) == 2 and client.calls[1]["messages"][-1]["role"] == "user"


@pytest.mark.parametrize("bad", [
    resp([], stop="refusal"),
    resp([NS(type="text", text="...")], stop="max_tokens"),
])
def test_failures_keep_old_files_and_flag_status(data_dir, cost_log, bad):
    before = {n: (data_dir / f"{n}.json").read_bytes() for n in ("market", "headlines")}
    assert update.run("full", data_dir, client=FakeClient([bad]), cost_log=cost_log, now=NOW) == 1
    for n, b in before.items():
        assert (data_dir / f"{n}.json").read_bytes() == b
    s = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
    assert s["ok"] is False and s["message_th"].startswith("อัปเดตอัตโนมัติไม่สำเร็จ") and update.validate_doc("status", s) == []
    assert s["run_count"] == seed("status")["run_count"] + 1
    assert list(csv.DictReader(cost_log.open(encoding="utf-8")))[0]["ok"] == "no"


def test_invalid_output_is_never_written(data_dir, cost_log):
    before = (data_dir / "market.json").read_bytes()
    client = FakeClient([resp([submit_block("submit_full", {"market": market_input(), "headlines": headlines_input(9),
                                                            "status_message_th": "x"})], u=usage(searches=6))])
    assert update.run("full", data_dir, client=client, cost_log=cost_log, now=NOW) == 1
    assert (data_dir / "market.json").read_bytes() == before     # market was fine, but nothing partial is written
    assert json.loads((data_dir / "status.json").read_text(encoding="utf-8"))["ok"] is False


def test_missing_key_exits_cleanly(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert update.main(["prices"]) == 2
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().err


def test_key_is_never_printed(data_dir, cost_log, monkeypatch, capsys):
    secret = "fake-key-TESTSECRET-do-not-print"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    monkeypatch.setattr(update, "make_client", lambda key: FakeClient([resp([], stop="refusal")]))
    assert update.main(["prices", "--data-dir", str(data_dir)]) == 1
    out = capsys.readouterr()
    assert secret not in out.out + out.err
    assert secret not in (data_dir / "status.json").read_text(encoding="utf-8")


# ----------------------------------------------------------------- real SDK, mock transport
def test_real_sdk_request_and_stream_parsing(data_dir, cost_log):
    """Drive anthropic.Anthropic against a mock transport: checks the wire request (beta header,
    fallbacks, strict tool, cache_control) and that the SDK's stream accumulator yields the tool input."""
    anthropic = pytest.importorskip("anthropic")
    import httpx2

    payload = json.dumps({"market": market_input(1.005)}, ensure_ascii=False)
    seen = {}

    def sse(events):
        return "".join(f"event: {e['type']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)

    def handler(request):
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        body = sse([
            {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
                                                  "content": [], "stop_reason": None, "stop_sequence": None,
                                                  "usage": {"input_tokens": 12000, "output_tokens": 1, "cache_creation_input_tokens": 3000,
                                                            "cache_read_input_tokens": 0}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "submit_prices", "input": {}}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": payload[:40]}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": payload[40:]}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "tool_use", "stop_sequence": None},
             "usage": {"output_tokens": 2500, "server_tool_use": {"web_search_requests": 4}}},
            {"type": "message_stop"},
        ])
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode("utf-8"))

    client = anthropic.Anthropic(api_key="fake-test-key", base_url="http://mock.invalid", max_retries=0,
                                 http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)))
    assert update.run("prices", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    b, h = seen["body"], seen["headers"]
    assert "server-side-fallback-2026-07-01" in h.get("anthropic-beta", "")
    assert b["model"] == "claude-sonnet-5-5" and b["fallbacks"] == "default" and b["stream"] is True
    assert b["thinking"] == {"type": "adaptive"} and b["output_config"] == {"effort": "medium"}
    assert "temperature" not in b and "tool_choice" not in b
    sub = [t for t in b["tools"] if t.get("name") == "submit_prices"][0]
    assert sub["strict"] is False and sub["input_schema"]["additionalProperties"] is False
    assert b["system"][0]["cache_control"]["type"] == "ephemeral"
    m = json.loads((data_dir / "market.json").read_text(encoding="utf-8"))
    assert {i["key"]: i for i in m["items"]}["brent"]["as_of"] == "2026-11-02T12:30:00Z"
    row = list(csv.DictReader(cost_log.open(encoding="utf-8")))[0]
    assert row["web_searches"] == "4" and row["output_tokens"] == "2500"



# ----------------------------------------------------------------- search plan, fetch tool, changed count
def test_tools_include_fresh_capped_web_fetch():
    for mode in ("prices", "full"):
        tools = update.tools_for(mode)
        fetch = [t for t in tools if t.get("name") == "web_fetch"][0]
        assert fetch["type"].startswith("web_fetch_2026") and fetch["use_cache"] is False
        assert fetch["max_uses"] == update.MAX_FETCHES[mode] and fetch["max_content_tokens"] == update.FETCH_MAX_CONTENT_TOKENS
        assert [t.get("name") for t in tools] == ["web_search", "web_fetch", "submit_" + mode]
    assert update.MAX_FETCHES == {"prices": 5, "full": 8} and update.MAX_SEARCHES == {"prices": 6, "full": 20}


def test_user_message_carries_sessions_and_fetchable_quote_pages():
    prev = {k: seed(k) for k in update.DOCS}
    msg = update.user_message("prices", prev, dt.datetime(2026, 11, 2, 11, 51, tzinfo=dt.timezone.utc))
    assert "Bangkok Mon 18:51" in msg and "New York Mon 06:51" in msg
    assert "SET (Bangkok 10:00-12:30, 14:30-16:30): closed for the day" in msg
    assert "S&P 500, Nasdaq 100, VIX cash session (New York 09:30-16:00): not open yet today" in msg
    assert "gold spot, Brent, WTI, DXY, USD/THB, US 10-year yield: trading now" in msg
    for url, _ in update.QUOTE_PAGES:      # web_fetch can only open URLs that appear in the conversation
        assert url in msg
    assert "web_search at most 6 searches; web_fetch at most 5 pages" in msg
    sp = update.system_prompt()
    assert "How to find the quotes" in sp and "later than the previous item's as_of" in sp


@pytest.mark.parametrize("when,expect", [
    ("2026-11-03T03:30:00Z", ["SET (Bangkok 10:00-12:30, 14:30-16:30): OPEN now", "Nikkei 225 (Tokyo 09:00-11:30, 12:30-15:30): OPEN now"]),
    ("2026-11-02T15:00:00Z", ["VIX cash session (New York 09:30-16:00): OPEN now"]),
    ("2026-11-07T03:00:00Z", ["SET (Bangkok 10:00-12:30, 14:30-16:30): closed (weekend)", "US 10-year yield: not trading now"]),
])
def test_market_sessions(when, expect):
    lines = "\n".join(update.market_sessions(dt.datetime.fromisoformat(when.replace("Z", "+00:00"))))
    for e in expect:
        assert e in lines


def test_older_as_of_never_replaces_newer():
    sub = market_input()["items"]
    sub["gold"]["as_of"] = "2026-11-01T00:00:00Z"
    sub["gold"]["value"] = "3900"
    items, notes = update.sanity_market(seed("market"), sub)
    gold = {i["key"]: i for i in items}["gold"]
    assert gold == {i["key"]: i for i in seed("market")["items"]}["gold"]
    assert any(n.startswith("gold:") and "older" in n for n in notes)


def test_status_reports_the_real_number_of_changed_items(data_dir, cost_log, capsys):
    m = market_input(1.0)
    prev = {i["key"]: i for i in seed("market")["items"]}
    for k in ("set", "nikkei", "spx", "ndx", "vix"):        # these five come back exactly as before
        m["items"][k] = {f: prev[k][f] for f in ("value", "change_th", "trend", "as_of", "source")}
    client = FakeClient([resp([submit_block("submit_prices", {"market": m})], u=usage(searches=6))])
    assert update.run("prices", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    s = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
    assert "ราคาเปลี่ยน 8/13 รายการ" in s["message_th"] and "13/13" not in s["message_th"]
    row = list(csv.DictReader(cost_log.open(encoding="utf-8")))[0]
    assert row["items_changed"] == "8"
    assert "items changed: 8/13" in capsys.readouterr().out


def test_nothing_new_is_ok_but_says_so(data_dir, cost_log):
    prev = {i["key"]: i for i in seed("market")["items"]}
    same = {"note_th": "ไม่มีข้อมูลใหม่", "items": {k: {f: v[f] for f in ("value", "change_th", "trend", "as_of", "source")} for k, v in prev.items()}}
    client = FakeClient([resp([submit_block("submit_prices", {"market": same})])])
    assert update.run("prices", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    s = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
    assert s["ok"] is True and "ไม่พบราคาใหม่กว่ารอบก่อน (เปลี่ยน 0/13 รายการ)" in s["message_th"]


def test_usage_counts_fetches_and_migrates_old_csv(tmp_path):
    log = tmp_path / "old.csv"
    log.write_text("time_utc,mode,ok,model,requests,input_tokens,output_tokens,cache_write_tokens,cache_read_tokens,web_searches,cost_usd,note\n"
                   "2026-11-02T11:51:22Z,prices,yes,claude-sonnet-5-5,1,12,2449,19752,62023,2,0.1001,\n", encoding="utf-8")
    u = update.Usage()
    u.add(NS(usage=NS(input_tokens=1, output_tokens=1, cache_creation_input_tokens=0, cache_read_input_tokens=0,
                      server_tool_use=NS(web_search_requests=2, web_fetch_requests=3)), stop_reason="tool_use", model="m"))
    assert (u.web_searches, u.web_fetches) == (2, 3)
    assert u.cost_usd() == pytest.approx(2 / 1e6 * 1 + 10 / 1e6 + 0.02)    # fetches add no fee
    update.log_cost("prices", True, u, "", NOW, log, items_changed=4)
    rows = list(csv.DictReader(log.open(encoding="utf-8")))
    assert list(rows[0].keys()) == update.CSV_FIELDS
    assert rows[0]["cost_usd"] == "0.1001" and rows[0]["web_fetches"] == ""
    assert rows[1]["web_fetches"] == "3" and rows[1]["items_changed"] == "4"



def test_trace_lines_summarise_server_tools():
    content = [
        NS(type="server_tool_use", name="web_search", input={"query": "gold price today"}),
        NS(type="web_search_tool_result", content=[NS(title="Gold rises", page_age="2 hours ago"), NS(title="Oil", page_age=None)]),
        NS(type="web_search_tool_result", content=NS(type="web_search_tool_result_error", error_code="max_uses_exceeded")),
        NS(type="server_tool_use", name="web_fetch", input={"url": "https://tradingeconomics.com/commodities"}),
        NS(type="web_fetch_tool_result", content=NS(type="web_fetch_result", url="https://tradingeconomics.com/commodities",
                                                    retrieved_at="2026-11-02T12:00:00Z", content=NS(source=NS(data="x" * 50)))),
        NS(type="web_fetch_tool_result", content=NS(type="web_fetch_tool_result_error", error_code="url_not_accessible")),
        NS(type="bash_code_execution_tool_result", content=NS(return_code=0, stdout="Brent 109.8\nGold 3911")),
        NS(type="text", text="Found the quotes."),
        submit_block("submit_prices", {}),
    ]
    lines = update.trace_lines(content)
    assert lines[0] == 'web_search {"query": "gold price today"}'
    assert "2 results: Gold rises [2 hours ago]; Oil [-]" in lines[1]
    assert lines[2].endswith("error max_uses_exceeded") and lines[5].endswith("error url_not_accessible")
    assert "retrieved 2026-11-02T12:00:00Z (50 chars)" in lines[4]
    assert "stdout: Brent 109.8 Gold 3911" in lines[6] and lines[-1] == "submit_prices (submit)"



# ----------------------------------------------------------------- non-strict submit tool: repair, validate, retry
def _as_file_items(m):
    return [{"key": k, "label_th": "x", "unit": "y", **v} for k, v in m["items"].items()]


@pytest.mark.parametrize("shape", ["list_items", "string_market", "flat_market", "top_level", "numeric_values"])
def test_normalize_submission_repairs_known_shapes(shape):
    m = market_input()
    if shape == "list_items":
        data = {"market": {"note_th": "n", "items": _as_file_items(m)}}
    elif shape == "string_market":
        data = {"market": json.dumps(m, ensure_ascii=False)}
    elif shape == "flat_market":
        data = {"market": {"note_th": "n", **m["items"]}}
    elif shape == "top_level":
        data = {"note_th": "n", "items": m["items"]}
    else:
        data = {"market": {"note_th": "n", "items": {k: {**v, "value": float(v["value"])} for k, v in m["items"].items()}}}
    fixed = update.normalize_submission("prices", data)
    assert update.submission_errors("prices", fixed) == []
    assert set(fixed["market"]["items"]) == set(update.MARKET_KEYS)


def test_full_submission_with_string_headlines_is_repaired():
    data = {"market": market_input(), "headlines": json.dumps(headlines_input(13), ensure_ascii=False), "status_message_th": "x"}
    assert update.submission_errors("full", update.normalize_submission("full", data)) == []


def test_invalid_submit_gets_one_is_error_retry(data_dir, cost_log):
    bad = {"market": {"note_th": "n", "items": {"brent": {"value": "1"}}}}           # 12 keys missing, fields missing
    first = resp([submit_block("submit_prices", bad)])
    second = resp([submit_block("submit_prices", {"market": market_input()})])
    client = FakeClient([first, second])
    assert update.run("prices", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    retry = client.calls[1]["messages"]
    assert retry[-2] == {"role": "assistant", "content": first.content}
    tr = retry[-1]["content"][0]
    assert tr["type"] == "tool_result" and tr["is_error"] is True and tr["tool_use_id"] == "toolu_1" and "wti" in tr["content"]
    assert client.calls[1]["tools"] == client.calls[0]["tools"]


def test_still_invalid_after_retry_fails_and_keeps_files(data_dir, cost_log):
    before = (data_dir / "market.json").read_bytes()
    bad = {"market": {"note_th": "n", "items": {}}}
    client = FakeClient([resp([submit_block("submit_prices", bad)]), resp([submit_block("submit_prices", bad)])])
    assert update.run("prices", data_dir, client=client, cost_log=cost_log, now=NOW) == 1
    assert (data_dir / "market.json").read_bytes() == before
    assert json.loads((data_dir / "status.json").read_text(encoding="utf-8"))["ok"] is False


def test_many_missing_items_never_overwrite_data():
    with pytest.raises(update.UpdateError):
        update.build_docs("prices", {k: seed(k) for k in update.DOCS}, {"market": {"note_th": "n", "items": {}}}, NOW)



# ----------------------------------------------------------------- full runs must research the news
def test_full_without_news_searches_is_sent_back_once(data_dir, cost_log):
    sub = {"market": market_input(), "headlines": headlines_input(14), "status_message_th": "สรุป"}
    first = resp([submit_block("submit_full", sub)], u=usage(searches=1))
    second = resp([submit_block("submit_full", sub)], u=usage(searches=5))
    client = FakeClient([first, second])
    assert update.run("full", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    tr = client.calls[1]["messages"][-1]["content"][0]
    assert tr["is_error"] is True and "2026-11-02T07:45:00Z" in tr["content"] and "Iran / Hormuz" in tr["content"]
    s = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
    assert "ข่าวใหม่ 14 จาก 14 ข่าว" in s["message_th"]
    assert json.loads((data_dir / "headlines.json").read_text(encoding="utf-8"))["updated_at"] == "2026-11-02T13:00:00Z"


def test_full_that_never_searches_keeps_old_headlines(data_dir, cost_log):
    before = (data_dir / "headlines.json").read_bytes()
    sub = {"market": market_input(), "headlines": headlines_input(14), "status_message_th": "สรุป"}
    client = FakeClient([resp([submit_block("submit_full", sub)]), resp([submit_block("submit_full", sub)])])
    assert update.run("full", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    assert (data_dir / "headlines.json").read_bytes() == before
    s = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
    assert s["ok"] is True and "ข่าวไม่ได้อัปเดตรอบนี้" in s["message_th"]


def test_resubmitted_old_headlines_count_as_nothing_new(data_dir, cost_log):
    before = (data_dir / "headlines.json").read_bytes()
    old = [{k: v for k, v in i.items() if k != "id"} for i in seed("headlines")["items"]]
    client = FakeClient([resp([submit_block("submit_full", {"market": market_input(), "headlines": old, "status_message_th": "x"})],
                              u=usage(searches=8))])
    assert update.run("full", data_dir, client=client, cost_log=cost_log, now=NOW) == 0
    assert (data_dir / "headlines.json").read_bytes() == before
    assert "ไม่พบข่าวใหม่ คงชุดเดิม 16 ข่าว" in json.loads((data_dir / "status.json").read_text(encoding="utf-8"))["message_th"]


def test_count_new_headlines_mixes_kept_and_new():
    prev = seed("headlines")
    kept = [{k: v for k, v in i.items() if k != "id"} for i in prev["items"][:5]]
    new = headlines_input(9)          # times 04:00-12:00Z, some after the previous updated_at (08:05Z), all unseen
    assert update.count_new_headlines(prev, kept + new) == 9


def test_full_run_skips_prices_when_they_are_fresh(data_dir, cost_log):
    before = (data_dir / "market.json").read_bytes()
    now = dt.datetime(2026, 11, 2, 8, 35, tzinfo=dt.timezone.utc)      # market.json is 30 min old
    sub = {"headlines": headlines_input(13), "status_message_th": "สรุปข่าว", "market": {"junk": 1}}
    client = FakeClient([resp([submit_block("submit_full", sub)], u=usage(searches=6))])
    assert update.run("full", data_dir, client=client, cost_log=cost_log, now=now) == 0
    kw = client.calls[0]
    submit = [t for t in kw["tools"] if t.get("name") == "submit_full"][0]
    assert "market" not in submit["input_schema"]["properties"] and "market" not in submit["input_schema"]["required"]
    assert "updated 30 minutes ago" in kw["messages"][0]["content"][0]["text"]
    assert (data_dir / "market.json").read_bytes() == before
    s = json.loads((data_dir / "status.json").read_text(encoding="utf-8"))
    assert "ราคาคงชุดรอบราคาเมื่อ 30 นาทีก่อน" in s["message_th"]


def test_full_run_with_old_prices_still_follows_the_price_plan(data_dir, cost_log):
    client = FakeClient([resp([submit_block("submit_full", {"market": market_input(), "headlines": headlines_input(12),
                                                            "status_message_th": "x"})], u=usage(searches=9))])
    assert update.run("full", data_dir, client=client, cost_log=cost_log, now=NOW) == 0      # 4 h 55 min old
    submit = [t for t in client.calls[0]["tools"] if t.get("name") == "submit_full"][0]
    assert "market" in submit["input_schema"]["required"]
    assert "Follow the price plan" in client.calls[0]["messages"][0]["content"][0]["text"]


def test_prompt_asks_for_article_time_and_major_outlets():
    sp = update.system_prompt()
    assert "publication time of the source article" in sp and "Reuters, AP, AFP, Bloomberg" in sp and "Kyiv Independent" in sp
    assert "at most about 5 older items" in sp and "at least 4 searches" in sp



def test_kept_headlines_are_copied_verbatim():
    prev = seed("headlines")
    kept = dict(prev["items"][0]); kept.pop("id")
    retyped = {**kept, "title_th": kept["title_th"][:-3] + "พิมพ์ผิด", "time": "2026-11-02T12:00:00Z", "source_name": "x"}
    h = update.build_headlines([retyped] + headlines_input(12), NOW, prev)
    row = [i for i in h["items"] if i["source"] == kept["source"]][0]
    assert {k: row[k] for k in kept} == kept
