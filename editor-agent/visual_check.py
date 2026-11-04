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
One more case, reading-mobile: ?view=read at 390x844, page by page with everything open, and every article: the front page
and six chapters have content, the conflict, economy and chokepoint counts = the data, every article opens, no errors, no bad
text, no Thai digits, no overflow, every colour readable at 4.5:1. A chapter longer than about three screens only warns.
One more case, infographic-mobile: every marker's click card at 390x844 with reduced motion: no bad text, no overflow, one row per arc.
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
READING_MAX_PX = 2500   # the first state of one chapter on a phone: about three screens
READING_JS = """async () => {
  const pages = ['front', 'latest', 'prices', 'conflicts', 'disasters', 'economy', 'gold'];
  const n = (sel) => document.querySelectorAll(sel).length;
  const wait = () => new Promise((r) => setTimeout(r, 60));
  const go = async (h) => { location.hash = h; await wait(); };
  const cv = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
  const rgba = (c) => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); const d = cv.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
  const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
  const bgOf = (e) => { for (; e; e = e.parentElement) { const c = rgba(getComputedStyle(e).backgroundColor); if (c[3] > 0.99) return c; } return [255, 255, 255, 1]; };
  const out = { thin: [], text: '', tall: [], width: [], wide: [], low: [] };
  const scan = () => {
    out.width.push(document.documentElement.scrollWidth, document.body.scrollWidth);
    document.querySelectorAll('.topbar *, #rd-tabs *, #reader *, #rd-sheet *').forEach((e) => {
      if (!e.checkVisibility() || e.closest('svg')) return;
      const r = e.getBoundingClientRect();
      if (r.width > 0 && (r.right > WIDTH + 0.5 || r.left < -0.5)) out.wide.push(e.className || e.tagName);
      if (!Array.from(e.childNodes).some((x) => x.nodeType === 3 && x.textContent.trim())) return;
      const a = lum(rgba(getComputedStyle(e).color)), b = lum(bgOf(e)), k = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      if (k < 4.5) out.low.push((e.className || e.tagName) + ' ' + k.toFixed(2));
    });
  };
  for (const p of pages) {
    await go(p === 'front' ? 'front' : p);
    const id = 'r-' + p, e = document.getElementById(id);
    if (!e || e.innerText.trim().length < 40) out.thin.push(id);
    const h = document.documentElement.scrollHeight;
    if (p === 'front') { const last = Array.from(document.querySelectorAll('.rd-tile')).pop(), tab = document.getElementById('rd-tabs').getBoundingClientRect().top; out.frontFits = !!last && last.getBoundingClientRect().bottom <= tab + 0.5; }
    else if (h > READ_MAX) out.tall.push(p + ' ' + h);
    scan();
    document.querySelectorAll('#reader .rd-sec.on details').forEach((d) => { d.open = true; });
    scan();
    if (e) out.text += e.innerText + '\\n';
  }
  /* the long text: one article per kind, and every article of the two big lists */
  const arts = ['latest/analysis', 'latest/risks', 'latest/thailand'];
  document.querySelectorAll('#r-conflicts a[href^="#conflicts/"], #r-economy a[href^="#economy/"], #r-disasters a[href^="#disasters/"], #r-prices a[href^="#prices/"]').forEach((a) => arts.push(a.getAttribute('href').slice(1)));
  out.missingArticles = [];
  for (const h of Array.from(new Set(arts))) {
    await go(h);
    const s = document.getElementById('rd-sheet');
    if (s.hidden || s.innerText.trim().length < 20) { out.missingArticles.push(h); continue; }
    out.text += s.innerText + '\\n';
    scan();
  }
  await go('front');
  const banner = document.getElementById('r-banner');
  return Object.assign(out, {
    articles: arts.length,
    conflicts: n('#r-conflicts li.rd-conf'), economies: n('#r-econ-list > li'), chokepoints: n('#r-choke-list > li'),
    priceTable: n('#r-price-list li[data-key]'),
    fontFamily: getComputedStyle(document.body).fontFamily,
    offline: !!(window.__liveState || {}).offline,
    banner: banner && !banner.hidden ? banner.textContent : '',
    wide: Array.from(new Set(out.wide)).slice(0, 3), low: Array.from(new Set(out.low)).slice(0, 6),
  });
}"""


