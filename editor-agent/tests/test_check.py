"""Tests for editor-agent/check.py. Hermetic: no network, and nothing is read from the working tree's data or git
state - every test builds a throwaway git repo from the frozen copies in tests/fixtures/, so a run that is
editing data/*.json can never make these tests fail.

Run:  .venv/bin/python -m pytest editor-agent/tests -q
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "fixtures"
spec = importlib.util.spec_from_file_location("editor_check", HERE.parent / "check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)

NOW = "2026-11-05T01:00:00Z"      # 08:00 in Bangkok
RUN = "2026-11-05"
BOT = "41898283+github-actions[bot]@users.noreply.github.com"


def git(root, *args, email="editor@example.com"):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=" + email, "-c", "commit.gpgsign=false", *args],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def load(root, rel):
    return json.loads((root / rel).read_text(encoding="utf-8"))


def save(root, rel, doc):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def build_page(root):
    w = load(root, "data/world-data.json")
    w["gold"] = load(root, "data/gold.json")
    txt = json.dumps(w, ensure_ascii=False, separators=(",", ":"))
    (root / "site").mkdir(exist_ok=True)
    (root / "site" / "index.html").write_text(
        '<!doctype html><html lang="th"><body><script type="application/json" id="world-data">%s</script></body></html>' % txt,
        encoding="utf-8")


def fresh_live(root):
    """Live files that look like a healthy bot run one hour before NOW."""
    t = "2026-11-05T00:00:00Z"
    save(root, "site/data/status.json", {"updated_at": t, "run_count": 1, "ok": True, "message_th": "ok"})
    save(root, "site/data/market.json", {"updated_at": t, "note_th": "x", "items": [{"key": "gold", "value": "3935.0"}]})
    save(root, "site/data/headlines.json", {"updated_at": t, "items": [{"id": "h1", "conflict_id": "ukraine_russia"}]})
    save(root, "site/data/disasters.json", {"updated": t, "ok": True, "message_th": ""})
    (root / "updater").mkdir(exist_ok=True)
    (root / "updater" / "cost-log.csv").write_text(
        "time_utc,mode,ok,model,requests,input_tokens,output_tokens,cache_write_tokens,cache_read_tokens,web_searches,cost_usd,note,web_fetches,items_changed\n"
        "2026-11-04T21:08:44Z,prices,yes,claude-sonnet-5-5,1,20,4259,22764,149806,4,0.1545,,5,1\n", encoding="utf-8")


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    for rel in ("data/world-data.json", "data/gold.json", "updater/schema/headlines.schema.json"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIX / pathlib.Path(rel).name, root / rel)
    build_page(root)
    fresh_live(root)
    (root / "editor-agent" / "runs").mkdir(parents=True)
    (root / "editor-agent" / "runs" / ".gitkeep").write_text("")
    (root / "tools").mkdir()
    (root / "tools" / "build.py").write_text("# build\n")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "base")
    return root


def run(root, *args):
    code, f = check.run(["--now", NOW, *args], root=root)
    return code, f


def msgs(f, level="ERROR"):
    return [i["where"] + ": " + i["what"] for i in f.items if i["level"] == level]


def has(f, text, level="ERROR"):
    return any(text in m for m in msgs(f, level))


def edit_conflict(root, cid="ukraine_russia", url="https://www.reuters.com/world/europe/ukraine-2026-11-04/"):
    w = load(root, "data/world-data.json")
    c = next(c for c in w["conflicts"] if c["id"] == cid)
    c["status_th"] = "รบต่อเนื่อง ปะทะหนักแนวโปครอฟสก์ (4 พ.ย.)"
    if url and url not in c["sources"]:
        c["sources"] = [url] + c["sources"][:3]
    w["meta"]["updated"] = RUN
    w["meta"]["basis_th"] = "3–5 พ.ย. 2569"
    save(root, "data/world-data.json", w)
    return w


def changes_doc(entries, **extra):
    d = {"date": RUN, "changes": entries}
    d.update(extra)
    return d


def entry(section, keys, url="https://www.reuters.com/world/europe/ukraine-2026-11-04/", published="2026-11-04", file="world-data", conf="high"):
    return {"file": file, "section": section, "keys": keys, "summary_th": "อัปเดตสถานะ", "confidence": conf,
            "sources": [{"url": url, "published": published, "publisher": "Reuters"}] if url else []}


def write_run(root, doc, log=True):
    save(root, "editor-agent/runs/%s.changes.json" % RUN, doc)
    if log:
        (root / "editor-agent" / "runs" / ("%s.md" % RUN)).write_text("# สรุป\n", encoding="utf-8")


# ----------------------------------------------------------------------------- helpers
def test_thai_date():
    import datetime as dt
    assert check.thai_date(dt.date(2026, 11, 2)) == "2 พ.ย. 2569"
    assert check.thai_date(dt.date(2027, 1, 31)) == "31 ม.ค. 2570"


def test_month_and_now_detection():
    assert check.has_month("สถานการณ์โลก ปลายตุลาคม 2569")
    assert check.has_month("World in October")
    assert check.has_month("สถานการณ์โลก") is None
    assert check.has_now_word("ข่าวล่าสุด") == "ล่าสุด"
    assert check.has_now_word("latest news") == "latest"
    assert check.undated_now_words("วันนี้ราคาขึ้น") == ["วันนี้"]
    assert check.undated_now_words("วันนี้ (4 พ.ย.) ราคาขึ้น") == []


# ----------------------------------------------------------------------------- current files
def test_fixture_files_pass_schema_and_consistency(repo):
    code, f = run(repo)
    assert not msgs(f), msgs(f)
    assert code == 0


def test_fixture_files_validate_against_schemas():
    assert check.schema_errors("world-data.schema.json", load(FIX, "world-data.json")) == []
    assert check.schema_errors("gold.schema.json", load(FIX, "gold.json")) == []


def test_fixture_is_clean(repo):
    code, f = run(repo, "--all", "--base", "HEAD", "--run-date", RUN)
    assert code == 0, msgs(f)


# ----------------------------------------------------------------------------- schema / consistency
def test_schema_rejects_unknown_field_and_bad_enum(repo):
    w = load(repo, "data/world-data.json")
    w["conflicts"][0]["type"] = "war"
    w["conflicts"][1]["extra"] = 1
    w["economies"][0]["sources"] = ["not a url"]
    save(repo, "data/world-data.json", w)
    code, f = run(repo)
    assert code == 1
    assert has(f, "conflicts/0/type")
    assert has(f, "Additional properties")
    assert has(f, "economies/0/sources/0")


def test_gold_schema_rejects_missing_key(repo):
    g = load(repo, "data/gold.json")
    del g["spot_now"]
    save(repo, "data/gold.json", g)
    code, f = run(repo)
    assert code == 1 and has(f, "'spot_now' is a required property")


def test_title_with_month_or_now_word_fails(repo):
    w = load(repo, "data/world-data.json")
    w["meta"]["title"] = "สถานการณ์โลก ปลายตุลาคม 2569"
    save(repo, "data/world-data.json", w)
    code, f = run(repo)
    assert code == 1 and has(f, "meta.title")
    w["meta"]["title"] = "สถานการณ์โลกล่าสุด"
    save(repo, "data/world-data.json", w)
    code, f = run(repo)
    assert code == 1 and has(f, "undated 'now'")


def test_conflict_name_with_month_fails(repo):
    w = load(repo, "data/world-data.json")
    w["conflicts"][0]["name_th"] = "ยูเครน–รัสเซีย (พ.ย.)"
    save(repo, "data/world-data.json", w)
    code, f = run(repo)
    assert code == 1 and has(f, "conflicts[ukraine_russia]")


def test_meta_dates(repo):
    w = load(repo, "data/world-data.json")
    w["meta"]["updated"] = "2026-11-09"
    save(repo, "data/world-data.json", w)
    _, f = run(repo)
    assert has(f, "in the future")
    w["meta"]["updated"] = "2026-10-01"
    save(repo, "data/world-data.json", w)
    _, f = run(repo)
    assert has(f, "older than the newest indicator")
    assert has(f, "does not end at meta.updated")
    assert has(f, "days old", "WARN")


def test_gold_dates_and_plausibility(repo):
    g = load(repo, "data/gold.json")
    g["updated_th"] = "ข้อมูลรวบรวมถึง 1 พ.ย. 2569"
    g["thai"]["buy"] = g["thai"]["sell"] + 100
    g["levels"]["support"][0]["lo"] = 9999
    g["spot_now"] = 90000
    save(repo, "data/gold.json", g)
    code, f = run(repo)
    assert code == 1
    for t in ("updated_th", "below buy", "lo 9999", "not plausible"):
        assert has(f, t), t


def test_economy_range(repo):
    w = load(repo, "data/world-data.json")
    w["economies"][0]["policy_rate"] = 375.0
    save(repo, "data/world-data.json", w)
    _, f = run(repo)
    assert has(f, "policy_rate = 375.0")


def test_count_change_warns_about_e2e(repo):
    w = load(repo, "data/world-data.json")
    w["indicators"].pop()
    save(repo, "data/world-data.json", w)
    code, f = run(repo)
    assert code == 0 and has(f, "the page layout was designed for 20", "WARN")


# ----------------------------------------------------------------------------- diff vs base
def test_changed_item_without_run_files_fails(repo):
    edit_conflict(repo)
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1
    assert has(f, "Thai change summary for this run is missing")
    assert has(f, "changes.json: file is missing")


def test_changed_item_with_dated_source_passes(repo):
    edit_conflict(repo)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"])]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 0, msgs(f)


def test_changed_item_not_listed_fails(repo):
    edit_conflict(repo)
    w = load(repo, "data/world-data.json")
    w["economies"][0]["note_th"] = "เปลี่ยน"
    save(repo, "data/world-data.json", w)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"])]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "economies[USA]: changed but not listed")


def test_source_must_appear_in_item_sources(repo):
    edit_conflict(repo, url=None)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"], url="https://apnews.com/article/x")]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "none of this run's source URLs")


def test_entry_without_source_fails(repo):
    edit_conflict(repo)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"], url=None)]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "needs at least 1 dated source")


def test_source_dates(repo):
    edit_conflict(repo)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"], published="2026-11-06")]))
    _, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert has(f, "after the run date")
    assert has(f, "older than the newest source")
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"], published="2026-10-20")]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "more than 7 days before the run")
    stale = entry("conflicts", ["ukraine_russia"], published="2026-10-20", conf="low")
    write_run(repo, changes_doc([stale]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "stale_reason_th")
    stale["stale_reason_th"] = "ยังไม่มีรายงานใหม่กว่านี้"
    write_run(repo, changes_doc([stale]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 0, msgs(f)


@pytest.mark.parametrize("url", ["https://cappnotes.substack.com/p/x", "https://www.pomegra.io/a", "https://financefeeds.com/b",
                                 "https://www.babypips.com/news/c", "https://www.kitco.com/charts/gold", "https://x.medium.com/d",
                                 "https://foo.blogspot.com/e", "https://www.hoa.org.uk/f"])
def test_blocked_sources(repo, url):
    edit_conflict(repo, url=url)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"], url=url)]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and (has(f, "blocked source type") or has(f, "chart or quote page"))


def test_source_problem_allows_established_outlets():
    for u in ("https://www.reuters.com/world/x", "https://news.un.org/en/story/2026/11/1", "https://www.kitco.com/news/article/2026-11-04/gold",
              "https://www.bot.or.th/th/news.html"):
        assert check.source_problem(u) is None, u


def test_reviewed_unchanged_must_not_contain_changed_keys(repo):
    edit_conflict(repo)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"])], reviewed_unchanged=["ukraine_russia", "libya"]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "reviewed_unchanged at the same time: ukraine_russia")


def test_meta_updated_must_move_to_run_date(repo):
    edit_conflict(repo)
    w = load(repo, "data/world-data.json")
    w["meta"]["updated"] = "2026-11-04"
    w["meta"]["basis_th"] = "2–4 พ.ย. 2569"
    save(repo, "data/world-data.json", w)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia"], published="2026-11-04")]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "not the run date")


def test_removing_linked_conflict_fails(repo):
    w = load(repo, "data/world-data.json")
    w["conflicts"] = [c for c in w["conflicts"] if c["id"] != "libya"]
    w["meta"]["updated"] = RUN
    w["meta"]["basis_th"] = "5 พ.ย. 2569"
    save(repo, "data/world-data.json", w)
    write_run(repo, changes_doc([], removed=[entry("conflicts", ["libya"], url="https://news.un.org/en/story/2026/11/1")]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "mark it ended instead")


def test_new_crisis_needs_two_publishers_and_a_headline_id(repo):
    w = load(repo, "data/world-data.json")
    new = copy.deepcopy(w["conflicts"][0])
    new.update(id="new_crisis", name_th="วิกฤตใหม่", sources=["https://www.reuters.com/a"], confidence="medium")
    w["conflicts"].append(new)
    w["meta"]["updated"] = RUN
    w["meta"]["basis_th"] = "5 พ.ย. 2569"
    save(repo, "data/world-data.json", w)
    write_run(repo, changes_doc([], added=[entry("conflicts", ["new_crisis"], url="https://www.reuters.com/a")]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "at least 2 dated source")
    two = entry("conflicts", ["new_crisis"], url="https://www.reuters.com/a")
    two["sources"].append({"url": "https://apnews.com/b", "published": "2026-11-04"})
    write_run(repo, changes_doc([], added=[two]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "not in the headlines conflict_id enum")   # needs a code change first
    hs = load(repo, "updater/schema/headlines.schema.json")
    hs["properties"]["items"]["items"]["properties"]["conflict_id"]["enum"].append("new_crisis")
    save(repo, "updater/schema/headlines.schema.json", hs)
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 0, msgs(f)


def test_gold_change_needs_coverage_and_new_as_of(repo):
    g = load(repo, "data/gold.json")
    g["spot_now"] = 3950
    g["from_peak_pct"] = round((3950 / g["peak"] - 1) * 100, 1)
    save(repo, "data/gold.json", g)
    write_run(repo, changes_doc([]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1
    assert has(f, "gold[spot_now]: changed but not listed")
    assert has(f, "was not moved to the run")
    g["as_of"] = "2026-11-05T00:30:00Z"
    g["updated_th"] = "ข้อมูลรวบรวมถึง 5 พ.ย. 2569 07:30 น."
    save(repo, "data/gold.json", g)
    write_run(repo, changes_doc([entry("gold", ["spot_now", "from_peak_pct"], file="gold", url="https://www.kitco.com/gold-price-today")]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 0, msgs(f)


def test_stale_entry_warns(repo):
    edit_conflict(repo)
    write_run(repo, changes_doc([entry("conflicts", ["ukraine_russia", "libya"])]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 0 and has(f, "conflicts[libya]: listed in", "WARN")


def test_changes_file_schema(repo):
    edit_conflict(repo)
    bad = entry("conflicts", ["ukraine_russia"])
    bad["sources"][0]["published"] = "4 Nov"
    write_run(repo, changes_doc([bad]))
    code, f = run(repo, "--base", "HEAD", "--run-date", RUN)
    assert code == 1 and has(f, "changes.json: schema")


# ----------------------------------------------------------------------------- page / scope / live
def test_page_must_be_rebuilt(repo):
    edit_conflict(repo)
    code, f = run(repo, "--page")
    assert code == 1 and has(f, "embedded data differs")
    build_page(repo)
    code, f = run(repo, "--page")
    assert code == 0, msgs(f)


def test_scope_blocks_code_changes(repo):
    (repo / "tools" / "build.py").write_text("# changed\n")
    (repo / ".github").mkdir()
    (repo / ".github" / "x.yml").write_text("x")
    (repo / "editor-agent" / "runs" / ("%s.md" % RUN)).write_text("ok")
    code, f = run(repo, "--scope")
    assert code == 1
    assert has(f, "scope tools/build.py") and has(f, "scope .github/x.yml")
    assert not has(f, "runs/%s.md" % RUN)


def test_scope_ignores_bot_commits_but_not_own_commits(repo):
    base = git(repo, "rev-parse", "HEAD").strip()
    save(repo, "site/data/status.json", {"updated_at": NOW, "run_count": 2, "ok": True, "message_th": "x"})
    git(repo, "commit", "-qam", "chore(data): prices", email=BOT)
    code, f = run(repo, "--scope", "--base", base)
    assert code == 0, msgs(f)
    (repo / "tools" / "build.py").write_text("# agent edit\n")
    git(repo, "commit", "-qam", "agent edit")
    code, f = run(repo, "--scope", "--base", base)
    assert code == 1 and has(f, "scope tools/build.py")


def test_live_health(repo):
    code, f = run(repo, "--live")
    assert code == 0 and not [m for m in msgs(f, "WARN") if m.startswith(("site/", "updater/"))]
    save(repo, "site/data/status.json", {"updated_at": "2026-11-04T10:00:00Z", "run_count": 1, "ok": False, "message_th": "เกินวงเงิน"})
    save(repo, "site/data/market.json", {"updated_at": "2026-11-05T00:00:00Z", "items": [{"key": "gold", "value": "4400"}, {"key": "vix", "value": "n/a"}]})
    code, f = run(repo, "--live")
    assert code == 0
    for t in ("hours old", "last bot run failed", "not a number", "away from the live price"):
        assert has(f, t, "WARN"), t


def test_live_unknown_headline_conflict(repo):
    save(repo, "site/data/headlines.json", {"updated_at": "2026-11-05T00:00:00Z", "items": [{"id": "h1", "conflict_id": "gone"}]})
    _, f = run(repo, "--live")
    assert has(f, "unknown conflict 'gone'", "WARN")


def test_json_output(repo, capsys):
    code, _ = run(repo, "--json")
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True and code == 0 and isinstance(out["findings"], list)


def test_strict_turns_warnings_into_failure(repo):
    w = load(repo, "data/world-data.json")
    w["indicators"].pop()
    save(repo, "data/world-data.json", w)
    code, _ = run(repo, "--strict")
    assert code == 1
