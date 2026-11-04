"""Shared helpers for brief.py, show.py and apply_changes.py: load/save the data files without changing their
formatting, find one item by section + key, and read dates out of URLs and Thai text."""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
FILES = {"world-data": "data/world-data.json", "gold": "data/gold.json"}
LIST_SECTIONS = {"conflicts": "id", "economies": "iso", "chokepoints": "name_th", "indicators": "label_th"}
WORLD_SECTIONS = set(LIST_SECTIONS) | {"meta", "analysis_th"}
TH_MONTH_ABBR = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
BKK = dt.timezone(dt.timedelta(hours=7))
TH_DATE = re.compile(r"(?<!\d)(\d{1,2})\s?(%s)" % "|".join(re.escape(m) for m in TH_MONTH_ABBR))
URL_DATE = re.compile(r"(20\d\d)[/-](\d{2})[/-](\d{2})|(20\d\d)/(\d{2})/")


def thai_date(d: dt.date, year: bool = True) -> str:
    s = "%d %s" % (d.day, TH_MONTH_ABBR[d.month - 1])
    return s + (" %d" % (d.year + 543)) if year else s


def bkk_today() -> dt.date:
    return dt.datetime.now(BKK).date()


def detect_indent(raw: str) -> int | None:
    m = re.match(r"\{\n( +)\"", raw)
    return len(m.group(1)) if m else None


def load(root: pathlib.Path, file: str) -> tuple[Any, dict]:
    raw = (root / FILES[file]).read_text(encoding="utf-8")
    return json.loads(raw), {"indent": detect_indent(raw), "newline": raw.endswith("\n")}


def dump(doc: Any, fmt: dict) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=fmt.get("indent")) + ("\n" if fmt.get("newline") else "")


def save(root: pathlib.Path, file: str, doc: Any, fmt: dict) -> None:
    p = root / FILES[file]
    tmp = p.with_suffix(".tmp")
    tmp.write_text(dump(doc, fmt), encoding="utf-8")
    tmp.replace(p)


def find_item(world: dict, section: str, key: str) -> tuple[int, dict]:
    """Find a list item by its key field, by index ('3'), or by a unique substring of the key."""
    items = world.get(section, [])
    kf = LIST_SECTIONS[section]
    for i, it in enumerate(items):
        if it.get(kf) == key:
            return i, it
    if re.fullmatch(r"\d+", key) and int(key) < len(items):
        return int(key), items[int(key)]
    hits = [(i, it) for i, it in enumerate(items) if key.lower() in str(it.get(kf, "")).lower()]
    if len(hits) == 1:
        return hits[0]
    raise KeyError("%s: no unique item %r (%d matches)" % (section, key, len(hits)))


def split_path(path: str) -> list:
    return [int(p) if re.fullmatch(r"\d+", p) else p for p in path.split(".") if p != ""]


def get_path(obj: Any, path: str) -> Any:
    for p in split_path(path):
        obj = obj[p]
    return obj


def set_path(obj: Any, path: str, value: Any) -> Any:
    """Set an existing key/index; returns the old value. Raises KeyError for a path that does not exist."""
    parts = split_path(path)
    if not parts:
        raise KeyError("empty path")
    for p in parts[:-1]:
        obj = obj[p]
    last = parts[-1]
    if isinstance(obj, dict) and last not in obj:
        raise KeyError("no field %r (fields: %s)" % (last, ", ".join(obj.keys())))
    if isinstance(obj, list) and not (isinstance(last, int) and last < len(obj)):
        raise KeyError("no index %r" % last)
    old = obj[last]
    obj[last] = value
    return old


def url_date(u: str) -> dt.date | None:
    m = URL_DATE.search(u)
    if not m:
        return None
    try:
        if m.group(1):
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        return dt.date(int(m.group(4)), int(m.group(5)), 1)
    except ValueError:
        return None


def text_dates(text: str, ref: dt.date) -> list[dt.date]:
    """Thai '29 ต.ค.' mentions as dates, the year taken so the date is not far after ref."""
    out = []
    for d, mon in TH_DATE.findall(text or ""):
        m = TH_MONTH_ABBR.index(mon) + 1
        y = ref.year if m <= ref.month + 1 else ref.year - 1
        try:
            out.append(dt.date(y, m, int(d)))
        except ValueError:
            pass
    return out