def check_reading(browser, url: str, world: dict, sandbox: bool, shots: pathlib.Path, add) -> None:
    """The reading view with today's data, page by page with everything open, and every article: six chapters and a front page,
    no errors, no overflow, no Thai digits, the first state of a chapter stays short. One phone case only."""
    import re
    ctx = browser.new_context(viewport={"width": READING_WIDTH, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              reduced_motion="reduce", ignore_https_errors=sandbox)
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
    r = page.evaluate(READING_JS.replace("WIDTH", str(READING_WIDTH)).replace("READ_MAX", str(READING_MAX_PX)))
    for e in errs[:5]:
        add("ERROR", READING_NAME, e)
    if r["thin"]:
        add("ERROR", READING_NAME, "empty or missing sections: " + ", ".join(r["thin"]))
    for what, key in (("conflicts", "conflicts"), ("economies", "economies"), ("chokepoints", "chokepoints")):
        if r[key] != len(world.get(what, [])):
            add("ERROR", READING_NAME, "%s (%s): %d on the page, %d in the data" % (what, key, r[key], len(world.get(what, []))))
    if not r["priceTable"] and not r["offline"]:
        add("ERROR", READING_NAME, "the prices are not in their table")
    if "Noto Serif Thai" not in r["fontFamily"]:
        add("ERROR", READING_NAME, "the book face is not in force: " + r["fontFamily"][:80])
    if r["low"]:
        add("ERROR", READING_NAME, "text below 4.5:1: " + ", ".join(r["low"]))
    if r["missingArticles"]:
        add("ERROR", READING_NAME, "articles that do not open: " + ", ".join(r["missingArticles"][:5]))
    if re.search(r"[\u0e50-\u0e59]", r["text"]):
        add("ERROR", READING_NAME, "Thai digits on the page: " + ", ".join(sorted(set(re.findall(r"\S*[\u0e50-\u0e59]\S*", r["text"])))[:3]))
    # today's data decides these lengths, so they warn and do not block a publish
    if r["tall"]:
        add("WARN", READING_NAME, "chapter longer than %d px on a phone: %s" % (READING_MAX_PX, ", ".join(r["tall"])))
    if not r["frontFits"] and not r["banner"] and not r["offline"]:
        add("WARN", READING_NAME, "the front page entries no longer fit one phone screen")
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


CARD_NAME = "infographic-mobile"
CARD_WIDTH = 390
CARD_JS = """() => {
  const fx = window.__globeFx; if (!fx) return { missing: true };
  const c = fx.counts(), out = { missing: false, cards: 0, bad: [], arcs: [], hidden: [], wide: [], width: [] };
  for (const [k, n] of [['conflict', c.conflict], ['econ', c.econ], ['choke', c.choke], ['disaster', c.disaster], ['gold', 1]]) {
    for (let i = 0; i < n; i++) {
      window.__igSelect(k, i);
      const d = document.getElementById('view-detail'), id = k + ':' + i, t = d.innerText;
      if (!d.querySelector('.ig h2')) { out.bad.push(id + ' no card'); continue; }
      out.cards++;
      const m = t.match(/\\bnull\\b|\\bNaN\\b|undefined|\\[object Object\\]/); if (m) out.bad.push(id + ' ' + m[0]);
      if (d.querySelectorAll('.ig-link[data-arc="1"]').length !== fx.arcs.length) out.arcs.push(id);
      if (Array.from(d.querySelectorAll('.ig-rv')).some((e) => +getComputedStyle(e).opacity < 1)) out.hidden.push(id);
      const wide = Array.from(d.querySelectorAll('*')).find((e) => { const r = e.getBoundingClientRect(); return r.width > 0 && e.checkVisibility() && (r.right > WIDTH + 0.5 || r.left < -0.5); });
      if (wide) out.wide.push(id + ' ' + (wide.className || wide.tagName));
    }
  }
  out.width = [document.documentElement.scrollWidth, document.body.scrollWidth];
  return out;
}"""


def check_cards(browser, url: str, sandbox: bool, shots: pathlib.Path, add) -> None:
    """Every marker's infographic card with today's data, at once (reduced motion skips the animation): no bad text, no
    overflow, one row per arc. One phone case only, so the gate stays cheap."""
    import time
    t0 = time.monotonic()
    ctx = browser.new_context(viewport={"width": CARD_WIDTH, "height": 844}, device_scale_factor=2, is_mobile=True, has_touch=True,
                              reduced_motion="reduce", ignore_https_errors=sandbox)
    page = ctx.new_page()
    errs: list[str] = []
    page.on("console", lambda m: errs.append("console: %s" % m.text[:160]) if m.type == "error" else None)
    page.on("pageerror", lambda e: errs.append("pageerror: " + str(e)[:160]))
    page.goto(url + "?view=map", wait_until="load")
    try:
        page.wait_for_function("() => ((window.__liveState || {}).polls || 0) > 0 && window.__globeFx && window.__globeFx.stats()", timeout=15000)
    except Exception:
        add("ERROR", CARD_NAME, "the globe or its data never finished loading")
    r = page.evaluate(CARD_JS.replace("WIDTH", str(CARD_WIDTH)))
    for e in errs[:5]:
        add("ERROR", CARD_NAME, e)
    if r["missing"]:
        add("ERROR", CARD_NAME, "the page has no infographic code")
    else:
        for what, key in (("bad text or no card", "bad"), ("arcs without a row", "arcs"), ("elements left hidden", "hidden"), ("wider than the phone", "wide")):
            if r[key]:
                add("ERROR", CARD_NAME, "%s: %s" % (what, ", ".join(r[key][:5])))
        if max(r["width"]) > CARD_WIDTH:
            add("ERROR", CARD_NAME, "horizontal overflow: %s" % r["width"])
        add("INFO", CARD_NAME, "%d cards checked in %.1f s" % (r["cards"], time.monotonic() - t0))
    page.screenshot(path=str(shots / (CARD_NAME + ".png")))
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
            if not a.only or a.only == CARD_NAME:
                check_cards(browser, url, sandbox, shots, add)
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
