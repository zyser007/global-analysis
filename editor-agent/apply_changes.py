#!/usr/bin/env python3
"""Apply a small JSON patch to data/world-data.json and data/gold.json and record it, with its sources, in
editor-agent/runs/<DATE>.changes.json. Keeps the files' formatting, validates before writing (nothing is
written when there is an error) and prints only a short summary.

  python3 -I editor-agent/apply_changes.py /tmp/patch.json [--dry-run]

Patch format (several patches per run are fine; each one is merged into the same changes.json):
{
  "date": "2026-11-05",                       # run date, Asia/Bangkok (default: today in Bangkok)
  "base_commit": "<sha of main at the start>", # optional, stored in changes.json
  "changes": [
    {"section": "conflicts", "key": "ukraine_russia",
     "set": {"status_th": "...", "summary_th": "...", "intensity": 5},
     "summary_th": "สรุปสั้น ๆ ว่าเปลี่ยนอะไร", "confidence": "high",
     "sources": [{"url": "https://...", "published": "2026-11-04", "publisher": "Reuters", "title": "..."}]},
    {"section": "economies", "key": "THA", "set": {"inflation": 1.2, "note_th": "..."}, ...},
    {"section": "chokepoints", "key": "0", "set": {"level": 3, "note_th": "..."}, ...},      # index or unique name part
    {"section": "indicators", "key": "3", "set": {"value": "...", "delta_th": "...", "as_of": "2026-11-04"}, ...},
    {"section": "analysis_th", "set": {"points.2": "...", "risks": ["...", "..."]}, ...},
    {"section": "gold", "set": {"as_of": "2026-11-05T00:40:00Z", "as_of_caption_th": "ระหว่างวัน 5 พ.ย. ...",
                                "spot_now": 3935, "thai.sell": 62600, "outlook_th.calendar_th.items": ["..."]}, ...},
    {"section": "meta", "set": {"basis_th": "4–5 พ.ย. 2569"}}                                  # optional, no sources
  ],
  "add": [{"section": "economies", "item": {... full item ...}, "summary_th": "...", "confidence": "medium", "sources": [...]}],
  "reviewed_unchanged": ["libya", "BRA"]
}

Done for you: the change's source URLs are put first in the item's sources[] (conflicts, economies; max 5) or in
`source` (indicators); meta.updated = date and meta.basis_th = the Thai date (unless the patch sets it) whenever
world data changes; gold `updated_th` is written from `as_of` when not given. A gold change needs `as_of` and
`as_of_caption_th` in the same patch unless an earlier patch of this run already moved `as_of`.
Not allowed: renaming id / iso / name_th / label_th, deleting items, changing meta.title (open an issue instead).
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check as C  # noqa: E402
import datatools as T  # noqa: E402

KEY_FIELDS = {"id", "iso", "name_th", "label_th"}
MAX_SOURCES = 5


class PatchError(Exception):
    pass


def norm_sources(ch: dict, where: str, required: int) -> list[dict]:
    src = ch.get("sources") or []
    if not isinstance(src, list):
        raise PatchError("%s: sources must be a list" % where)
    for s in src:
        if not isinstance(s, dict) or not str(s.get("url", "")).startswith(("http://", "https://")) or not C.parse_day(s.get("published", "")):
            raise PatchError("%s: every source needs url (http...) and published (YYYY-MM-DD): %r" % (where, s))
    if len(src) < required:
        raise PatchError("%s: needs at least %d source(s)" % (where, required))
    return [{k: s[k] for k in ("url", "published", "publisher", "title") if s.get(k)} for s in src]


def entry(file: str, section: str, key: str, fields: list[str], ch: dict, sources: list[dict]) -> dict:
    conf = ch.get("confidence", "medium")
    if conf not in ("high", "medium", "low"):
        raise PatchError("%s[%s]: confidence must be high, medium or low" % (section, key))
    summary = str(ch.get("summary_th") or "").strip()
    if not summary:
        raise PatchError("%s[%s]: summary_th is required" % (section, key))
    return {"file": file, "section": section, "keys": [key], "fields": fields, "summary_th": summary,
            "sources": sources, "confidence": conf}


def put_sources(item: dict, sources: list[dict]) -> int:
    old = list(item.get("sources", []))
    seen = {C.norm_url(u) for u in old}
    new = [s["url"] for s in sources if C.norm_url(s["url"]) not in seen]
    merged = []
    for u in new + old:
        if C.norm_url(u) not in {C.norm_url(x) for x in merged}:
            merged.append(u)
    item["sources"] = merged[:MAX_SOURCES]
    return len(new)


def apply_patch(patch: dict, root: pathlib.Path, now: dt.datetime | None = None) -> tuple[dict, dict, dict, list[str]]:
    now = now or dt.datetime.now(dt.timezone.utc)
    date_s = patch.get("date") or T.bkk_today().isoformat()
    date = C.parse_day(date_s)
    if not date:
        raise PatchError("date must be YYYY-MM-DD")
    w, wfmt = T.load(root, "world-data")
    g, gfmt = T.load(root, "gold")
    w, g = copy.deepcopy(w), copy.deepcopy(g)
    log: list[str] = []
    entries: list[dict] = []
    added: list[dict] = []
    world_changed = gold_changed = False
    gold_as_of_set = False
    basis_set = False

    for n, ch in enumerate(patch.get("changes", [])):
        sec = ch.get("section")
        sets = ch.get("set") or {}
        where = "changes[%d] %s[%s]" % (n, sec, ch.get("key", ""))
        if not isinstance(sets, dict) or not sets:
            raise PatchError("%s: 'set' must be a non-empty object of field -> value" % where)
        try:
            if sec == "meta":
                bad = set(sets) - {"updated", "basis_th"}
                if bad:
                    raise PatchError("%s: only updated / basis_th may be set (title is the owner's)" % where)
                for k, v in sets.items():
                    w["meta"][k] = v
                basis_set = basis_set or "basis_th" in sets
                log.append("meta: %s" % ", ".join(sets))
                continue
            sources = norm_sources(ch, where, 1)
            if sec in T.LIST_SECTIONS:
                if "key" not in ch:
                    raise PatchError("%s: key is required" % where)
                _, item = T.find_item(w, sec, str(ch["key"]))
                key = item[T.LIST_SECTIONS[sec]]
                for path, v in sets.items():
                    if T.split_path(path)[0] in KEY_FIELDS:
                        raise PatchError("%s: %s is the item's key and cannot change" % (where, path))
                    T.set_path(item, path, v)
                extra = ""
                if sec in ("conflicts", "economies"):
                    extra = " (+%d source)" % put_sources(item, sources)
                elif sec == "indicators" and "source" not in sets:
                    item["source"] = sources[0]["url"]
                entries.append(entry("world-data", sec, key, list(sets), ch, sources))
                world_changed = True
                log.append("%s[%s]: %s%s" % (sec, key, ", ".join(sets), extra))
            elif sec == "analysis_th":
                for path, v in sets.items():
                    T.set_path(w["analysis_th"], path, v)
                entries.append(entry("world-data", sec, "analysis_th", list(sets), ch, sources))
                world_changed = True
                log.append("analysis_th: %s" % ", ".join(sets))
            elif sec == "gold":
                tops = []
                for path, v in sets.items():
                    T.set_path(g, path, v)
                    top = str(T.split_path(path)[0])
                    if top not in tops:
                        tops.append(top)
                if "as_of" in sets:
                    gold_as_of_set = True
                    if "as_of_caption_th" not in sets:
                        raise PatchError("%s: a new as_of needs as_of_caption_th too (it shows the quote's date)" % where)
                    if "updated_th" not in sets:
                        t = C.parse_instant(sets["as_of"])
                        if not t:
                            raise PatchError("%s: as_of must be an ISO time like 2026-11-05T00:40:00Z" % where)
                        b = t.astimezone(T.BKK)
                        g["updated_th"] = "ข้อมูลรวบรวมถึง %s %s น." % (T.thai_date(b.date()), b.strftime("%H:%M"))
                for top in [t for t in tops if t not in C.GOLD_META_KEYS]:
                    e = entry("gold", "gold", top, [p for p in sets if str(T.split_path(p)[0]) == top], ch, sources)
                    entries.append(e)
                gold_changed = gold_changed or any(t not in C.GOLD_META_KEYS for t in tops) or gold_as_of_set
                log.append("gold: %s" % ", ".join(sets))
            else:
                raise PatchError("%s: unknown section (use %s, gold)" % (where, ", ".join(sorted(T.WORLD_SECTIONS))))
        except (KeyError, IndexError, TypeError) as e:
            raise PatchError("%s: %s" % (where, e))

    for n, ad in enumerate(patch.get("add", [])):
        sec = ad.get("section")
        where = "add[%d] %s" % (n, sec)
        if sec not in T.LIST_SECTIONS:
            raise PatchError("%s: only conflicts, economies, chokepoints, indicators can get new items" % where)
        item = ad.get("item")
        if not isinstance(item, dict):
            raise PatchError("%s: item must be the full new object" % where)
        kf = T.LIST_SECTIONS[sec]
        if any(x.get(kf) == item.get(kf) for x in w[sec]):
            raise PatchError("%s: %s %r already exists" % (where, kf, item.get(kf)))
        sources = norm_sources(ad, where, 2 if sec == "conflicts" else 1)
        if sec in ("conflicts", "economies"):
            item.setdefault("sources", [])
            put_sources(item, sources)
        w[sec].append(item)
        e = entry("world-data", sec, item.get(kf), [], ad, sources)
        e.pop("fields")
        added.append(e)
        world_changed = True
        log.append("ADDED %s[%s]" % (sec, item.get(kf)))

    if world_changed:
        w["meta"]["updated"] = date.isoformat()
        if not basis_set:
            w["meta"]["basis_th"] = T.thai_date(date)
    if gold_changed and not gold_as_of_set:
        t = C.parse_instant(g.get("as_of", ""))
        if not t or C.bkk_day(t) < date - dt.timedelta(days=1):
            raise PatchError("gold changed but as_of was not moved: add as_of + as_of_caption_th to this patch")

    # validate in memory; refuse to write anything on error
    f = C.Findings()
    C.check_world(w, f, date)
    C.check_gold(g, f, date, max(now, dt.datetime.combine(date, dt.time(23, 59), tzinfo=T.BKK)))
    ids = C.headline_ids(root)
    if ids is not None:
        for a in added:
            if a["section"] == "conflicts" and a["keys"][0] not in ids:
                f.error("add conflicts[%s]" % a["keys"][0], "new conflict id is not in the headlines enum; this needs a code change: put it on a branch + issue, not on main")
    errors = ["%s: %s" % (i["where"], i["what"]) for i in f.errors]
    if errors:
        raise PatchError("validation failed, nothing written:\n  " + "\n  ".join(errors[:15]))

    changes_path = root / C.RUNS / ("%s.changes.json" % date.isoformat())
    if changes_path.exists():
        doc = json.loads(changes_path.read_text(encoding="utf-8"))
        if doc.get("date") != date.isoformat():
            raise PatchError("%s has date %r" % (changes_path.name, doc.get("date")))
    else:
        doc = {"date": date.isoformat(), "changes": []}
    if patch.get("base_commit") and not doc.get("base_commit"):
        doc["base_commit"] = patch["base_commit"]
    doc.setdefault("changes", []).extend(entries)
    if added:
        doc.setdefault("added", []).extend(added)
    rev = patch.get("reviewed_unchanged") or []
    if rev:
        doc["reviewed_unchanged"] = sorted(set(doc.get("reviewed_unchanged", [])) | {str(x) for x in rev})
    se = C.schema_errors("changes.schema.json", doc)
    if se:
        raise PatchError("changes.json would be invalid: " + "; ".join(se[:5]))
    return {"world": (w, wfmt, world_changed), "gold": (g, gfmt, gold_changed or gold_as_of_set)}, doc, {"path": changes_path}, log + [
        "%d warning(s) (see check.py)" % len(f.warnings)]


def main(argv: list[str] | None = None, root: pathlib.Path = T.ROOT, now: dt.datetime | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("patch")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    try:
        patch = json.loads(pathlib.Path(a.patch).read_text(encoding="utf-8"))
        docs, changes, meta, log = apply_patch(patch, root, now)
    except (PatchError, json.JSONDecodeError, OSError) as e:
        print("apply_changes: ERROR %s" % e)
        return 1
    for line in log:
        print("  " + line)
    if a.dry_run:
        print("apply_changes: OK (dry run, nothing written)")
        return 0
    w, wfmt, wch = docs["world"]
    g, gfmt, gch = docs["gold"]
    if wch:
        T.save(root, "world-data", w, wfmt)
    if gch:
        T.save(root, "gold", g, gfmt)
    p = meta["path"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(changes, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("apply_changes: OK wrote %s%s%s" % ("data/world-data.json " if wch else "", "data/gold.json " if gch else "",
                                              p.relative_to(root)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
