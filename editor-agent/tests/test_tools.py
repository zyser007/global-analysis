"""Tests for brief.py, show.py and apply_changes.py. Hermetic: they work on a throwaway repo built from
tests/fixtures/, never on the working tree's data."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
FIX = HERE / "fixtures"
EA = HERE.parent
sys.path.insert(0, str(EA))


def mod(name):
    spec = importlib.util.spec_from_file_location("ea_" + name, EA / ("%s.py" % name))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


brief, show, apply_changes, check = mod("brief"), mod("show"), mod("apply_changes"), mod("check")
RUN = "2026-11-05"
NOW = dt.datetime(2026, 11, 5, 1, 0, tzinfo=dt.timezone.utc)
URL = "https://www.reuters.com/world/europe/ukraine-2026-11-04/"


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    (root / "updater" / "schema").mkdir(parents=True)
    (root / "editor-agent" / "runs").mkdir(parents=True)
    shutil.copy(FIX / "world-data.json", root / "data" / "world-data.json")
    shutil.copy(FIX / "gold.json", root / "data" / "gold.json")
    shutil.copy(FIX / "headlines.schema.json", root / "updater" / "schema" / "headlines.schema.json")
    (root / "editor-agent" / "runs" / ".gitkeep").write_text("")
    for args in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@x", "-c", "commit.gpgsign=false", *args], cwd=root, check=True)
    return root


def raw(root, rel):
    return (root / rel).read_text(encoding="utf-8")


def patch_file(tmp_path, doc, name="patch.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return str(p)


def src(url=URL, day="2026-11-04"):
    return [{"url": url, "published": day, "publisher": "Reuters"}]


def run_apply(root, tmp_path, doc, *extra):
    return apply_changes.main([patch_file(tmp_path, doc), *extra], root=root, now=NOW)


# ----------------------------------------------------------------------------- brief / show
def test_brief_is_compact_and_complete(repo, capsys):
    assert brief.main([], root=repo) == 0
    out = capsys.readouterr().out
    w = json.loads(raw(repo, "data/world-data.json"))
    for c in w["conflicts"]:
        assert c["id"] in out
    for e in w["economies"]:
        assert e["iso"] + " |" in out
    assert "## gold" in out and "calendar" in out
    assert len(out.encode("utf-8")) < 12_000, len(out.encode("utf-8"))   # a few thousand tokens at most


def test_brief_one_section(repo, capsys):
    brief.main(["economies"], root=repo)
    out = capsys.readouterr().out
    assert out.startswith("## economies") and "## conflicts" not in out


def test_show_item_and_fields(repo, capsys):
    assert show.main(["conflicts", "ukraine_russia", "status_th", "sources"], root=repo) == 0
    out = json.loads(capsys.readouterr().out)
    assert set(out) == {"status_th", "sources"}
    assert show.main(["chokepoints", "0"], root=repo) == 0
    assert json.loads(capsys.readouterr().out)["_index"] == 0
    assert show.main(["gold", "thai.sell"], root=repo) == 0
    assert json.loads(capsys.readouterr().out) == {"thai.sell": 62500}
    assert show.main(["conflicts", "no_such_id"], root=repo) == 1


# ----------------------------------------------------------------------------- apply_changes
def test_apply_conflict_change(repo, tmp_path, capsys):
    doc = {"date": RUN, "base_commit": "abc", "changes": [{
        "section": "conflicts", "key": "ukraine_russia", "set": {"status_th": "รบต่อเนื่อง (4 พ.ย.)"},
        "summary_th": "อัปเดตสถานะ", "confidence": "high", "sources": src()}], "reviewed_unchanged": ["libya"]}
    assert run_apply(repo, tmp_path, doc) == 0, capsys.readouterr().out
    w = json.loads(raw(repo, "data/world-data.json"))
    c = next(c for c in w["conflicts"] if c["id"] == "ukraine_russia")
    assert c["status_th"] == "รบต่อเนื่อง (4 พ.ย.)" and c["sources"][0] == URL and len(c["sources"]) <= 5
    assert w["meta"]["updated"] == RUN and w["meta"]["basis_th"] == "5 พ.ย. 2569"
    ch = json.loads(raw(repo, "editor-agent/runs/%s.changes.json" % RUN))
    assert ch["base_commit"] == "abc" and ch["reviewed_unchanged"] == ["libya"]
    assert ch["changes"][0]["keys"] == ["ukraine_russia"] and ch["changes"][0]["fields"] == ["status_th"]
    # formatting kept: world-data indent 1, gold untouched
    assert raw(repo, "data/world-data.json").startswith('{\n "meta"')
    assert raw(repo, "data/gold.json") == (FIX / "gold.json").read_text(encoding="utf-8")
    (repo / "editor-agent" / "runs" / ("%s.md" % RUN)).write_text("# สรุป\n", encoding="utf-8")
    code, f = check.run(["--now", NOW.isoformat(), "--base", "HEAD", "--run-date", RUN], root=repo)
    assert code == 0, [i for i in f.items if i["level"] == "ERROR"]


def test_apply_gold_needs_as_of_then_passes_check(repo, tmp_path, capsys):
    bad = {"date": RUN, "changes": [{"section": "gold", "set": {"spot_now": 3935, "from_peak_pct": -29.7},
                                     "summary_th": "ราคาล่าสุด", "confidence": "high", "sources": src("https://www.kitco.com/gold")}]}
    before = raw(repo, "data/gold.json")
    assert run_apply(repo, tmp_path, bad) == 1
    assert "as_of was not moved" in capsys.readouterr().out
    assert raw(repo, "data/gold.json") == before
    good = json.loads(json.dumps(bad))
    good["changes"][0]["set"].update({"as_of": "2026-11-05T00:40:00Z", "as_of_caption_th": "ระหว่างวัน 5 พ.ย."})
    assert run_apply(repo, tmp_path, good) == 0, capsys.readouterr().out
    g = json.loads(raw(repo, "data/gold.json"))
    assert g["updated_th"] == "ข้อมูลรวบรวมถึง 5 พ.ย. 2569 07:40 น."
    assert raw(repo, "data/gold.json").startswith('{\n  "as_of"') and not raw(repo, "data/gold.json").endswith("\n")
    ch = json.loads(raw(repo, "editor-agent/runs/%s.changes.json" % RUN))
    assert sorted(k for e in ch["changes"] for k in e["keys"]) == ["from_peak_pct", "spot_now"]
    (repo / "editor-agent" / "runs" / ("%s.md" % RUN)).write_text("# สรุป\n", encoding="utf-8")
    code, f = check.run(["--now", NOW.isoformat(), "--base", "HEAD", "--run-date", RUN], root=repo)
    assert code == 0, [i for i in f.items if i["level"] == "ERROR"]


def test_patches_merge_into_one_changes_file(repo, tmp_path, capsys):
    a = {"date": RUN, "changes": [{"section": "economies", "key": "THA", "set": {"inflation": 1.1},
                                   "summary_th": "เงินเฟ้อ", "confidence": "high", "sources": src("https://www.bot.or.th/x")}]}
    b = {"date": RUN, "changes": [{"section": "indicators", "key": "0", "set": {"delta_th": "ทรงตัว (4 พ.ย.)"},
                                   "summary_th": "ตัวชี้วัด", "confidence": "medium", "sources": src("https://www.imf.org/y")}]}
    assert run_apply(repo, tmp_path, a) == 0
    assert run_apply(repo, tmp_path, b) == 0
    ch = json.loads(raw(repo, "editor-agent/runs/%s.changes.json" % RUN))
    assert [e["section"] for e in ch["changes"]] == ["economies", "indicators"]
    w = json.loads(raw(repo, "data/world-data.json"))
    assert w["indicators"][0]["source"] == "https://www.imf.org/y"


@pytest.mark.parametrize("change,msg", [
    ({"section": "conflicts", "key": "ukraine_russia", "set": {"id": "x"}}, "cannot change"),
    ({"section": "conflicts", "key": "ukraine_russia", "set": {"nonsense": 1}}, "no field"),
    ({"section": "conflicts", "key": "ukraine_russia", "set": {"intensity": 9}}, "validation failed"),
    ({"section": "conflicts", "key": "ukraine_russia", "set": {"name_th": "ยูเครน พ.ย."}}, "cannot change"),
    ({"section": "meta", "set": {"title": "x"}}, "only updated"),
    ({"section": "conflicts", "key": "ukraine_russia", "set": {"status_th": "x"}, "sources": []}, "at least 1 source"),
    ({"section": "conflicts", "key": "nope", "set": {"status_th": "x"}}, "no unique item"),
])
def test_apply_refuses_bad_changes(repo, tmp_path, capsys, change, msg):
    change.setdefault("summary_th", "x")
    change.setdefault("confidence", "high")
    change.setdefault("sources", src())
    before = raw(repo, "data/world-data.json")
    assert run_apply(repo, tmp_path, {"date": RUN, "changes": [change]}) == 1
    assert msg in capsys.readouterr().out
    assert raw(repo, "data/world-data.json") == before
    assert not (repo / "editor-agent" / "runs" / ("%s.changes.json" % RUN)).exists()


def test_new_conflict_id_needs_code_change(repo, tmp_path, capsys):
    w = json.loads(raw(repo, "data/world-data.json"))
    item = dict(w["conflicts"][0], id="new_crisis", name_th="วิกฤตใหม่", sources=[])
    doc = {"date": RUN, "add": [{"section": "conflicts", "item": item, "summary_th": "วิกฤตใหม่", "confidence": "medium",
                                 "sources": src() + src("https://apnews.com/b")}]}
    assert run_apply(repo, tmp_path, doc) == 1
    assert "branch + issue" in capsys.readouterr().out


def test_dry_run_writes_nothing(repo, tmp_path, capsys):
    doc = {"date": RUN, "changes": [{"section": "analysis_th", "set": {"points.0": "ข้อใหม่ (4 พ.ย.)"},
                                     "summary_th": "x", "confidence": "high", "sources": src()}]}
    before = raw(repo, "data/world-data.json")
    assert run_apply(repo, tmp_path, doc, "--dry-run") == 0
    assert raw(repo, "data/world-data.json") == before
    assert "dry run" in capsys.readouterr().out
