#!/usr/bin/env python3
"""Open the built page headless and look for what a reader would notice: errors, stale dates, empty
panels, broken layout. Every expectation is read from data/*.json, so it keeps working after the
data changes (unlike the hard-coded values in e2e/).

  python3 editor-agent/visual_check.py [--shots DIR] [--json]

Serves a copy of site/ under /global-analysis/ on 127.0.0.1 (like GitHub Pages), then loads it at
desktop 1280x800 and phone 390x844, light and dark. Uses the Python Playwright that is pre-installed
in the Managed Agents cloud sandbox (Chromium in /opt/pw-browsers); locally: pip install playwright.

Checks, per viewport:
  - no console errors, page errors or failed same-origin requests
  - the globe canvas rendered (no WebGL fallback) and live data loaded (no offline bar)
  - footer basis date = meta.basis_th; gold note = Bangkok date of gold.as_of
  - overview tiles / points / risks, conflict and economy list lengths = the data
  - no 'null' / 'NaN' / 'undefined' text in any tab, every tab has content
  - no horizontal scroll and no element wider than the panel
One more case, reading-mobile: ?view=read at 390x844 with every section open: the six chapters have content, the
conflict, economy (table rows and notes) and chokepoint counts = the data, no errors, no bad text, no overflow, and the
page is still a book page: figures in tables, the page colour and the book face in force, every colour readable at 4.5:1.
Screenshots go to --shots (default editor-agent/shots/, which .gitignore already excludes).
Exit 1 on any ERROR.

In the Managed Agents sandbox (detected like e2e.sh: /opt/pw-browsers and /mnt/session exist, or
VISUAL_IGNORE_HTTPS_ERRORS=1) the browser context ignores HTTPS certificate errors: the sandbox re-signs outgoing
TLS (git and curl trust it, Chromium does not), which would otherwise break every external asset (three.js on
cdnjs, Google Fonts). Console errors, page errors, failed same-origin requests and HTTP errors still fail the
check, everywhere. Every problem line names its URL; failed external requests are listed as WARN with the URL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import json
import os
import pathlib
import shutil
import socketserver
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
BKK = dt.timezone(dt.timedelta(hours=7))
TH_MONTH_ABBR = ["ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
CASES = [
    {"name": "desktop-light", "w": 1280, "h": 800, "scheme": "light"},
    {"name": "desktop-dark", "w": 1280, "h": 800, "scheme": "dark"},
    {"name": "mobile-light", "w": 390, "h": 844, "scheme": "light"},
    {"name": "mobile-dark", "w": 390, "h": 844, "scheme": "dark"},
]
LAUNCH_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def thai_date(d: dt.date) -> str:
    return "%d %s %d" % (d.day, TH_MONTH_ABBR[d.month - 1], d.year + 543)


def in_sandbox() -> bool:
    if os.environ.get("VISUAL_IGNORE_HTTPS_ERRORS") == "1":
        return True
    return pathlib.Path("/opt/pw-browsers").is_dir() and pathlib.Path("/mnt/session").is_dir()


def serve(site: pathlib.Path) -> tuple[str, http.server.ThreadingHTTPServer, pathlib.Path]:
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="editor-visual-"))
    shutil.copytree(site, tmp / "global-analysis")

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

    srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(tmp)))   # no getfqdn()
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return "http://127.0.0.1:%d/global-analysis/" % srv.server_address[1], srv, tmp


READING_NAME = "reading-mobile"
READING_WIDTH = 390   # compared with this, not innerWidth: on a phone viewport innerWidth grows with content that is too wide
READING_JS = """() => {
  const ids = ['r-latest', 'r-prices', 'r-conflicts', 'r-disasters', 'r-economy', 'r-gold'];
  document.querySelectorAll('#reader details').forEach((d) => { d.open = true; });
  const n = (sel) => document.querySelectorAll(sel).length;
  const reader = document.getElementById('reader');
  const banner = document.getElementById('r-banner');
  return {
    thin: ids.filter((id) => { const e = document.getElementById(id); return !e || e.innerText.trim().length < 40; }),
    text: reader ? reader.innerText : '',
    conflicts: n('#r-conflicts li.rd-conf'), economies: n('#r-econ-list tbody tr'), econNotes: n('#r-econ-notes > li'), chokepoints: n('#r-choke-list > li'),
    priceTable: n('table#r-price-list tbody[data-key]'),
    fontFamily: getComputedStyle(document.body).fontFamily,
    contrast: ['.topbar h1', '.rd-toc a', '.rd-fresh', '.rd-prose li', '.rd-level', '.rd-table .val', '.rd-table .line2 td', 'details.rd-more > summary', '.rd-note'].map((s) => {
      const e = document.querySelector(s); if (!e) return [s, 0];
      const v = (c) => { const m = c.match(/[0-9.]+/g).map(Number).slice(0, 3); return m.map((x) => (x /= 255) <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4)); };
      const l = (c) => { const a = v(c); return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]; };
      const a = l(getComputedStyle(e).color), b = l(getComputedStyle(document.body).backgroundColor);
      return [s, (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)];
    }),
    offline: !!(window.__liveState || {}).offline,
    banner: banner && !banner.hidden ? banner.textContent : '',
    width: [document.documentElement.scrollWidth, document.body.scrollWidth],
    wide: Array.from(document.querySelectorAll('.topbar *, #reader *')).filter((e) => {
      const r = e.getBoundingClientRect(); return e.checkVisibility() && r.width > 0 && (r.right > WIDTH + 0.5 || r.left < -0.5);
    }).map((e) => e.className || e.tagName).slice(0, 3),
  };
}"""


def check_reading(browser, url: str, world: dict, sandbox: bool, shots: pathlib.Path, add) -> None:
    """The reading view with today's data, every section open: six sections, no errors, no overflow. One phone case only."""
    import re
    ctx = browser.new_context(viewport={"width": READING_WIDTH, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              ignore_https_errors=sandbox)
    page = ctx.new_page()
    errs: list[str] = []
    page.on("console", lambda m: errs.append("console: %s" % m.text[:160]) if m.type == "error" else None)
    page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:160]))
    page.on("response", lambda r: errs.append("HTTP %d %s" % (r.status, r.url)) if r.status >= 400 and r.url.startswith(url) else None)
    page.goto(url + "?view=read", wait_until="load")
    try:
        page.wait_for_function("() => ((window.__liveState || {}).polls || 0) > 0", timeout=15000)
    except Exception:
        add("ERROR", READING_NAME, "the page never finished its first data load")
    page.screenshot(path=str(shots / (READING_NAME + ".png")))
    r = page.evaluate(READING_JS.replace("WIDTH", str(READING_WIDTH)))
    for e in errs[:5]:
        add("ERROR", READING_NAME, e)
    if r["thin"]:
        add("ERROR", READING_NAME, "empty or missing sections: " + ", ".join(r["thin"]))
    for what, key in (("conflicts", "conflicts"), ("economies", "economies"), ("economies", "econNotes"), ("chokepoints", "chokepoints")):
        if r[key] != len(world.get(what, [])):
            add("ERROR", READING_NAME, "%s (%s): %d on the page, %d in the data" % (what, key, r[key], len(world.get(what, []))))
    if not r["priceTable"] and not r["offline"]:
        add("ERROR", READING_NAME, "the prices are not in their table")
    if "Noto Serif Thai" not in r["fontFamily"]:
        add("ERROR", READING_NAME, "the book face is not in force: " + r["fontFamily"][:80])
    low = ["%s %.2f" % (x, c) for x, c in r["contrast"] if c < 4.5]
    if low:
        add("ERROR", READING_NAME, "text below 4.5:1: " + ", ".join(low))
    bad = sorted(set(re.findall(r"\bnull\b|\bNaN\b|undefined|\[object Object\]", r["text"])))
    if bad:
        add("ERROR", READING_NAME, "page shows " + ", ".join(bad))
    if max(r["width"]) > READING_WIDTH or r["wide"]:
        add("ERROR", READING_NAME, "horizontal overflow: %s %s" % (r["width"], ", ".join(map(str, r["wide"]))))
    if r["offline"]:
        add("ERROR", READING_NAME, "offline: data/*.json did not load")
    elif r["banner"]:
        add("WARN", READING_NAME, r["banner"][:120])
    ctx.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(ROOT / "editor-agent" / "shots"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", help="run one case by name, e.g. mobile-dark")
    ap.add_argument("--site", default=str(ROOT / "site"), help="folder served as /global-analysis/ (tests)")
    ap.add_argument("--data-root", default=str(ROOT), help="repo root whose data/*.json give the expectations (tests)")
    a = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("ERROR playwright: the Python package is not installed (pip install playwright)")
        return 1

    droot = pathlib.Path(a.data_root)
    world = json.loads((droot / "data" / "world-data.json").read_text(encoding="utf-8"))
    gold = json.loads((droot / "data" / "gold.json").read_text(encoding="utf-8"))
    meta = world.get("meta", {})
    basis = meta.get("basis_th") or thai_date(dt.date.fromisoformat(meta["updated"]))
    gold_day = thai_date(dt.datetime.fromisoformat(gold["as_of"].replace("Z", "+00:00")).astimezone(BKK).date())
    expect_counts = {
        "#view-overview .tile": len(world.get("indicators", [])),
        "#view-overview .points > li": len(world.get("analysis_th", {}).get("points", [])),
        "#view-overview .risks > li": len(world.get("analysis_th", {}).get("risks", [])),
    }
    shots = pathlib.Path(a.shots)
    shots.mkdir(parents=True, exist_ok=True)
    url, srv, tmp = serve(pathlib.Path(a.site))
    findings: list[dict] = []

    def add(level: str, case: str, what: str) -> None:
        findings.append({"level": level, "case": case, "what": what})

    sandbox = in_sandbox()
    add("INFO", "tls", "sandbox: HTTPS certificate errors ignored (TLS is re-signed by the sandbox egress)" if sandbox
        else "HTTPS certificates checked normally")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
            for c in CASES:
                if a.only and c["name"] != a.only:
                    continue
                mobile = c["w"] < 500
                ctx = browser.new_context(viewport={"width": c["w"], "height": c["h"]}, color_scheme=c["scheme"],
                                          device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile,
                                          ignore_https_errors=sandbox)
                page = ctx.new_page()
                errs: list[str] = []
                ext: list[str] = []

                def on_console(m, errs=errs):
                    if m.type == "error":
                        loc = (m.location or {}).get("url") or "?"
                        errs.append("console: %s @ %s" % (m.text, loc))

                def on_failed(r, errs=errs, ext=ext):
                    line = "request failed: %s (%s)" % (r.url, r.failure or "?")
                    (errs if r.url.startswith(url) else ext).append(line)

                page.on("console", on_console)
                page.on("pageerror", lambda e, errs=errs: errs.append("pageerror: " + str(e)))
                page.on("requestfailed", on_failed)
                page.on("response", lambda r, errs=errs: errs.append("HTTP %d %s" % (r.status, r.url)) if r.status >= 400 and r.url.startswith(url) else None)
                name = c["name"]
                page.goto(url + "?view=map", wait_until="load")   # the map view is what these cases check; phones default to the reading view
                page.wait_for_timeout(3500)

                def count(sel: str) -> int:
                    return page.locator(sel).count()

                def text(sel: str) -> str:
                    loc = page.locator(sel)
                    return loc.first.inner_text() if loc.count() else ""

                def no_bad_text(label: str) -> None:
                    t = page.evaluate("() => (document.getElementById('panel-body') || document.body).innerText")
                    import re
                    bad = re.findall(r"\bnull\b|\bNaN\b|undefined|\[object Object\]", t)
                    if bad:
                        add("ERROR", name, "%s: panel shows %s" % (label, ", ".join(sorted(set(bad)))))

                def layout(label: str) -> None:
                    sw = page.evaluate("() => [document.documentElement.scrollWidth, window.innerWidth, document.body.scrollWidth]")
                    if sw[0] > sw[1] or sw[2] > sw[1]:
                        add("ERROR", name, "%s: horizontal scroll (%s > %s)" % (label, max(sw[0], sw[2]), sw[1]))
                    wide = page.evaluate("""() => { const b = document.getElementById('panel-body'); if (!b) return [];
                        return Array.from(b.querySelectorAll('*')).filter(e => !e.closest('.ticker') && e.scrollWidth > b.clientWidth + 1)
                          .map(e => e.className || e.tagName).slice(0, 5); }""")
                    if wide:
                        add("ERROR", name, "%s: elements wider than the panel: %s" % (label, ", ".join(map(str, wide))))

                if count("#stage canvas") != 1 or count("#fallback.on") != 0:
                    add("ERROR", name, "the globe did not render (WebGL fallback shown)")
                if count("#live-slot .offline-bar"):
                    add("ERROR", name, "offline bar shown: data/*.json did not load")
                if count("#sample-badge") and page.locator("#sample-badge").is_visible():
                    add("ERROR", name, "sample badge visible (meta.sample is true?)")
                foot = text("#foot-basis").strip()
                if foot != basis:
                    add("ERROR", name, "footer basis date %r != meta.basis_th %r" % (foot, basis))
                if page.locator("#updated.is-stale").count() or page.locator(".live-head.is-stale").count():
                    add("WARN", name, "live prices are marked stale (ข้อมูลเก่า): the Actions bot is late")
                for sel, n in expect_counts.items():
                    if count(sel) != n:
                        add("ERROR", name, "%s: %d on the page, %d in the data" % (sel, count(sel), n))
                no_bad_text("overview")
                layout("overview")
                page.screenshot(path=str(shots / ("%s-1-overview.png" % name)))

                for tab, n_items in (("conflicts", len(world.get("conflicts", []))), ("economies", len(world.get("economies", []))),
                                     ("gold", None), ("disasters", None)):
                    page.click('.tab[data-tab="%s"]' % tab)
                    page.wait_for_timeout(600)
                    view = "#view-%s" % tab
                    if not page.locator(view).is_visible():
                        add("ERROR", name, "%s tab did not open" % tab)
                        continue
                    body = text(view)
                    if len(body.strip()) < 40:
                        add("ERROR", name, "%s tab is (nearly) empty" % tab)
                    if n_items is not None and count(view + " .item") != n_items:
                        add("ERROR", name, "%s list: %d items on the page, %d in the data" % (tab, count(view + " .item"), n_items))
                    if tab == "conflicts" and count(view + " .basis-note") and basis not in text(view + " .basis-note"):
                        add("ERROR", name, "conflicts basis note does not show %r" % basis)
                    if tab == "gold":
                        note = text("#gold-analysis-note")
                        if gold_day not in note:
                            add("ERROR", name, "gold analysis note %r does not show the gold.as_of date %s" % (note[:120], gold_day))
                        if not page.locator("#gold-chart svg").count():
                            add("ERROR", name, "gold chart missing")
                    no_bad_text(tab)
                    layout(tab)
                    page.screenshot(path=str(shots / ("%s-%s.png" % (name, tab))))
                for e in errs:
                    add("ERROR", name, e)
                for e in ext:
                    add("WARN", name, e + " (external)")
                ctx.close()
            if not a.only or a.only == READING_NAME:
                check_reading(browser, url, world, sandbox, shots, add)
            browser.close()
    except Exception as e:  # a browser that cannot start is an environment problem the agent must report
        add("ERROR", "browser", "%s: %s" % (type(e).__name__, str(e)[:400]))
    finally:
        srv.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)

    errors = [x for x in findings if x["level"] == "ERROR"]
    warns = [x for x in findings if x["level"] == "WARN"]
    if a.json:
        print(json.dumps({"ok": not errors, "shots": str(shots), "findings": findings}, ensure_ascii=False, indent=1))
    else:
        for x in findings:
            print("%-5s %s: %s" % (x["level"], x["case"], x["what"]))
        print("visual_check.py: %s - %d error(s), %d warning(s); screenshots in %s" % (
            "FAIL" if errors else "OK", len(errors), len(warns), shots))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
