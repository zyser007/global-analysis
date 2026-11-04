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
Screenshots go to --shots (default editor-agent/shots/, which .gitignore already excludes).
Exit 1 on any ERROR.

three.js (pinned r128 on cdnjs) is fetched once with curl, checked, and served to the page from that copy via
page routing. Reason: the Managed Agents sandbox re-signs outgoing TLS, which curl/git trust but Chromium does not
(ERR_CERT_AUTHORITY_INVALID). Only that one URL is routed; certificate checks, console errors, page errors and
failed requests stay as strict as before. If curl cannot get a valid copy, the page loads the CDN itself.
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import http.server
import json
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
THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
LAUNCH_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"]


def thai_date(d: dt.date) -> str:
    return "%d %s %d" % (d.day, TH_MONTH_ABBR[d.month - 1], d.year + 543)


def fetch_three() -> tuple[bytes | None, str]:
    """The pinned three.js via curl (which trusts the sandbox's TLS re-signing), checked to really be r128."""
    import subprocess

    try:
        r = subprocess.run(["curl", "-fsSL", "--max-time", "40", THREE_URL], capture_output=True)
    except OSError as e:
        return None, "curl not available: %s" % e
    if r.returncode != 0:
        return None, "curl failed: %s" % r.stderr.decode("utf-8", "replace").strip()[:160]
    return check_three(r.stdout)


def check_three(body: bytes) -> tuple[bytes | None, str]:
    head = body[:2000].decode("utf-8", "replace")
    if len(body) < 300_000 or "three.js" not in head.lower():
        return None, "the downloaded file does not look like three.js (%d bytes)" % len(body)
    if b'REVISION="128"' not in body and b"REVISION = '128'" not in body and b'"128"' not in body:
        return None, "the downloaded three.js is not revision 128"
    return body, "three.js r128 served from a checked curl copy (%d bytes)" % len(body)


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=str(ROOT / "editor-agent" / "shots"))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--only", help="run one case by name, e.g. mobile-dark")
    ap.add_argument("--site", default=str(ROOT / "site"), help="folder served as /global-analysis/ (tests)")
    ap.add_argument("--data-root", default=str(ROOT), help="repo root whose data/*.json give the expectations (tests)")
    ap.add_argument("--no-three-copy", action="store_true", help="let the page load three.js from the CDN itself")
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

    three, why = (None, "disabled by --no-three-copy") if a.no_three_copy else fetch_three()
    add("INFO", "three.js", why if three else "page loads the CDN itself (%s)" % why)

    def serve_three(route):
        route.fulfill(status=200, body=three, headers={"content-type": "application/javascript; charset=utf-8",
                                                       "access-control-allow-origin": "*"})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=LAUNCH_ARGS)
            for c in CASES:
                if a.only and c["name"] != a.only:
                    continue
                mobile = c["w"] < 500
                ctx = browser.new_context(viewport={"width": c["w"], "height": c["h"]}, color_scheme=c["scheme"],
                                          device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile)
                if three:
                    ctx.route(THREE_URL, serve_three)
                page = ctx.new_page()
                errs: list[str] = []
                page.on("console", lambda m, errs=errs: errs.append("console: " + m.text) if m.type == "error" else None)
                page.on("pageerror", lambda e, errs=errs: errs.append("pageerror: " + str(e)))
                page.on("requestfailed", lambda r, errs=errs: errs.append("request failed: " + r.url) if r.url.startswith(url) or "cdnjs" in r.url else None)
                page.on("response", lambda r, errs=errs: errs.append("HTTP %d %s" % (r.status, r.url)) if r.status >= 400 and r.url.startswith(url) else None)
                name = c["name"]
                page.goto(url, wait_until="load")
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
                ctx.close()
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
