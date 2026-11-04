// Reading view (โหมดอ่านง่าย, a magazine): the view switch and its memory, one chapter on screen at a time, the front page that
// fits a phone, swipe, tabs, the back button, the article sheet, type and colour, keeping the reader's place, failure honesty
// and the deferred globe. Every context here starts from an empty storage state, because playwright.config.js stores the map
// view for the older specs.
const { test, expect, webkit } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const { URL, SHOTS, writeData, removeData, resetData, seed, collectErrors, noHScroll, repoll } = require('./helpers');

// E2E_LIVE_EMBED=1 runs these against the page's own embedded data of today instead of the frozen copy (see serve.py)
const LIVE_EMBED = process.env.E2E_LIVE_EMBED === '1';
const EMBED = LIVE_EMBED ? path.join(__dirname, '..', '..', 'data') : path.join(__dirname, '..', 'fixtures');
const world = JSON.parse(fs.readFileSync(path.join(EMBED, 'world-data.json'), 'utf8'));
const goldFx = JSON.parse(fs.readFileSync(path.join(EMBED, 'gold.json'), 'utf8'));
const FRESH = { storageState: { cookies: [], origins: [] } };
const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString();
const MIN = 60000, HOUR = 3600000;
const CHAPTERS = ['latest', 'prices', 'conflicts', 'disasters', 'economy', 'gold'];
const PAGES = ['front', ...CHAPTERS];
const SEC = (c) => 'r-' + c;
const THREE_RE = /three\.min\.js/;
const MAX_CHAPTER_PX = 2500;
// noon the day after the frozen fixture's review date: nothing is old, so no warning takes room on the page
const FIXTURE_NOON = Date.parse(world.meta.updated + 'T05:00:00Z') + 24 * HOUR;

async function open(browser, w, h, extra = {}) {
  const mobile = w < 500;
  const ctx = await browser.newContext({ ...FRESH, viewport: { width: w, height: h }, colorScheme: 'light', isMobile: mobile, hasTouch: mobile, ...extra });
  const page = await ctx.newPage();
  return { ctx, page };
}
async function ready(page) { await expect.poll(() => page.evaluate(() => (window.__liveState || {}).polls || 0)).toBeGreaterThan(0); }
const viewOf = (page) => page.evaluate(() => document.documentElement.getAttribute('data-view'));
const stored = (page) => page.evaluate(() => localStorage.getItem('world-view'));
const onChapter = (page) => page.evaluate(() => document.querySelector('.rd-sec.on').id);
const sheetOpen = (page) => page.evaluate(() => !document.getElementById('rd-sheet').hidden);
async function expectRead(page) {
  expect(await viewOf(page)).toBe('read');
  await expect(page.locator('#reader')).toBeVisible();
  await expect(page.locator('#stage')).toBeHidden();
  await expect(page.locator('#vw-map')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('#vw-read')).toHaveAttribute('aria-pressed', 'true');
}
async function expectMap(page) {
  expect(await viewOf(page)).toBe('map');
  await expect(page.locator('#stage')).toBeVisible();
  await expect(page.locator('#reader')).toBeHidden();
  await expect(page.locator('#rd-tabs')).toBeHidden();
  await expect(page.locator('#vw-map')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#vw-read')).toHaveAttribute('aria-pressed', 'false');
}
// a stored page colour and type size, as if the reader had picked them earlier
async function openAs(browser, w, h, theme, size, extra = {}) {
  const o = await open(browser, w, h, extra);
  await o.page.addInitScript(([t, z]) => { try { if (t) localStorage.setItem('world-read-theme', t); if (z) localStorage.setItem('world-read-size', z); } catch (e) { /* blocked */ } }, [theme, size ? String(size) : null]);
  return o;
}
const go = (page, c) => page.click(`#rd-tabs a[data-sec="r-${c}"]`);
const openAll = (page) => page.evaluate(() => document.querySelectorAll('#reader .rd-sec.on details').forEach((d) => { d.open = true; }));
// a real touch drag through the browser's own input pipeline
async function swipe(page, x0, x1, y0 = 400, y1 = y0) {
  const cdp = await page.context().newCDPSession(page);
  const send = (type, pts) => cdp.send('Input.dispatchTouchEvent', { type, touchPoints: pts });
  await send('touchStart', [{ x: x0, y: y0 }]);
  const n = 8;
  for (let i = 1; i <= n; i++) { await send('touchMove', [{ x: x0 + (x1 - x0) * i / n, y: y0 + (y1 - y0) * i / n }]); await page.waitForTimeout(16); }
  await send('touchEnd', []);
  await page.waitForTimeout(60);
}
async function fitsWidth(page, w, label) {
  const r = await page.evaluate((W) => ({
    sw: [document.documentElement.scrollWidth, document.body.scrollWidth],
    wide: Array.from(document.querySelectorAll('.topbar *, #rd-tabs *, #reader *, #rd-sheet *')).filter((e) => {
      if (!e.checkVisibility || !e.checkVisibility()) return false;
      if (e.closest('svg')) return false;
      const r = e.getBoundingClientRect(); return r.width > 0 && (r.right > W + 0.5 || r.left < -0.5);
    }).slice(0, 3).map((e) => e.tagName + '.' + e.className),
  }), w);
  expect(Math.max(...r.sw), label).toBeLessThanOrEqual(w);
  expect(r.wide, label).toEqual([]);
}

function freshMarket() {
  return { updated_at: iso(25 * MIN), note_th: 'หมายเหตุแหล่งราคาทดสอบ', items: [
    { key: 'brent', label_th: 'น้ำมัน Brent', value: '116.40', unit: '$/บาร์เรล', change_th: '+1.2% จากปิดก่อนหน้า', trend: 'up', as_of: iso(30 * MIN), source: 'https://www.cnbc.com/quotes/@LCO.1' },
    { key: 'gold_th', label_th: 'ทองคำแท่งไทย', value: '64400', unit: 'บาท', change_th: 'ค่าเดิม (ดึงราคาไม่สำเร็จรอบนี้)', trend: 'flat', as_of: iso(40 * MIN), source: 'https://www.goldtraders.or.th/' },
  ] };
}
function freshHeadlines() {
  return { updated_at: iso(20 * MIN), items: [
    { id: 'n1', conflict_id: 'ukraine_russia', title_th: 'ข่าวทดสอบหนึ่งของยูเครน', time: iso(HOUR), source: 'https://www.reuters.com/a', source_name: 'Reuters' },
    { id: 'n2', conflict_id: 'economy', title_th: 'ข่าวทดสอบสองของเศรษฐกิจ', time: iso(2 * HOUR), source: 'https://www.cnbc.com/b', source_name: 'CNBC' },
  ] };
}
const freshStatus = () => ({ updated_at: iso(25 * MIN), run_count: 1, ok: true, message_th: 'สำเร็จ' });
function freshDisasters() {
  return { updated: iso(30 * MIN), checked: iso(30 * MIN), ok: true, message_th: '', items: [
    { id: 'x1', type: 'flood', title_th: 'น้ำท่วมทดสอบ', country_th: 'ไทย', lat: 13, lon: 100, start: iso(5 * HOUR), updated: iso(HOUR), alert_level: 'red', severity_th: 'ทดสอบความรุนแรง', source_url: 'https://www.gdacs.org/x', source_name: 'GDACS' },
  ] };
}
function writeFresh() { writeData('market', freshMarket()); writeData('headlines', freshHeadlines()); writeData('status', freshStatus()); writeData('disasters', freshDisasters()); }

// Bangkok wall clock in the page's own format: the test works it out from the time it wrote, so nothing is frozen
function bkk(isoStr) {
  const M = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];
  const d = new Date(Date.parse(isoStr) + 7 * HOUR), p = (n) => ('0' + n).slice(-2);
  return `${d.getUTCDate()} ${M[d.getUTCMonth()]} ${d.getUTCFullYear() + 543} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} น.`;
}

test.beforeEach(() => resetData());
test.afterAll(() => resetData());

test.describe('defaults and the switch', () => {
  for (const [w, h, want] of [[360, 740, 'read'], [390, 844, 'read'], [600, 900, 'read'], [601, 900, 'map'], [1440, 900, 'map']]) {
    test(`first visit at ${w}px opens the ${want === 'read' ? 'reading' : 'map'} view`, async ({ browser }) => {
      const { ctx, page } = await open(browser, w, h);
      await page.goto(URL.full);
      if (want === 'read') await expectRead(page); else await expectMap(page);
      expect(await stored(page), 'a default is not a choice').toBeNull();
      await ctx.close();
    });
  }

  test('the switch works both ways and the choice is remembered (desktop starts on the map)', async ({ browser }) => {
    const { ctx, page } = await open(browser, 1440, 900);
    const errors = collectErrors(page);
    await page.goto(URL.full); await ready(page);
    await expectMap(page);
    await expect(page.locator('#stage canvas')).toHaveCount(1, { timeout: 15000 });

    await page.evaluate(() => document.getElementById('vw-read').click());
    await expectRead(page);
    expect(await stored(page)).toBe('read');
    expect(page.url()).toContain('view=read');
    await expect(page.locator('#r-front h2')).toBeVisible();

    await page.reload(); await ready(page);
    await expectRead(page);
    await page.goto(URL.full); await ready(page);   // no parameter: the stored choice decides
    await expectRead(page);

    await page.click('#vw-map');
    await expectMap(page);
    expect(await stored(page)).toBe('map');
    expect(page.url()).toContain('view=map');
    await page.goto(URL.full); await ready(page);
    await expectMap(page);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('a phone that chose the map stays on the map, and the quiet button under a chapter goes there too', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
    await go(page, 'gold');
    await page.click('#r-to-map');
    await expectMap(page);
    await page.goto(URL.full); await ready(page);
    await expectMap(page);
    await page.click('#vw-read');
    await expectRead(page);
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('?view= selects the view for that link, wins over a stored choice and does not overwrite it', async ({ browser }) => {
    const desk = await open(browser, 1440, 900);
    await desk.page.goto(URL.full + '?view=read');
    await expectRead(desk.page);
    expect(await stored(desk.page)).toBeNull();
    await desk.page.goto(URL.full + '?view=nonsense');
    await expectMap(desk.page);
    await desk.ctx.close();

    const phone = await open(browser, 390, 844);
    await phone.page.goto(URL.full + '?view=map');
    await expectMap(phone.page);
    expect(await stored(phone.page)).toBeNull();
    await phone.page.click('#vw-read');          // stored: read
    await phone.page.goto(URL.full + '?poll=60000&view=map');
    await expectMap(phone.page);
    expect(await stored(phone.page)).toBe('read');
    await phone.ctx.close();
  });

  test('blocked storage does not break anything', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844, { colorScheme: 'dark' });
    const errors = collectErrors(page);
    await page.addInitScript(() => {
      Storage.prototype.getItem = function () { throw new Error('blocked'); };
      Storage.prototype.setItem = function () { throw new Error('blocked'); };
      Storage.prototype.removeItem = function () { throw new Error('blocked'); };
    });
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
    expect(await page.evaluate(() => document.documentElement.getAttribute('data-rd-theme'))).toBe('night');
    await page.click('#rd-aa summary');
    await page.click('[data-rd-theme-set="sepia"]');
    await page.click('#rd-size-down');
    expect(await page.evaluate(() => [document.documentElement.getAttribute('data-rd-theme'), document.documentElement.getAttribute('data-rd-size')])).toEqual(['sepia', '2']);
    await page.mouse.click(195, 500);
    await go(page, 'conflicts');
    await page.evaluate(() => window.scrollTo(0, 800));
    await page.waitForTimeout(600);   // the place would be saved here
    await page.click('#vw-map', { force: true }).catch(() => {});
    await page.evaluate(() => document.getElementById('vw-map').click());
    await expectMap(page);
    await page.click('#vw-read');
    await expectRead(page);
    expect(errors).toEqual([]);
    await ctx.close();
  });
});

test.describe('one chapter at a time', () => {
  for (const w of [360, 390]) {
    test(`at ${w}px each chapter's first state stays short and only one is on screen`, async ({ browser }) => {
      const { ctx, page } = await open(browser, w, 844);
      const errors = collectErrors(page);
      await page.goto(URL.full + '?view=read'); await ready(page);
      const heights = {};
      for (const c of PAGES) {
        await go(page, c);
        expect(await page.locator('#reader .rd-sec.on').count()).toBe(1);
        expect(await onChapter(page)).toBe(SEC(c));
        expect((await page.locator('#' + SEC(c)).innerText()).trim().length, c).toBeGreaterThan(40);
        await expect(page.locator(`#${SEC(c)} h2`).first()).toBeVisible();
        heights[c] = await page.evaluate(() => document.documentElement.scrollHeight);
        expect(heights[c], c).toBeLessThanOrEqual(c === 'front' ? 1000 : MAX_CHAPTER_PX);
        expect(await page.evaluate(() => document.querySelectorAll('#reader details[open]').length), 'closed by default').toBe(0);
      }
      console.log(`heights at ${w}px`, JSON.stringify(heights), 'total', Object.values(heights).reduce((a, b) => a + b, 0));
      expect(errors).toEqual([]);
      await ctx.close();
    });
  }

  test('a phone gets a fixed tab bar; a desktop gets the same tabs as the strip under the masthead', async ({ browser }) => {
    const ph = await open(browser, 390, 844);
    await ph.page.goto(URL.full + '?view=read'); await ready(ph.page);
    await go(ph.page, 'conflicts');
    await ph.page.evaluate(() => window.scrollTo(0, 900));
    const bar = await ph.page.locator('#rd-tabs').boundingBox();
    expect(bar.y + bar.height).toBeCloseTo(844, 0);
    expect(await ph.page.locator('#rd-tabs a').count()).toBe(7);
    await ph.ctx.close();
    const de = await open(browser, 1440, 900);
    await de.page.goto(URL.full + '?view=read'); await ready(de.page);
    const strip = await de.page.locator('#rd-tabs').boundingBox();
    expect(strip.y).toBeLessThan(130);
    const r = await de.page.locator('#reader').boundingBox();
    expect(r.width, 'the page uses the width').toBeGreaterThan(1100);
    await go(de.page, 'conflicts');
    const cols = await de.page.locator('#r-conflicts .rd-grid').evaluate((e) => getComputedStyle(e).gridTemplateColumns.split(' ').length);
    expect(cols, 'more than one column').toBeGreaterThan(1);
    await de.page.evaluate(() => window.scrollTo(0, 500));
    expect((await de.page.locator('#rd-tabs').boundingBox()).y, 'the strip stays in reach').toBe(0);
    await de.ctx.close();
  });

  test('previous and next at the end of each chapter walk through the book', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read#latest'); await ready(page);
    for (const c of CHAPTERS.slice(1)) {
      await page.click('.rd-sec.on .rd-pager a.next');
      expect(await onChapter(page)).toBe(SEC(c));
      expect(await page.evaluate(() => window.scrollY)).toBe(0);
    }
    await expect(page.locator('.rd-sec.on .rd-pager a.next')).toHaveCount(0);
    await page.click('.rd-sec.on .rd-pager a.prev');
    expect(await onChapter(page)).toBe('r-economy');
    await ctx.close();
  });

  test('tabs answer to the mouse and keyboard, and mark the chapter they stand on', async ({ browser }) => {
    const { ctx, page } = await open(browser, 1440, 900);
    await page.goto(URL.full + '?view=read'); await ready(page);
    const cur = () => page.evaluate(() => document.querySelector('#rd-tabs a[aria-current="page"]').getAttribute('data-sec'));
    expect(await cur()).toBe('r-front');
    await page.focus('#rd-tabs a[data-sec="r-prices"]');
    await page.keyboard.press('Enter');
    expect(await cur()).toBe('r-prices');
    expect(page.url()).toContain('#prices');
    expect(await page.evaluate(() => document.activeElement.tagName + '#' + document.activeElement.closest('section').id), 'focus moves to the new chapter').toBe('H2#r-prices');
    await page.keyboard.press('ArrowRight');
    expect(await cur()).toBe('r-conflicts');
    await page.keyboard.press('ArrowLeft');
    await page.keyboard.press('ArrowLeft');
    expect(await cur()).toBe('r-latest');
    // arrows from inside the tabs keep the focus in the tabs
    await page.focus('#rd-tabs a[data-sec="r-latest"]');
    await page.keyboard.press('ArrowRight');
    expect(await page.evaluate(() => document.activeElement.getAttribute('data-sec'))).toBe('r-prices');
    await ctx.close();
  });

  test('a swipe changes chapter; a scroll, a touch at the edge and the end of the book do not', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read#latest'); await ready(page);
    await swipe(page, 300, 80);
    expect(await onChapter(page)).toBe('r-prices');
    await swipe(page, 300, 80);
    expect(await onChapter(page)).toBe('r-conflicts');
    expect(page.url()).toContain('#conflicts');
    await swipe(page, 80, 300);
    expect(await onChapter(page)).toBe('r-prices');
    await page.goBack();
    expect(await onChapter(page), 'each chapter is a step back').toBe('r-conflicts');
    // too short, mostly vertical, from the phone's own back-gesture edge
    await swipe(page, 200, 170);
    expect(await onChapter(page)).toBe('r-conflicts');
    await swipe(page, 200, 120, 300, 600);
    expect(await onChapter(page)).toBe('r-conflicts');
    await swipe(page, 8, 240);
    expect(await onChapter(page)).toBe('r-conflicts');
    // the transform never survives the gesture
    expect(await page.locator('#r-conflicts').evaluate((e) => e.style.transform)).toBe('');
    // no further than the last chapter, and no leftover shift
    await go(page, 'gold');
    await swipe(page, 300, 80);
    expect(await onChapter(page)).toBe('r-gold');
    await noHScroll(page, 'after a swipe at the end');
    // the first page resists too
    await go(page, 'front');
    await swipe(page, 80, 300);
    expect(await onChapter(page)).toBe('r-front');
    // a swipe across a link does not follow the link
    await go(page, 'conflicts');
    const row = await page.locator('#r-conflict-list a').first().boundingBox();
    await swipe(page, 300, 60, Math.max(120, row.y + 10));
    expect(await sheetOpen(page)).toBe(false);
    expect(await onChapter(page)).toBe('r-disasters');
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('the back button closes an article, then walks back through chapters to where the reader was', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read'); await ready(page);
    await go(page, 'conflicts');
    await page.evaluate(() => window.scrollTo(0, 900));
    const link = page.locator('#r-conflict-list > li').nth(1).locator('a');
    await link.click();
    await expect(page.locator('#rd-sheet')).toBeVisible();
    expect(page.url()).toContain('#conflicts/');
    const y = await page.evaluate(() => window.scrollY);
    await page.goBack();
    await expect(page.locator('#rd-sheet')).toBeHidden();
    expect(await onChapter(page)).toBe('r-conflicts');
    expect(await page.evaluate(() => window.scrollY), 'the chapter is where it was').toBe(y);
    expect(await page.evaluate((id) => document.activeElement === document.querySelectorAll('#r-conflict-list > li')[1].querySelector('a'), 0), 'focus returns to the link').toBe(true);
    await go(page, 'gold');
    await page.goBack();
    expect(await onChapter(page)).toBe('r-conflicts');
    expect(await page.evaluate(() => window.scrollY), 'going back returns to the same spot').toBe(y);
    await page.goBack();
    expect(await onChapter(page)).toBe('r-front');
    await page.goForward();
    expect(await onChapter(page)).toBe('r-conflicts');
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('deep links: a chapter, an article, an old-style chapter link, and addresses that lead nowhere', async ({ browser }) => {
    const c = world.conflicts.slice().sort((a, b) => b.intensity - a.intensity)[1];
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read#economy'); await ready(page);
    expect(await onChapter(page)).toBe('r-economy');
    await page.goto('about:blank');
    await page.goto(URL.full + `?view=read#conflicts/${c.id}`); await ready(page);
    await expect(page.locator('#rd-sheet')).toBeVisible();
    await expect(page.locator('#rd-sheet-title')).toHaveText(c.name_th);
    expect(await onChapter(page)).toBe('r-conflicts');
    await page.reload(); await ready(page);
    await expect(page.locator('#rd-sheet-title')).toHaveText(c.name_th);
    // going back from a link straight to an article lands on its chapter, still on the site
    await page.goBack();
    await expect(page.locator('#rd-sheet')).toBeHidden();
    expect(await onChapter(page)).toBe('r-conflicts');
    expect(page.url()).toContain(URL.full);
    await page.goto('about:blank');
    await page.goto(URL.full + '?view=read#r-gold'); await ready(page);
    expect(await onChapter(page)).toBe('r-gold');
    await page.goto('about:blank');
    await page.goto(URL.full + '?view=read#nowhere'); await ready(page);
    expect(await onChapter(page)).toBe('r-front');
    await page.goto('about:blank');
    await page.goto(URL.full + '?view=read#conflicts/no_such_thing'); await ready(page);
    await expect(page.locator('#rd-sheet')).toBeHidden();
    expect(await onChapter(page)).toBe('r-conflicts');
    expect(page.url()).not.toContain('no_such_thing');
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('the address names the view and the chapter together', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read'); await ready(page);
    await go(page, 'prices');
    expect(page.url()).toMatch(/\?view=read#prices$/);
    await page.click('#vw-map');
    await expectMap(page);
    await page.click('#vw-read');
    await expectRead(page);
    expect(await onChapter(page)).toBe('r-prices');
    await ctx.close();
  });
});

test.describe('the front page', () => {
  test('at 390x844 the masthead, date, headline, key numbers and every entry are on the first screen, with no scrolling', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    if (!LIVE_EMBED) await page.clock.setFixedTime(new Date(FIXTURE_NOON));   // today's data is checked at today's clock
    await page.goto(URL.full + '?view=read'); await ready(page);
    await expect(page.locator('#r-banner')).toBeHidden();
    const r = await page.evaluate(() => {
      const tabs = document.getElementById('rd-tabs').getBoundingClientRect().top;
      const q = (s) => Array.from(document.querySelectorAll(s));
      const inView = (e) => { const b = e.getBoundingClientRect(); return b.top >= 0 && b.bottom <= tabs + 0.5 && b.height > 0; };
      return {
        scroll: document.documentElement.scrollHeight, tabs,
        parts: Object.fromEntries(['#title', '#rd-today', '#rd-updated', '#r-front h2', '#rd-nums'].map((s) => [s, inView(document.querySelector(s))])),
        tiles: q('.rd-tile').map((e) => [e.getAttribute('data-tile'), inView(e)]),
        cells: q('#rd-nums .rd-num').map((e) => [e.querySelector('.v').textContent, e.querySelector('.rd-mv').className]),
      };
    });
    expect(r.scroll, 'nothing to scroll').toBeLessThanOrEqual(844);
    expect(Object.values(r.parts).every(Boolean), JSON.stringify(r.parts)).toBe(true);
    expect(r.tiles.map((t) => t[0]).sort()).toEqual(['conflicts', 'disasters', 'economy', 'gold', 'latest']);
    expect(r.tiles.filter((t) => !t[1])).toEqual([]);
    expect(r.cells.length).toBeGreaterThanOrEqual(3);
    expect(r.cells.length).toBeLessThanOrEqual(4);
    await expect(page.locator('#r-front h2')).toHaveText(world.analysis_th.headline);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('with the page\'s warning line showing, the headline and the numbers still come first', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.nodata + '?view=read'); await ready(page);
    await expect(page.locator('#r-banner')).toBeVisible();
    const tabs = (await page.locator('#rd-tabs').boundingBox()).y;
    const nums = await page.locator('#rd-nums').boundingBox();
    expect(nums.y + nums.height).toBeLessThanOrEqual(tabs);
    await ctx.close();
  });

  test('while the first files are on their way the page has its final shape and shows no value about to change', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    let release;
    const gate = new Promise((r) => { release = r; });
    await page.route(/data\/[a-z_]+\.json/, async (route) => { await gate; await route.continue(); });
    await page.goto(URL.full + '?view=read');
    await expect(page.locator('#r-front h2')).toHaveText(world.analysis_th.headline);
    await expect(page.locator('#rd-nums .rd-num')).toHaveCount(4);
    await expect(page.locator('#rd-nums .rd-num .v').first()).toHaveText('—');
    await expect(page.locator('.rd-tile[data-tile="gold"] .big')).toContainText('—');
    await expect(page.locator('.rd-tile[data-tile="latest"]')).toContainText('กำลังโหลดข่าวล่าสุด');
    const before = await page.locator('.rd-tile[data-tile="economy"]').boundingBox();
    release();
    await ready(page);
    await expect(page.locator('#rd-nums .rd-num .v').first()).not.toHaveText('—');
    const after = await page.locator('.rd-tile[data-tile="economy"]').boundingBox();
    expect(Math.abs(after.y - before.y), 'nothing jumps when the data arrives').toBeLessThanOrEqual(12);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('the entries carry today\'s data and lead to their chapters', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read'); await ready(page);
    const conf = world.conflicts.slice().sort((a, b) => b.intensity - a.intensity);
    const dz = seed('disasters').items, news = seed('headlines').items, market = seed('market').items;
    const tile = (k) => page.locator(`.rd-tile[data-tile="${k}"]`);
    await expect(tile('conflicts')).toContainText(conf[0].name_th);
    await expect(tile('conflicts')).toContainText(`${conf.length} เรื่อง`);
    await expect(tile('conflicts').locator('.rd-meter')).toHaveAttribute('aria-label', `ระดับ ${conf[0].intensity} จาก 5`);
    await expect(tile('latest')).toContainText(news[0].title_th.slice(0, 12));
    await expect(tile('latest')).toContainText(`${news.length} ข่าว`);
    await expect(tile('economy')).toContainText(`${world.economies.length} ประเทศ`);
    await expect(tile('disasters')).toContainText(`${dz.length} เหตุการณ์`);
    expect(await tile('gold').locator('svg').count(), 'the gold line from the recorded history').toBe(1);
    await expect(page.locator('#rd-nums')).toContainText(`${market.length} รายการ`);
    // real direction, with a sign and an arrow, never colour alone
    const cells = await page.locator('#rd-nums .rd-mv').evaluateAll((els) => els.map((e) => [e.className, e.textContent]));
    for (const [cls, text] of cells) {
      if (/\bup\b/.test(cls)) expect(text).toMatch(/▲\+/);
      else if (/\bdown\b/.test(cls)) expect(text).toMatch(/▼−|▼-/);
    }
    for (const k of ['conflicts', 'latest', 'economy', 'disasters', 'gold']) {
      await tile(k).click();
      expect(await onChapter(page)).toBe(SEC(k));
      await go(page, 'front');
    }
    await page.click('#rd-nums');
    expect(await onChapter(page)).toBe('r-prices');
    await go(page, 'front');
    await page.click('#r-front .rd-lead-link');
    expect(await onChapter(page)).toBe('r-latest');
    await ctx.close();
  });

  test('the date is today in Bangkok, from the clock, and follows midnight', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const t = Date.parse('2031-03-03T16:30:00Z');   // already the 3rd of March 23:30 in Bangkok
    await page.clock.setFixedTime(new Date(t));
    await page.goto(URL.full + '?view=read'); await ready(page);
    await expect(page.locator('#rd-today')).toHaveText('วันจันทร์ที่ 3 มี.ค. 2574');
    await page.clock.setFixedTime(new Date(t + HOUR));
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await page.waitForTimeout(2200);
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
    await expect(page.locator('#rd-today')).toHaveText('วันอังคารที่ 4 มี.ค. 2574', { timeout: 70000 });
    await ctx.close();
  });
});

test.describe('chapters', () => {
  for (const [name, w, h] of [['phone', 390, 844], ['desktop', 1440, 900]]) {
    test(`latest: headline, top news with sources, the analysis opens as articles (${name})`, async ({ browser }) => {
      const { ctx, page } = await open(browser, w, h);
      const errors = collectErrors(page);
      await page.goto(URL.full + '?view=read#latest'); await ready(page);
      await expect(page.locator('#r-latest .rd-lede')).toHaveText(world.analysis_th.headline);
      const news = seed('headlines').items;
      await expect(page.locator('#r-news > li')).toHaveCount(Math.min(5, news.length));
      await expect(page.locator('#r-news > li').first()).toContainText(news[0].title_th);
      await expect(page.locator('#r-news > li a').first()).toHaveAttribute('href', news[0].source);
      await expect(page.locator('#r-news > li a').first()).toHaveAttribute('target', '_blank');
      if (news.length > 5) {
        const more = page.locator('details[data-rd="news-all"]');
        await expect(more.locator('summary')).toContainText(`ดูทั้งหมด ${news.length} ข่าว`);
        await more.locator('summary').click();
        await expect(page.locator('.rd-news-more > li')).toHaveCount(news.length - 5);
      }
      for (const [key, text] of [['thailand', world.analysis_th.thailand], ['analysis', world.analysis_th.points[0]], ['risks', world.analysis_th.risks[0]]]) {
        await page.click(`#r-latest a[href="#latest/${key}"]`);
        await expect(page.locator('#rd-sheet')).toContainText(text);
        await page.click('#rd-sheet-close');
        await expect(page.locator('#rd-sheet')).toBeHidden();
      }
      expect(errors).toEqual([]);
      await ctx.close();
    });
  }

  test('prices: a table with its digits lined up, direction in colour, arrow and sign, source one tap away', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read#prices'); await ready(page);
    const market = seed('market');
    await expect(page.locator('#r-price-list li[data-key]')).toHaveCount(market.items.length);
    await expect(page.locator('#r-prices .rd-fresh')).toContainText(bkk(market.updated_at));
    const edges = await page.locator('#r-price-list .val').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().right));
    expect(edges.every((r) => Math.abs(r - edges[0]) < 0.6), 'the numbers end on one line').toBe(true);
    const chg = await page.locator('#r-price-list .rd-mv').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().right));
    expect(chg.every((r) => Math.abs(r - chg[0]) < 0.6), 'so do the changes').toBe(true);
    const rows = await page.locator('#r-price-list .rd-prow').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().height));
    expect(Math.min(...rows)).toBeGreaterThanOrEqual(44);
    const up = market.items.find((i) => /^\+/.test(i.change_th)), down = market.items.find((i) => /^[−-]/.test(i.change_th));
    if (up) await expect(page.locator(`#r-price-list li[data-key="${up.key}"] .rd-mv.up`)).toContainText('▲+');
    if (down) await expect(page.locator(`#r-price-list li[data-key="${down.key}"] .rd-mv.down`)).toContainText('▼');
    const it = market.items[0];
    await page.click(`#r-price-list li[data-key="${it.key}"] a`);
    await expect(page.locator('#rd-sheet')).toContainText(it.change_th);
    await expect(page.locator('#rd-sheet .rd-srcs a')).toHaveAttribute('href', it.source);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('digits share one width where they are compared', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read#prices'); await ready(page);
    const r = await page.evaluate(async () => {
      await document.fonts.ready;
      const span = document.createElement('span'), host = document.querySelector('#r-price-list .val');
      span.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap';
      host.appendChild(span);
      const w = (t) => { span.textContent = t; return span.getBoundingClientRect().width; };
      const out = ['1111', '0000', '7777', '8888'].map(w);
      span.remove();
      return out;
    });
    expect(Math.max(...r) - Math.min(...r)).toBeLessThan(0.6);
    await ctx.close();
  });

  test('conflicts: the most severe as large stories, severity as a meter plus words, the rest behind one button', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read#conflicts'); await ready(page);
    const conf = world.conflicts.slice().sort((a, b) => b.intensity - a.intensity);
    await expect(page.locator('#r-conflict-list > li')).toHaveCount(3);
    const leadH = await page.locator('#r-conflict-list > li').first().evaluate((e) => e.getBoundingClientRect().height);
    const rowH = await page.locator('#r-conflict-rows > li').first().evaluate((e) => e.getBoundingClientRect().height);
    expect(leadH, 'a lead is a different object from a row').toBeGreaterThan(rowH * 2);
    await expect(page.locator('#r-conflict-list > li').first().locator('h3')).toHaveText(conf[0].name_th);
    await expect(page.locator('#r-conflict-list > li').first()).toContainText(conf[0].status_th);
    await expect(page.locator('#r-conflict-list > li').first().locator('.rd-map svg circle').first()).toBeVisible();
    const more = page.locator('details[data-rd="conf-rest"]');
    await expect(more.locator('> summary')).toContainText(`ดูทั้งหมด ${conf.length} รายการ`);
    await expect(page.locator('#r-conflict-more')).toBeHidden();
    await more.locator('> summary').click();
    await expect(page.locator('#r-conflicts li.rd-conf')).toHaveCount(conf.length);
    const levels = await page.locator('#r-conflicts li.rd-conf').evaluateAll((els) => els.map((e) => +e.getAttribute('data-intensity')));
    expect(levels).toEqual(levels.slice().sort((a, b) => b - a));
    const words = { 5: 'รุนแรงที่สุด', 4: 'รุนแรงมาก', 3: 'รุนแรงปานกลาง', 2: 'รุนแรงน้อย', 1: 'รุนแรงน้อยมาก' };
    for (const lvl of [5, 4, 3, 2, 1]) {
      const r = page.locator(`#r-conflicts li[data-intensity="${lvl}"]`).first();
      if (!(await r.count())) continue;
      await expect(r.locator('.rd-level b')).toHaveText(words[lvl]);
      await expect(r.locator('.rd-meter')).toHaveAttribute('aria-label', `ระดับ ${lvl} จาก 5`);
      expect(await r.locator('.rd-meter i').count()).toBe(5);
    }
    expect(await page.locator('#r-conflicts li.rd-conf .rd-map').count(), 'every conflict has its locator').toBe(conf.length);
    // the article holds the rest, with its sources
    await page.locator('#r-conflict-list > li').first().locator('a').click();
    await expect(page.locator('#rd-sheet')).toContainText(conf[0].summary_th);
    await expect(page.locator('#rd-sheet .rd-srcs a')).toHaveCount(conf[0].sources.length);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('a locator shows land around the right point, across the date line too, and asks the network for nothing', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const asked = [];
    page.on('request', (r) => { if (/^http:\/\/127/.test(r.url())) asked.push(r.url().replace(/\?.*/, '')); });
    await page.goto(URL.full + '?view=read#conflicts'); await ready(page);
    const dots = await page.locator('#r-conflict-list .rd-map path').first().evaluate((p) => (p.getAttribute('d').match(/M/g) || []).length);
    expect(dots, 'a real piece of map').toBeGreaterThan(40);
    const data = asked.filter((u) => /\/data\//.test(u)).map((u) => u.replace(/.*\/data\//, ''));
    expect(asked.filter((u) => !/\/data\//.test(u) && !/\/global-analysis\/$/.test(u)), 'no other file from this site').toEqual([]);
    expect(new Set(data).size).toBe(data.length === 0 ? 0 : new Set(data).size);
    await ctx.close();
    writeFresh();
    const doc = freshDisasters();
    doc.items[0].lon = 179.5; doc.items[0].lat = -18;
    writeData('disasters', doc);
    const o = await open(browser, 390, 844);
    await o.page.goto(URL.mutable + '?view=read#disasters'); await ready(o.page);
    const pacific = await o.page.locator('#r-dz-list .rd-map path').first().evaluate((p) => (p.getAttribute('d').match(/M/g) || []).length);
    expect(pacific, 'land on both sides of 180 degrees').toBeGreaterThan(5);
    await o.ctx.close();
  });

  test('disasters are called the latest, with each event\'s date or range from the data, and none is filtered out', async ({ browser }) => {
    writeFresh();
    const ended = '2026-10-01T05:00:00Z';
    const doc = freshDisasters();
    doc.items = [
      { ...doc.items[0], id: 'range', title_th: 'พายุที่จบแล้ว', type: 'cyclone', alert_level: 'red', start: '2026-09-20T00:00:00Z', end: ended },
      { ...doc.items[0], id: 'one', title_th: 'แผ่นดินไหวเก่า', type: 'earthquake', alert_level: 'orange', start: '2026-09-22T14:33:40Z', end: '2026-09-22T14:33:40Z' },
    ];
    for (let i = 0; i < 8; i++) doc.items.push({ ...doc.items[0], id: 'extra' + i, title_th: 'เหตุการณ์ทดสอบ ' + i, type: 'flood', alert_level: 'green' });
    writeData('disasters', doc);
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.mutable + '?view=read#disasters'); await ready(page);
    await expect(page.locator('#r-disasters h2')).toHaveText('ภัยพิบัติล่าสุด');
    await expect(page.locator('#r-dz-list > li[data-id="range"] .rd-dz-date')).toHaveText('20 ก.ย. 2569 – 1 ต.ค. 2569');
    await expect(page.locator('#r-dz-list > li[data-id="one"] .rd-dz-date')).toContainText('22 ก.ย. 2569 (');
    await expect(page.locator('#r-dz-list > li[data-id="one"] .rd-dz-date')).toContainText('วันที่แล้ว');
    await expect(page.locator('#r-dz-list > li[data-id="range"] .rd-al')).toContainText('เตือนระดับแดง');
    expect(await page.locator('#r-dz-list > li').first().locator('.rd-map').count()).toBe(1);
    expect(await page.locator('#r-dz-list > li').nth(1).locator('.rd-ic svg').count(), 'a type icon').toBe(1);
    await page.locator('details[data-rd="dz-rest"] > summary').click();
    await expect(page.locator('#r-disasters li.rd-dz')).toHaveCount(doc.items.length);
    await page.locator('#r-dz-list > li[data-id="range"] a').click();
    await expect(page.locator('#rd-sheet .rd-srcs a')).toHaveAttribute('href', 'https://www.gdacs.org/x');
    await expect(page.locator('#rd-sheet')).toContainText('ทดสอบความรุนแรง');
    await page.click('#rd-sheet-close');
    await page.click('#vw-map');
    await page.click('.tab[data-tab="disasters"]');
    await expect(page.locator('#dz-head .sec-title')).toHaveText('ภัยพิบัติล่าสุด');
    const html = await (await page.request.get(URL.mutable)).text();
    expect(html).not.toContain('ภัยพิบัติขณะนี้');
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('economy: one comparison that re-ranks by the chosen figure, with Thailand marked and notes one tap away', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read#economy'); await ready(page);
    const ec = world.economies;
    await expect(page.locator('#r-econ-list > li')).toHaveCount(ec.length);
    const order = (f) => ec.slice().sort((a, b) => b[f] - a[f]).map((e) => e.iso);
    const onPage = () => page.locator('#r-econ-list > li').evaluateAll((els) => els.map((e) => e.getAttribute('data-iso')));
    expect((await onPage())[0]).toBe(order('gdp_growth_2026')[0]);
    await page.click('.rd-chips button[data-econ="2"]');
    await expect(page.locator('.rd-chips button[data-econ="2"]')).toHaveAttribute('aria-pressed', 'true');
    const infl = ec.slice().sort((a, b) => b.inflation - a.inflation);
    expect((await onPage())[0]).toBe(infl[0].iso);
    await expect(page.locator('#r-econ-list > li').first()).toContainText(String(infl[0].inflation));
    const neg = ec.find((e) => e.gdp_growth_2026 < 0);
    await page.click('.rd-chips button[data-econ="0"]');
    if (neg) await expect(page.locator(`#r-econ-list > li[data-iso="${neg.iso}"] .rd-track i.neg`)).toHaveCount(1);
    await expect(page.locator('#r-econ-list .rd-bar.home')).toContainText('ไทย');
    await expect(page.locator('#r-choke-list > li')).toHaveCount(world.chokepoints.length);
    await expect(page.locator('#r-choke-list > li').first().locator('.rd-meter')).toHaveAttribute('data-max', '3');
    await page.locator('#r-econ-list > li').first().locator('a').click();
    const top = ec.find((e) => e.iso === order('gdp_growth_2026')[0]);
    await expect(page.locator('#rd-sheet')).toContainText(top.note_th);
    await page.click('#rd-sheet-close');
    await page.locator('#r-choke-list > li').first().locator('a').click();
    await expect(page.locator('#rd-sheet')).toContainText(world.chokepoints[0].note_th);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('gold shows one value and one change everywhere, whatever the history says', async ({ browser }) => {
    writeFresh();
    const m = freshMarket();
    m.items.push({ key: 'gold', label_th: 'ทองคำ (spot)', value: '4040.70', unit: '$/ออนซ์', change_th: '+2.86% (+112.45) จากปิดก่อนหน้า', trend: 'up', as_of: iso(10 * MIN), source: 'https://www.swissquote.com/' });
    m.items[1].change_th = 'ประกาศครั้งที่ 46 เวลา 16:11 น. +50 บาท · +1,900 จากวันก่อน'; m.items[1].trend = 'up';
    writeData('market', m);
    // a previous-day point that would make the map tile say something else (+3.1%); the map view keeps doing that
    writeData('gold_history', { updated_at: iso(HOUR), points: [{ spot: 3919, spot_as_of: iso(26 * HOUR), th_sell: 62500, th_as_of: iso(26 * HOUR) }] });
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.mutable + '?view=read'); await ready(page);
    const inFront = await page.locator('.rd-tile[data-tile="gold"]').innerText();
    expect(inFront).toContain('64,400');
    expect(inFront).toContain('+1,900');
    expect((await page.locator('#rd-nums .rd-num').first().innerText())).toContain('64,400');
    expect((await page.locator('#rd-nums .rd-num').first().innerText())).toContain('+1,900');
    await go(page, 'prices');
    const pr = (k) => page.locator(`#r-price-list li[data-key="${k}"]`);
    await expect(pr('gold').locator('.chg')).toContainText('+2.86%');
    await expect(pr('gold_th').locator('.chg')).toContainText('+1,900');
    const prSpot = await pr('gold').locator('.val').innerText(), prTh = await pr('gold_th').locator('.val').innerText();
    await go(page, 'gold');
    expect(await page.locator('#r-gold-spot .num').innerText()).toBe(prSpot);
    expect(await page.locator('#r-gold-th .num').innerText()).toBe(prTh);
    await expect(page.locator('#r-gold-spot .chg')).toContainText('+2.86%');
    await expect(page.locator('#r-gold-spot')).toContainText('(+112.45) จากปิดก่อนหน้า');
    await expect(page.locator('#r-gold-th .chg')).toContainText('+1,900');
    await expect(page.locator('#r-gold-th')).toContainText('จากวันก่อน');
    await expect(page.locator('#r-gold-spot .u')).toHaveText('$/ออนซ์');
    expect(await page.locator('#r-gold .rd-srcs a').count()).toBe(2);
    await page.click('#vw-map');
    await page.click('.tab[data-tab="gold"]');
    if (!LIVE_EMBED) await expect(page.locator('#gold-tile-main .delta')).toContainText('+3.1%');   // map view untouched
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('a price held over from the last round says so and takes no direction', async ({ browser }) => {
    writeFresh();
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.mutable + '?view=read#prices'); await ready(page);
    const c = page.locator('#r-price-list li[data-key="gold_th"] .chg');
    await expect(c).toHaveText('ค่าเดิม');
    await expect(c).toHaveClass(/held/);
    await ctx.close();
  });

  test('every source link in the data can be reached', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read'); await ready(page);
    const hrefsOn = (sel) => page.locator(sel).evaluateAll((els) => els.map((e) => e.getAttribute('href')));
    const openArticle = async (hash) => {
      await page.evaluate((h) => { location.hash = h; }, hash);
      await expect(page.locator('#rd-sheet')).toBeVisible();
      const a = await hrefsOn('#rd-sheet a[target="_blank"]');
      await page.click('#rd-sheet-close');
      await expect(page.locator('#rd-sheet')).toBeHidden();
      return a;
    };
    for (const c of world.conflicts) {
      const got = await openArticle(`conflicts/${c.id}`);
      for (const u of c.sources || []) expect(got, c.id).toContain(u);
    }
    for (const e of world.economies) {
      const got = await openArticle(`economy/${e.iso}`);
      for (const u of e.sources || []) expect(got, e.iso).toContain(u);
    }
    let i = 0;
    for (const c of world.chokepoints) {
      const got = await openArticle(`economy/choke-${i++}`);
      for (const u of c.sources || []) expect(got, c.name_th).toContain(u);
    }
    for (const it of seed('disasters').items) {
      const got = await openArticle(`disasters/${it.id}`);
      for (const u of [it.source_url, it.alt_source_url].filter(Boolean)) expect(got, it.id).toContain(u);
    }
    for (const it of seed('market').items) {
      const got = await openArticle(`prices/${it.key}`);
      if (it.source) expect(got, it.key).toContain(it.source);
    }
    await go(page, 'latest');
    await openAll(page);
    const news = await hrefsOn('#r-latest a[target="_blank"]');
    for (const n of seed('headlines').items) if (n.source) expect(news).toContain(n.source);
    await ctx.close();
  });

  test('no Thai digits anywhere in the reading view, in any page or article', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read'); await ready(page);
    const THAI = /[๐-๙]/;
    const look = async (where) => {
      const t = await page.evaluate(() => [document.querySelector('.topbar').innerText, document.getElementById('rd-tabs').innerText, document.getElementById('reader').innerText, document.getElementById('rd-sheet').innerText, Array.from(document.querySelectorAll('[aria-label]')).map((e) => e.getAttribute('aria-label')).join(' ')].join('\n'));
      expect(t.match(THAI), where).toBeNull();
      expect(t.match(/\bnull\b|\bNaN\b|undefined|\[object Object\]/), where).toBeNull();
    };
    for (const c of PAGES) { await go(page, c); await openAll(page); await look(c); }
    for (const a of ['latest/analysis', 'latest/risks', 'latest/thailand', `conflicts/${world.conflicts[0].id}`, `economy/${world.economies[0].iso}`, 'economy/choke-0', `prices/${seed('market').items[0].key}`, `disasters/${seed('disasters').items[0].id}`]) {
      await page.evaluate((h) => { location.hash = h; }, a);
      await expect(page.locator('#rd-sheet')).toBeVisible();
      await look(a);
      await page.click('#rd-sheet-close');
    }
    await ctx.close();
  });

  test('the reading-view code has no frozen dates, and the page source no old cadence wording', () => {
    for (const f of ['tools/template.html', 'tools/gold_module.js']) {
      const src = fs.readFileSync(path.join(__dirname, '..', '..', f), 'utf8');
      expect(src.match(/ทุก 4 ชม|every 4 h/g), f).toBeNull();
    }
    const src = fs.readFileSync(path.join(__dirname, '..', '..', 'tools', 'template.html'), 'utf8');
    const a = src.indexOf('/* ================= reading view'), b = src.indexOf('/* ================= view switch');
    expect(a).toBeGreaterThan(0); expect(b).toBeGreaterThan(a);
    const code = src.slice(a, b).split('\n').filter((l) => !/gdp_growth_|series_20/.test(l)).join('\n');   // the field names themselves carry their year
    expect(code.match(/(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)/g)).toBeNull();
    expect(code.match(/\b(25[5-9]\d|20[2-9]\d)\b/g)).toBeNull();
  });
});

test.describe('the article sheet', () => {
  const conf = () => world.conflicts.slice().sort((a, b) => b.intensity - a.intensity);

  test('opens over the chapter, keeps focus inside, closes by button, Escape and the backdrop, and gives focus back', async ({ browser }) => {
    const { ctx, page } = await open(browser, 1440, 900);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read#conflicts'); await ready(page);
    const link = page.locator('#r-conflict-list > li').first().locator('a');
    await link.focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('#rd-sheet')).toBeVisible();
    await expect(page.locator('#rd-sheet')).toHaveAttribute('role', 'dialog');
    await expect(page.locator('#rd-sheet')).toHaveAttribute('aria-modal', 'true');
    await expect(page.locator('#rd-sheet-close')).toBeFocused();
    expect(await page.evaluate(() => document.getElementById('app').hasAttribute('inert'))).toBe(true);
    for (let i = 0; i < 40; i++) {
      await page.keyboard.press('Tab');
      expect(await page.evaluate(() => { const a = document.activeElement; return a === document.body || !!a.closest('#rd-sheet'); }), 'tab stays in the sheet').toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(page.locator('#rd-sheet')).toBeHidden();
    await expect(link).toBeFocused();
    expect(await page.evaluate(() => document.getElementById('app').hasAttribute('inert'))).toBe(false);
    expect(page.url()).toMatch(/#conflicts$/);
    await link.click();
    await page.click('#rd-sheet-close');
    await expect(page.locator('#rd-sheet')).toBeHidden();
    await link.click();
    await page.mouse.click(40, 450);   // outside the page on a desktop
    await expect(page.locator('#rd-sheet')).toBeHidden();
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('colour and type size stay reachable inside an article', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + `?view=read#conflicts/${conf()[0].id}`); await ready(page);
    await expect(page.locator('#rd-sheet #rd-aa')).toBeVisible();
    await page.click('#rd-aa summary');
    await expect(page.locator('.rd-aa-panel')).toBeVisible();
    await page.click('[data-rd-theme-set="night"]');
    expect(await page.evaluate(() => getComputedStyle(document.getElementById('rd-sheet')).backgroundColor)).toBe('rgb(27, 24, 21)');
    const before = await page.evaluate(() => parseFloat(getComputedStyle(document.querySelector('#rd-sheet .rd-art > p:not(.rd-level):not(.rd-fresh):not(.lede):not(.rd-note)')).fontSize));
    await page.click('#rd-size-up');
    const after = await page.evaluate(() => parseFloat(getComputedStyle(document.querySelector('#rd-sheet .rd-art > p:not(.rd-level):not(.rd-fresh):not(.lede):not(.rd-note)')).fontSize));
    expect(after).toBeGreaterThan(before);
    await page.keyboard.press('Escape');   // the panel first
    await expect(page.locator('.rd-aa-panel')).toBeHidden();
    await expect(page.locator('#rd-sheet')).toBeVisible();
    await page.keyboard.press('Escape');   // then the article
    await expect(page.locator('#rd-sheet')).toBeHidden();
    await expect(page.locator('.topbar #rd-aa')).toBeVisible();
    await ctx.close();
  });

  test('the next story replaces this one, so going back still returns to the chapter', async ({ browser }) => {
    const c = conf();
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read#conflicts'); await ready(page);
    await page.locator('#r-conflict-list > li').first().locator('a').click();
    await page.click('.rd-nextart');
    await expect(page.locator('#rd-sheet-title')).toHaveText(c[1].name_th);
    expect(await page.evaluate(() => document.getElementById('rd-sheet').scrollTop)).toBe(0);
    await page.goBack();
    await expect(page.locator('#rd-sheet')).toBeHidden();
    expect(await onChapter(page)).toBe('r-conflicts');
    await ctx.close();
  });

  test('book-like reading in the sheet: looped serif, 17 to 20px, generous lines', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + `?view=read#conflicts/${conf()[0].id}`); await ready(page);
    const r = await page.locator('#rd-sheet .rd-art > p:not(.rd-level):not(.rd-fresh):not(.lede):not(.rd-note)').first().evaluate((e) => { const c = getComputedStyle(e); return [c.fontFamily, parseFloat(c.fontSize), parseFloat(c.lineHeight) / parseFloat(c.fontSize), c.textAlign]; });
    expect(r[0]).toContain('Noto Serif Thai');
    expect(r[1]).toBeGreaterThanOrEqual(17);
    expect(r[1]).toBeLessThanOrEqual(20);
    expect(r[2]).toBeGreaterThanOrEqual(1.7);
    expect(r[3]).toBe('start');
    await ctx.close();
  });
});

test.describe('layout and comfort', () => {
  // the whole reading view measured against the fixed viewport: a phone's innerWidth grows with content that is too wide
  for (const w of [360, 390]) {
    for (const size of [1, 3, 6]) {
      test(`no horizontal overflow at ${w}px, type size ${size}, with everything open, an article and the controls`, async ({ browser }) => {
        const { ctx, page } = await openAs(browser, w, 800, null, size, { reducedMotion: 'reduce' });   // measured at rest, not in the middle of the short slide
        const errors = collectErrors(page);
        await page.goto(URL.full + '?view=read'); await ready(page);
        for (const c of PAGES) {
          await go(page, c);
          await fitsWidth(page, w, `${c} shut`);
          await openAll(page);
          await fitsWidth(page, w, `${c} open`);
        }
        await page.click('#rd-aa summary');
        await fitsWidth(page, w, 'controls');
        const panel = await page.locator('.rd-aa-panel').boundingBox();
        expect(panel.x).toBeGreaterThanOrEqual(0);
        expect(panel.x + panel.width).toBeLessThanOrEqual(w);
        await page.keyboard.press('Escape');
        for (const a of ['latest/analysis', `conflicts/${world.conflicts[0].id}`, `economy/${world.economies[0].iso}`, `prices/${seed('market').items[0].key}`]) {
          await page.evaluate((h) => { location.hash = h; }, a);
          await expect(page.locator('#rd-sheet')).toBeVisible();
          await fitsWidth(page, w, a);
          await page.click('#rd-sheet-close');
        }
        expect(errors).toEqual([]);
        await ctx.close();
      });
    }
  }

  test('long titles today or tomorrow do not break the page', async ({ browser }) => {
    const long = (s) => (s + ' ').repeat(9).trim();
    const unbroken = 'ก'.repeat(70) + 'AVeryLongLatinSourceNameWithoutAnySpaceToBreakOnAtAll';
    writeFresh();
    const news = freshHeadlines();
    news.items[0].title_th = long('ข่าวที่ยาวมากเป็นพิเศษ'); news.items[1].title_th = unbroken; news.items[1].source_name = unbroken;
    writeData('headlines', news);
    const dz = freshDisasters();
    dz.items[0].title_th = long('พายุหมุนเขตร้อนชื่อยาวมาก'); dz.items[0].country_th = long('ประเทศ');
    writeData('disasters', dz);
    const m = freshMarket();
    m.items[0].label_th = long('น้ำมันดิบชนิดพิเศษ'); m.items[0].value = '1234567890.1234';
    writeData('market', m);
    for (const size of [3, 6]) {
      const { ctx, page } = await openAs(browser, 360, 740, null, size, { reducedMotion: 'reduce' });
      const errors = collectErrors(page);
      await page.route(URL.mutable + '?view=read', async (route) => {
        const res = await route.fetch(); let body = await res.text();
        body = body.replace(/"headline":"/, '"headline":"' + long('พาดหัวข่าวที่ยาวกว่าปกติมาก'));
        body = body.replace(/"name_th":"/g, '"name_th":"ชื่อเรื่องที่ยาวกว่าปกติมาก ชื่อเรื่องที่ยาวกว่าปกติมาก ');
        await route.fulfill({ response: res, body });
      });
      await page.goto(URL.mutable + '?view=read'); await ready(page);
      for (const c of PAGES) { await go(page, c); await openAll(page); await fitsWidth(page, 360, `${c} size ${size}`); }
      await go(page, 'front');
      if (size === 3) {
        await expect(page.locator('#r-front h2')).toBeVisible();
        const fs3 = await page.locator('#r-front h2').evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
        expect(fs3, 'a very long headline steps down in size').toBeLessThan(23);
      }
      expect(errors).toEqual([]);
      await ctx.close();
    }
  });

  // scrollWidth cannot see this: .reader{overflow-x:clip} and every rounded tile hide what sticks out, so measure the text itself
  const CLIP_AUDIT = () => {
    const W = document.documentElement.clientWidth, bad = [];
    document.querySelectorAll('#reader .rd-sec.on *, #rd-tabs *, .topbar *').forEach((e) => {
      if (e.closest('svg') || !e.checkVisibility()) return;
      if (!Array.from(e.childNodes).some((x) => x.nodeType === 3 && x.textContent.trim())) return;
      const rg = document.createRange(); rg.selectNodeContents(e);
      const rs = Array.from(rg.getClientRects()); if (!rs.length) return;
      const right = Math.max(...rs.map((r) => r.right)), left = Math.min(...rs.map((r) => r.left));
      let clipped = right > W + 0.5 || left < -0.5;
      for (let a = e; a && a !== document.body; a = a.parentElement) {
        if (getComputedStyle(a).overflowX === 'visible') continue;
        if (right > a.getBoundingClientRect().right + 1) clipped = true;
        break;
      }
      if (clipped) bad.push(`${e.className || e.tagName} "${e.textContent.trim().slice(0, 18)}" r=${Math.round(right)}`);
    });
    return Array.from(new Set(bad)).slice(0, 6);
  };
  // the longest figures that could realistically sit in the four-number row: five digits and a large move
  function longNumbers() {
    const m = freshMarket(), at = iso(10 * MIN), row = (key, label_th, value, unit, change_th) => ({ key, label_th, value, unit, change_th, trend: 'up', as_of: at, source: 'https://example.com/' });
    m.updated_at = iso(10 * MIN);
    m.items = [row('gold_th', 'ทองคำแท่ง 96.5% ขายออก (สมาคมค้าทองคำ)', '104400', 'บาท', '+11,900 จากวันก่อน'), row('brent', 'น้ำมัน Brent', '116.40', '$/บาร์เรล', '−18.29% (−8.80) จากปิดก่อนหน้า'), row('usdthb', 'ดอลลาร์/บาท', '33.600', 'บาท/$', '−10.50% (−0.170) จากปิดก่อนหน้า'), row('set', 'ดัชนี SET', '11502.09', 'จุด', '+10.74% (+11.08)')];
    return m;
  }
  for (const [engine, widths] of [['chromium', [320, 340, 360, 375, 390]], ['webkit', [320, 390]]]) {
    test(`no text is cut off by the screen or its box at phone widths, from the front page through the six chapters, at every large type size (${engine})`, async ({ browser }) => {
      let wk = null;
      if (engine === 'webkit') { try { wk = await webkit.launch(); } catch (e) { test.skip(true, 'WebKit is not installed here: ' + String(e.message).slice(0, 80)); } }
      writeFresh();
      for (const [feed, doc] of [['today', null], ['long', longNumbers()]]) {
        if (doc) writeData('market', doc);
        const base = doc ? URL.mutable : URL.full;
        for (const w of widths) {
          for (const size of doc ? [3] : [3, 4, 5, 6]) {
            const ctx = await (wk || browser).newContext({ ...FRESH, viewport: { width: w, height: 700 }, ...(wk ? {} : { isMobile: true, hasTouch: true }), reducedMotion: 'reduce' });
            const page = await ctx.newPage();
            await page.addInitScript((z) => { localStorage.setItem('world-read-size', z); }, String(size));
            await page.goto(base + '?view=read'); await ready(page);
            await page.evaluate(() => document.fonts.ready);
            for (const c of doc ? ['front'] : PAGES) {
              await page.evaluate((h) => { location.hash = h; }, c);
              await expect.poll(() => onChapter(page)).toBe(SEC(c));
              expect(await page.evaluate(CLIP_AUDIT), `${feed} figures, ${c} at ${w}px, type size ${size}`).toEqual([]);
            }
            await ctx.close();
          }
        }
      }
      if (wk) await wk.close();
    });
  }

  test('"ขายออก" stays whole in a price row, and economy figures use the true minus sign', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read#prices'); await ready(page);
    const nb = page.locator('#r-price-list li[data-key="gold_th"] .nm .rd-nb');
    await expect(nb).toHaveText('ขายออก');
    const lines = await nb.evaluate((e) => { const r = document.createRange(); r.selectNodeContents(e); return new Set(Array.from(r.getClientRects()).map((x) => Math.round(x.top))).size; });
    expect(lines).toBe(1);
    await go(page, 'economy');
    for (const metric of [0, 1, 2, 3]) {
      await page.click(`.rd-chips button[data-econ="${metric}"]`);
      expect(await page.locator('#r-econ-list .val').allInnerTexts(), 'no ASCII hyphen before a figure').not.toContainEqual(expect.stringMatching(/^-/));
    }
    await page.click('.rd-chips button[data-econ="0"]');
    const neg = world.economies.find((e) => e.gdp_growth_2026 < 0);
    if (neg) await expect(page.locator(`#r-econ-list > li[data-iso="${neg.iso}"] .val`)).toHaveText(`−${Math.abs(neg.gdp_growth_2026).toFixed(1)}%`);
    await ctx.close();
  });

  test('map view header still fits at 360px with the switch in it', async ({ browser }) => {
    const { ctx, page } = await open(browser, 360, 740);
    await page.goto(URL.full + '?view=map');
    const r = await page.evaluate(() => ({ title: document.getElementById('title').getBoundingClientRect(), sw: document.querySelector('.view-switch').getBoundingClientRect(), w: innerWidth, scroll: document.documentElement.scrollWidth }));
    expect(r.scroll).toBeLessThanOrEqual(r.w);
    expect(r.sw.right).toBeLessThanOrEqual(r.w);
    await ctx.close();
  });

  for (const size of [3, 6]) {
    test(`tap targets stay 44px at type size ${size}`, async ({ browser }) => {
      const { ctx, page } = await openAs(browser, 390, 844, null, size);
      await page.goto(URL.full + '?view=read'); await ready(page);
      await page.click('#rd-aa summary');
      const small = (await page.locator('.rd-aa button:not(:disabled)').evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }))).filter((x) => x[0] < 44 || x[1] < 44);
      expect(small).toEqual([]);
      await page.keyboard.press('Escape');
      const measure = () => page.evaluate(() => Array.from(document.querySelectorAll('.topbar summary, .topbar button, #rd-tabs a, #reader .rd-sec.on a, #reader .rd-sec.on button, #reader .rd-sec.on summary, .rd-foot button')).filter((e) => e.checkVisibility()).map((e) => { const r = e.getBoundingClientRect(); return [e.tagName + '.' + e.className, Math.round(r.width), Math.round(r.height), (e.textContent || '').slice(0, 24)]; }).filter((x) => x[2] < 43.5 && !/rd-note/.test(x[0])));
      for (const c of PAGES) {
        await go(page, c);
        await openAll(page);
        expect(await measure(), c).toEqual([]);
      }
      await page.evaluate((id) => { location.hash = id; }, `conflicts/${world.conflicts[0].id}`);
      await expect(page.locator('#rd-sheet')).toBeVisible();
      const sheet = await page.evaluate(() => Array.from(document.querySelectorAll('#rd-sheet a, #rd-sheet button, #rd-sheet summary')).filter((e) => e.checkVisibility()).map((e) => [e.textContent.slice(0, 24), e.getBoundingClientRect().height]).filter((x) => x[1] < 43.5));
      expect(sheet).toEqual([]);
      await ctx.close();
    });
  }

  test('typography has contrast: a heavy sans over a comfortable looped body, 17px or more for what you read', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read#conflicts'); await ready(page);
    const st = (sel) => page.locator(sel).first().evaluate((e) => { const c = getComputedStyle(e); return { f: c.fontFamily, w: +c.fontWeight, s: parseFloat(c.fontSize), lh: parseFloat(c.lineHeight) / parseFloat(c.fontSize) }; });
    const head = await st('#r-conflicts .rd-hero h2'), story = await st('#r-conflict-list h3'), body = await st('#r-conflict-list p.tx');
    expect(head.f).toContain('IBM Plex Sans Thai');
    expect(head.w).toBeGreaterThanOrEqual(700);
    expect(head.s).toBeGreaterThanOrEqual(30);
    expect(story.w).toBeGreaterThanOrEqual(700);
    expect(body.f).toContain('Noto Serif Thai');
    expect(body.s).toBeGreaterThanOrEqual(17);
    expect(body.lh).toBeGreaterThanOrEqual(1.65);
    await ctx.close();
  });

  for (const size of [3, 6]) {
    test(`Thai stacked marks are not cut off and lines of text do not run into each other, type size ${size}`, async ({ browser }) => {
      const { ctx, page } = await openAs(browser, 390, 844, null, size, { reducedMotion: 'reduce' });
      await page.goto(URL.full + '?view=read'); await ready(page);
      const check = () => page.evaluate(async () => {
        await document.fonts.ready;
        const cx = document.createElement('canvas').getContext('2d');
        const STACK = 'ปุ๋ย ฟื้นฟู กิ๊ฟ ญี่ปุ่น ฎีกา ฏุ ปั้น ที่นี่ ผู้นำ น้ำ';
        const bad = [];
        document.querySelectorAll('#reader .rd-sec.on *, #rd-sheet *').forEach((e) => {
          if (!e.checkVisibility() || e.closest('svg') || !Array.from(e.childNodes).some((n) => n.nodeType === 3 && /[฀-๿]/.test(n.textContent))) return;
          const cs = getComputedStyle(e), lh = parseFloat(cs.lineHeight), box = e.getBoundingClientRect();
          if (!lh) return;
          cx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
          const m = cx.measureText(STACK), ink = m.actualBoundingBoxAscent + m.actualBoundingBoxDescent;
          const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom), name = `${e.tagName}.${e.className}`;
          const clamped = cs.webkitLineClamp && cs.webkitLineClamp !== 'none';
          if (clamped && !(ink <= lh + pad + 0.5)) bad.push(`clipped ${name}: ink ${ink.toFixed(1)} > line ${lh.toFixed(1)} + padding ${pad.toFixed(1)}`);
          const wraps = box.height - pad > lh * 1.5, serif = /^"?Noto Serif/.test(cs.fontFamily);
          if (wraps && serif && !(ink <= lh + 0.5)) bad.push(`tight body ${name}: ink ${ink.toFixed(1)} > line ${lh.toFixed(1)}`);
          if (wraps && !serif && !(ink <= lh * 1.25)) bad.push(`tight heading ${name}: ink ${ink.toFixed(1)} > line ${lh.toFixed(1)} x 1.25`);
        });
        return Array.from(new Set(bad)).slice(0, 10);
      });
      for (const c of PAGES) { await go(page, c); await openAll(page); expect(await check(), c).toEqual([]); }
      await go(page, 'conflicts');
      await page.locator('#r-conflict-list a').first().click();
      await expect(page.locator('#rd-sheet')).toBeVisible();
      expect(await check(), 'article').toEqual([]);
      await ctx.close();
    });
  }

  for (const theme of ['paper', 'sepia', 'night']) {
    test(`all text on every page and in articles reaches 4.5:1, nothing pure black on pure white (${theme})`, async ({ browser }) => {
      writeFresh(); writeData('market', { ...freshMarket(), updated_at: iso(20 * HOUR) });   // brings a warning on screen
      const { ctx, page } = await openAs(browser, 390, 844, theme);
      await page.goto(URL.mutable + '?view=read'); await ready(page);
      const scan = () => page.evaluate(() => {
        const cv = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
        const rgba = (c) => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); const d = cv.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
        const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
        const bgOf = (e) => { for (; e; e = e.parentElement) { const c = rgba(getComputedStyle(e).backgroundColor); if (c[3] > 0.99) return c; } return [255, 255, 255, 1]; };
        const low = [];
        document.querySelectorAll('.topbar *, #rd-tabs *, #reader *, #rd-sheet *').forEach((e) => {
          if (!e.checkVisibility() || e.closest('svg') || !Array.from(e.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim())) return;
          const a = lum(rgba(getComputedStyle(e).color)), b = lum(bgOf(e)), r = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
          if (r < 4.5) low.push(`${e.tagName}.${e.className} "${e.textContent.slice(0, 16)}" ${r.toFixed(2)}`);
          if (r > 18) low.push(`too hard: ${e.tagName}.${e.className} ${r.toFixed(2)}`);
        });
        return Array.from(new Set(low)).slice(0, 10);
      });
      for (const c of PAGES) {
        await go(page, c);
        await openAll(page);
        expect(await scan(), c).toEqual([]);
      }
      await page.click('#rd-aa summary');
      expect(await scan(), 'controls').toEqual([]);
      await page.keyboard.press('Escape');
      await page.click('#rd-tabs a[data-sec="r-conflicts"]');
      await page.locator('#r-conflict-list a').first().click();
      expect(await scan(), 'article').toEqual([]);
      const base = await page.evaluate(() => [getComputedStyle(document.documentElement).backgroundColor, getComputedStyle(document.body).color]);
      for (const c of base) expect(['rgb(255, 255, 255)', 'rgb(0, 0, 0)']).not.toContain(c);
      await ctx.close();
    });
  }

  test('no looping animation; a page change takes a moment and nothing with reduced motion', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read'); await ready(page);
    const running = () => page.evaluate(() => document.getAnimations().map((a) => ({ n: a.animationName || a.transitionProperty || '', it: a.effect.getTiming().iterations, d: a.effect.getTiming().duration })));
    await go(page, 'conflicts');
    const during = await running();
    expect(during.filter((a) => a.it === Infinity)).toEqual([]);
    expect(during.filter((a) => a.d > 250)).toEqual([]);
    expect(during.length, 'a short step between pages').toBeGreaterThan(0);
    await page.waitForTimeout(350);
    expect(await running()).toEqual([]);
    await ctx.close();
    const calm = await open(browser, 390, 844, { reducedMotion: 'reduce' });
    await calm.page.goto(URL.full + '?view=read'); await ready(calm.page);
    await go(calm.page, 'conflicts');
    expect(await calm.page.evaluate(() => document.getAnimations().length)).toBe(0);
    await calm.page.locator('#r-conflict-list a').first().click();
    expect(await calm.page.evaluate(() => document.getAnimations().length)).toBe(0);
    await calm.page.click('#rd-sheet-close');
    await swipe(calm.page, 300, 80);
    expect(await onChapter(calm.page), 'swiping still works, without the movement').toBe('r-disasters');
    await calm.ctx.close();
  });

  test('severity is never colour alone: every meter has words beside it and a name for a screen reader', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read#conflicts'); await ready(page);
    await openAll(page);
    const lonely = await page.locator('#r-conflicts .rd-level').evaluateAll((els) => els.filter((e) => !e.querySelector('b') || !e.querySelector('b').textContent.trim() || !e.querySelector('.rd-meter[role="img"][aria-label]')).length);
    expect(lonely).toBe(0);
    await ctx.close();
  });
});

test.describe('page colour and type size', () => {
  const themeOf = (page) => page.evaluate(() => document.documentElement.getAttribute('data-rd-theme'));
  const sizeOf = (page) => page.evaluate(() => [document.documentElement.getAttribute('data-rd-size'), parseFloat(getComputedStyle(document.body).fontSize)]);

  test('the first visit follows the phone: light takes paper, dark takes the warm night page, and a later change follows until the reader chooses', async ({ browser }) => {
    const light = await open(browser, 390, 844);
    await light.page.goto(URL.full + '?view=read'); await ready(light.page);
    expect(await themeOf(light.page)).toBe('paper');
    await light.page.emulateMedia({ colorScheme: 'dark' });
    await expect.poll(() => themeOf(light.page)).toBe('night');
    await light.page.click('#rd-aa summary');
    await light.page.click('[data-rd-theme-set="sepia"]');
    await light.page.emulateMedia({ colorScheme: 'light' });
    await light.page.waitForTimeout(100);
    expect(await themeOf(light.page), 'a chosen colour stays').toBe('sepia');
    await light.ctx.close();
    const dark = await open(browser, 390, 844, { colorScheme: 'dark' });
    await dark.page.goto(URL.full + '?view=read'); await ready(dark.page);
    expect(await themeOf(dark.page)).toBe('night');
    expect(await dark.page.evaluate(() => localStorage.getItem('world-read-theme')), 'a default is not a choice').toBeNull();
    await dark.ctx.close();
  });

  test('the controls are on every page, tucked away, and a chosen colour and size come back before anything is painted', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read'); await ready(page);
    for (const c of PAGES) { await go(page, c); await expect(page.locator('#rd-aa summary')).toBeVisible(); }
    await go(page, 'front');
    await expect(page.locator('.rd-aa-panel')).toBeHidden();
    await page.click('#rd-aa summary');
    await expect(page.locator('.rd-aa-panel')).toBeVisible();
    await expect(page.locator('[data-rd-theme-set="paper"]')).toHaveAttribute('aria-pressed', 'true');
    await page.click('[data-rd-theme-set="night"]');
    await expect(page.locator('[data-rd-theme-set="night"]')).toHaveAttribute('aria-pressed', 'true');
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(27, 24, 21)');
    expect(await page.locator('meta[name="theme-color"]').first().getAttribute('content'), 'the browser bar takes the page colour').toBe('#1b1815');
    const before = (await sizeOf(page))[1];
    await page.click('#rd-size-up'); await page.click('#rd-size-up');
    expect((await sizeOf(page))[0]).toBe('5');
    expect((await sizeOf(page))[1]).toBeGreaterThan(before);
    await expect(page.locator('#rd-size-now')).toHaveText('ขนาด 5 จาก 6');
    await page.click('#rd-size-up');
    await expect(page.locator('#rd-size-up')).toBeDisabled();
    expect(await page.evaluate(() => [localStorage.getItem('world-read-theme'), localStorage.getItem('world-read-size')])).toEqual(['night', '6']);
    // a tap elsewhere and Escape both close it
    await page.mouse.click(195, 500);
    await expect(page.locator('.rd-aa-panel')).toBeHidden();
    await page.click('#rd-aa summary');
    await page.keyboard.press('Escape');
    await expect(page.locator('.rd-aa-panel')).toBeHidden();

    // the head script sets both attributes, so the first paint already has them
    await page.goto(URL.full + '?view=read');
    expect(await themeOf(page)).toBe('night');
    expect((await sizeOf(page))[0]).toBe('6');
    await ready(page);
    await page.click('#rd-aa summary');
    for (let i = 0; i < 5; i++) await page.click('#rd-size-down');
    await expect(page.locator('#rd-size-down')).toBeDisabled();
    expect((await sizeOf(page))[0]).toBe('1');
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('nonsense in storage falls back to the defaults', async ({ browser }) => {
    const { ctx, page } = await openAs(browser, 390, 844, 'pink', 99);
    await page.goto(URL.full + '?view=read'); await ready(page);
    expect(await themeOf(page)).toBe('paper');
    expect((await sizeOf(page))[0]).toBe('3');
    await ctx.close();
  });

  test('the colour and size stay out of the map view', async ({ browser }) => {
    const plain = await open(browser, 1440, 900);
    await plain.page.goto(URL.full + '?view=map');
    const look = (p) => p.evaluate(() => [getComputedStyle(document.body).backgroundColor, getComputedStyle(document.body).fontSize, getComputedStyle(document.body).fontFamily, document.querySelector('meta[name="theme-color"][media*="light"]').getAttribute('content')]);
    const want = await look(plain.page);
    await plain.ctx.close();
    const { ctx, page } = await openAs(browser, 1440, 900, 'night', 6);
    await page.goto(URL.full + '?view=read'); await ready(page);
    expect(await page.locator('meta[name="theme-color"][media*="light"]').getAttribute('content')).toBe('#1b1815');
    await page.click('#vw-map');
    await expectMap(page);
    await expect(page.locator('#rd-aa')).toBeHidden();
    await expect(page.locator('#rd-progress')).toBeHidden();
    await expect(page.locator('#rd-sheet')).toBeHidden();
    expect(await look(page)).toEqual(want);
    await ctx.close();
  });

  test('each view asks only for its own fonts', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const asked = [];
    page.on('request', (r) => { if (/fonts\.gstatic\.com/.test(r.url())) asked.push(r.url()); });
    await page.goto(URL.full + '?view=read'); await ready(page);
    await page.waitForTimeout(500);
    expect(asked.filter((u) => /notosansthai\//i.test(u)), 'the map view\'s body face is not fetched').toEqual([]);
    await ctx.close();
    const map = await open(browser, 1440, 900);
    const asked2 = [];
    map.page.on('request', (r) => { if (/fonts\.gstatic\.com/.test(r.url())) asked2.push(r.url()); });
    await map.page.goto(URL.full + '?view=map'); await ready(map.page);
    await map.page.waitForTimeout(500);
    expect(asked2.filter((u) => /notoserifthai/i.test(u)), 'the map view does not fetch the book face').toEqual([]);
    await map.ctx.close();
  });

  test('if the web fonts fail the page is still readable: a Thai system face, the same layout, no errors', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page, [/fonts\.g/, /ERR_FAILED/]);
    await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    await page.goto(URL.full + '?view=read#latest'); await ready(page);
    const r = await page.evaluate(() => ({ family: getComputedStyle(document.body).fontFamily, loaded: Array.from(document.fonts).filter((f) => f.status === 'loaded').length, w: document.documentElement.scrollWidth }));
    expect(r.loaded, 'the web font really is blocked').toBe(0);
    expect(r.family).toContain('Thonburi');
    expect(r.w).toBeLessThanOrEqual(390);
    await page.screenshot({ path: path.join(SHOTS, 'reading-no-webfont-390.png') });
    expect(errors).toEqual([]);
    await ctx.close();
  });
});

test.describe('keeping the place', () => {
  test('new data arriving, or a change of type size, leaves the reader on the same item', async ({ browser }) => {
    writeFresh();
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.mutable + '?view=read#conflicts'); await ready(page);
    const target = page.locator('#r-conflict-list > li').nth(1);
    await target.evaluate((e) => window.scrollTo(0, e.getBoundingClientRect().top + scrollY - 100));
    const top = () => page.locator('#r-conflict-list > li').nth(1).evaluate((e) => Math.round(e.getBoundingClientRect().top));
    const before = await top();
    writeData('headlines', { ...freshHeadlines(), updated_at: iso(MIN), items: [{ id: 'n0', conflict_id: 'economy', title_th: 'ข่าวใหม่ที่มาแทรก', time: iso(MIN), source: 'https://www.reuters.com/c', source_name: 'Reuters' }, ...freshHeadlines().items] });
    await repoll(page);
    expect(Math.abs(await top() - before)).toBeLessThanOrEqual(2);
    await page.click('#rd-tabs a[data-sec="r-conflicts"]').catch(() => {});   // the same tab: to the top of the chapter
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    await ctx.close();
  });

  test('coming back to the tab returns to the same chapter, item and open sections; an article too', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read#conflicts'); await ready(page);
    await page.locator('details[data-rd="conf-rest"] > summary').click();
    const target = page.locator('#r-conflict-more > li').nth(2);
    await target.evaluate((e) => window.scrollTo(0, e.getBoundingClientRect().top + scrollY - 120));
    await page.waitForTimeout(600);
    await page.reload(); await ready(page);
    expect(await onChapter(page)).toBe('r-conflicts');
    await expect(page.locator('details[data-rd="conf-rest"]')).toHaveAttribute('open', '');
    await expect.poll(() => page.locator('#r-conflict-more > li').nth(2).evaluate((e) => Math.round(e.getBoundingClientRect().top))).toBeGreaterThanOrEqual(110);
    expect(await page.locator('#r-conflict-more > li').nth(2).evaluate((e) => Math.round(e.getBoundingClientRect().top))).toBeLessThanOrEqual(130);
    // at the top of a chapter the top stays the top
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(600);
    await page.reload(); await ready(page);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    await page.locator('#r-conflict-list a').first().click();
    await page.evaluate(() => { document.getElementById('rd-sheet').scrollTop = 500; });
    await page.waitForTimeout(600);
    await page.reload(); await ready(page);
    await expect(page.locator('#rd-sheet')).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.getElementById('rd-sheet').scrollTop)).toBeGreaterThan(450);
    await ctx.close();
  });
});

test.describe('iPhone engine', () => {
  test('headless WebKit at 390px: pages, swipe, tabs, article, back, controls, memory and width all hold', async () => {
    let browser;
    try { browser = await webkit.launch(); } catch (e) { test.skip(true, 'WebKit is not installed here: ' + String(e.message).slice(0, 80)); }
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, colorScheme: 'light', storageState: { cookies: [], origins: [] } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
    const fits = async (label) => { const sw = await page.evaluate(() => [document.documentElement.scrollWidth, document.body.scrollWidth]); expect(Math.max(...sw), label).toBeLessThanOrEqual(390); };
    await fits('front');
    await page.screenshot({ path: path.join(SHOTS, 'reading-webkit-front.png') });
    const front = await page.evaluate(() => { const last = Array.from(document.querySelectorAll('.rd-tile')).pop(); return { bottom: last.getBoundingClientRect().bottom, tabs: document.getElementById('rd-tabs').getBoundingClientRect().top }; });
    console.log('webkit front', JSON.stringify(front));
    for (const c of CHAPTERS) {
      await page.tap(`#rd-tabs a[data-sec="r-${c}"]`);
      expect(await onChapter(page)).toBe(SEC(c));
      await fits(c);
    }
    // swipe by touch events on the page: this headless engine has no way to inject real ones
    const swipeW = (x0, x1) => page.evaluate(([a, b]) => {
      const r = document.getElementById('reader'), t = (x) => ({ clientX: x, clientY: 400 });
      const fire = (n, ts) => { const e = new Event(n, { bubbles: true }); e.touches = ts; r.dispatchEvent(e); };
      fire('touchstart', [t(a)]);
      for (let i = 1; i <= 6; i++) fire('touchmove', [t(a + (b - a) * i / 6)]);
      fire('touchend', []);
    }, [x0, x1]);
    await page.tap('#rd-tabs a[data-sec="r-prices"]');
    await swipeW(300, 80);
    expect(await onChapter(page), 'swipe to the next chapter').toBe('r-conflicts');
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(SHOTS, 'reading-webkit-conflicts.png') });
    await page.locator('#r-conflict-list a').first().tap();
    await expect(page.locator('#rd-sheet')).toBeVisible();
    await fits('article');
    await page.waitForTimeout(300);
    await page.screenshot({ path: path.join(SHOTS, 'reading-webkit-article.png') });
    await page.goBack();
    await expect(page.locator('#rd-sheet')).toBeHidden();
    expect(await onChapter(page)).toBe('r-conflicts');
    await page.tap('#rd-aa summary');
    await expect(page.locator('.rd-aa-panel')).toBeVisible();
    await page.tap('[data-rd-theme-set="night"]');
    for (let i = 0; i < 3; i++) await page.tap('#rd-size-up');
    await page.tap('#rd-aa summary');
    await fits('largest type');
    for (const c of ['front', 'prices', 'economy']) { await page.tap(`#rd-tabs a[data-sec="r-${c}"]`); await fits(`${c} largest type`); }
    expect(await page.evaluate(() => [document.documentElement.getAttribute('data-rd-theme'), document.documentElement.getAttribute('data-rd-size'), localStorage.getItem('world-read-theme')])).toEqual(['night', '6', 'night']);
    await page.tap('#rd-tabs a[data-sec="r-prices"]');
    expect(await page.evaluate(() => Array.from(document.querySelectorAll('#r-price-list .val')).map((e) => e.getBoundingClientRect().right).every((r, i, a) => Math.abs(r - a[0]) < 0.6))).toBe(true);
    await page.screenshot({ path: path.join(SHOTS, 'reading-webkit-night-large.png') });
    expect(errors).toEqual([]);
    await browser.close();
  });
});

test.describe('failure honesty', () => {
  test('no live data at all: says so at the top and in every live chapter, embedded values keep their own dates', async ({ browser }) => {
    for (const [w, h] of [[390, 844], [1440, 900]]) {
      const { ctx, page } = await open(browser, w, h);
      const allowed = [];
      const errors = [];
      page.on('console', (m) => { if (m.type() !== 'error') return; const t = m.text() + ' ' + (m.location().url || ''); (/404/.test(t) && /data\//.test(t) ? allowed : errors).push(t); });
      page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
      await page.goto(URL.nodata + '?view=read'); await ready(page);
      expect(allowed.length, 'the feeds really failed').toBeGreaterThan(0);
      await expect(page.locator('#r-banner')).toBeVisible();
      await expect(page.locator('#r-banner')).toContainText('โหมดออฟไลน์');
      await expect(page.locator('#rd-nums')).toContainText('โหลดราคาสดไม่สำเร็จ');
      await expect(page.locator('#rd-nums .rd-num').first()).toContainText('ค่าฝัง');
      await go(page, 'prices');
      await expect(page.locator('#r-prices .rd-note.warn')).toContainText('โหลดราคาสดไม่สำเร็จ');
      const rows = page.locator('#r-price-list li[data-key]');
      expect(await rows.count()).toBeGreaterThan(0);
      await expect(rows.first()).toContainText('ค่าล่าสุดที่ฝังในหน้าเว็บ ณ');
      await expect(page.locator('#r-prices [data-age]')).toHaveCount(0);
      await go(page, 'latest');
      await expect(page.locator('#r-latest .rd-note.warn').last()).toContainText('โหลดข่าวล่าสุดไม่สำเร็จ');
      await go(page, 'disasters');
      await expect(page.locator('#r-disasters .rd-note.warn')).toContainText('โหลดข้อมูลภัยพิบัติไม่สำเร็จ');
      await go(page, 'gold');
      await expect(page.locator('#r-gold .rd-note.warn')).toContainText('โหลดราคาสดไม่สำเร็จ');
      await expect(page.locator('#r-gold-th')).toBeVisible();
      await expect(page.locator('#r-gold-th')).toContainText('ณ ');
      await go(page, 'conflicts');
      await openAll(page);
      await expect(page.locator('#r-conflicts li.rd-conf')).toHaveCount(world.conflicts.length);
      await noHScroll(page, 'offline');
      expect(errors).toEqual([]);
      await page.screenshot({ path: path.join(SHOTS, `reading-offline-${w}.png`), fullPage: false });
      await ctx.close();
    }
  });

  test('one feed failing, stale data and a failed run are each shown where they apply, then clear', async ({ browser }) => {
    writeFresh();
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page, [/404/]);
    await page.goto(URL.mutable + '?view=read#latest'); await ready(page);
    const warnsOn = async (c) => { await go(page, c); return page.locator(`#${SEC(c)} .rd-note.warn`).evaluateAll((els) => els.map((e) => e.textContent).filter((t) => !/ไม่ได้ทบทวนมาแล้ว/.test(t))); };   // the frozen e2e fixture is old on purpose
    const lastWarn = (c) => page.locator(`#${SEC(c)} .rd-note.warn`).last();
    for (const c of ['latest', 'prices', 'disasters', 'gold']) expect(await warnsOn(c), c).toEqual([]);

    // headlines fail after a good load: last items stay, with a warning
    await go(page, 'latest');
    removeData('headlines');
    await repoll(page);
    await expect(lastWarn('latest')).toContainText('โหลดข่าวรอบล่าสุดไม่สำเร็จ');
    await expect(page.locator('#r-news > li').first()).toContainText('ข่าวทดสอบหนึ่ง');
    await expect(page.locator('#r-banner')).toContainText('ข่าว');

    // disasters fail too; the front page tile keeps its last list and the chapter warns
    removeData('disasters');
    await go(page, 'disasters');
    await repoll(page);
    await expect(lastWarn('disasters')).toContainText('โหลดข้อมูลภัยพิบัติรอบล่าสุดไม่สำเร็จ');
    await expect(page.locator('#r-dz-list > li')).toHaveCount(1);

    // everything back: warnings gone
    writeFresh();
    await repoll(page);
    for (const c of ['latest', 'prices', 'disasters']) expect(await warnsOn(c), c).toEqual([]);

    // stale prices
    await go(page, 'prices');
    writeData('market', { ...freshMarket(), updated_at: iso(7 * HOUR) });
    await repoll(page);
    await expect(lastWarn('prices')).toContainText('เก่ากว่า 6 ชม.');
    await expect(page.locator('#r-banner')).toContainText('ราคา');

    // stale news
    await go(page, 'latest');
    writeData('headlines', { ...freshHeadlines(), updated_at: iso(15 * HOUR) });
    await repoll(page);
    await expect(lastWarn('latest')).toContainText('เก่ากว่า 14 ชม.');

    // stale disasters
    await go(page, 'disasters');
    writeData('disasters', { ...freshDisasters(), updated: iso(7 * HOUR) });
    await repoll(page);
    await expect(lastWarn('disasters')).toContainText('เก่ากว่า 6 ชม.');

    // disasters partly failed, in the feed's own words
    writeData('disasters', { ...freshDisasters(), ok: false, message_th: 'GDACS ล้มเหลวรอบนี้' });
    await repoll(page);
    await expect(lastWarn('disasters')).toContainText('GDACS ล้มเหลวรอบนี้');

    // a failed run, in the status file's own words
    await go(page, 'prices');
    writeData('status', { ...freshStatus(), ok: false, message_th: 'รอบล่าสุดล้มเหลว เกินวงเงิน' });
    await repoll(page);
    await expect(lastWarn('prices')).toContainText('รอบล่าสุดล้มเหลว เกินวงเงิน');
    await page.screenshot({ path: path.join(SHOTS, 'reading-stale-390.png'), fullPage: false });
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('stale gold says which price is stale', async ({ browser }) => {
    // a fixed clock long after the fixture's date: both quotes are newer than the embedded ones and still many trading hours old
    const now = Date.parse(goldFx.as_of) + 15 * 86400000;
    const quoteAt = new Date(now - 8 * 86400000).toISOString();
    const m = { updated_at: new Date(now - HOUR).toISOString(), items: [
      { key: 'gold', label_th: 'ทองคำ (spot)', value: '4000.00', unit: '$/ออนซ์', change_th: '+1.00% จากปิดก่อนหน้า', trend: 'up', as_of: quoteAt, source: 'https://www.swissquote.com/' },
      { key: 'gold_th', label_th: 'ทองคำแท่ง', value: '64000', unit: 'บาท', change_th: '+50 บาท', trend: 'up', as_of: quoteAt, source: 'https://www.goldtraders.or.th/' },
    ] };
    writeData('market', m);
    const { ctx, page } = await open(browser, 390, 844);
    await page.clock.setFixedTime(new Date(now));
    await page.goto(URL.mutable + '?view=read#gold'); await ready(page);
    const note = page.locator('#r-gold .rd-note.warn').last();
    await expect(note).toContainText('ข้อมูลเก่า');
    await expect(note).toContainText('ทองคำแท่งไทย');
    await expect(note).toContainText('ทองคำโลก');
    await expect(page.locator('#r-gold-spot')).toContainText(bkk(quoteAt));
    await ctx.close();
  });

  test('an open article stays readable when a feed behind it fails, and leaves when its item disappears', async ({ browser }) => {
    writeFresh();
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page, [/404/]);
    await page.goto(URL.mutable + '?view=read#disasters/x1'); await ready(page);
    await expect(page.locator('#rd-sheet-title')).toHaveText('น้ำท่วมทดสอบ');
    writeData('disasters', { ...freshDisasters(), items: [] });
    await repoll(page);
    await expect(page.locator('#rd-sheet')).toBeHidden();
    expect(await onChapter(page)).toBe('r-disasters');
    await expect(page.locator('#r-disasters')).toContainText('ขณะนี้ไม่มีภัยพิบัติ');
    expect(errors).toEqual([]);
    await ctx.close();
  });
});

test.describe('deferred globe', () => {
  test('the reading view never asks for three.js; the first switch to the map builds the globe', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    const reqs = [];
    page.on('request', (r) => { if (THREE_RE.test(r.url())) reqs.push(r.url()); });
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
    for (const c of CHAPTERS) await go(page, c);
    await page.waitForTimeout(500);
    expect(reqs, 'no three.js on a reading-view load').toEqual([]);
    await expect(page.locator('#stage canvas')).toHaveCount(0);

    await page.click('#vw-map');
    await expect(page.locator('#stage canvas')).toHaveCount(1, { timeout: 15000 });
    expect(reqs).toHaveLength(1);
    const sized = await page.locator('#stage canvas').evaluate((c) => [c.width, c.height]);
    expect(sized[0]).toBeGreaterThan(100); expect(sized[1]).toBeGreaterThan(100);
    // the map's own features answer as usual after the late start
    await page.click('.tab[data-tab="conflicts"]');
    await page.locator('#view-conflicts .item').first().click();
    await expect(page.locator('#view-detail h2')).toBeVisible();

    await page.click('#vw-read');
    await expectRead(page);
    await page.click('#vw-map');
    await expectMap(page);
    await expect(page.locator('#stage canvas')).toHaveCount(1);
    expect(reqs, 'loaded only once').toHaveLength(1);
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('the map view loads three.js straight away', async ({ browser }) => {
    const { ctx, page } = await open(browser, 1440, 900);
    const reqs = [];
    page.on('request', (r) => { if (THREE_RE.test(r.url())) reqs.push(r.url()); });
    await page.goto(URL.full);
    await expect(page.locator('#stage canvas')).toHaveCount(1, { timeout: 15000 });
    expect(reqs).toHaveLength(1);
    await ctx.close();
  });

  test('three.js failing in the map view falls back to the list, without touching the reading view', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.route(THREE_RE, (r) => r.abort());
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
    await page.click('#vw-map');
    await expect(page.locator('#fallback.on')).toBeVisible({ timeout: 10000 });
    await page.click('#vw-read');
    await expectRead(page);
    await expect(page.locator('#r-front h2')).toBeVisible();
    await ctx.close();
  });
});

test('screenshots of the reading view', async ({ browser }) => {
  for (const [name, w, h] of [['phone', 390, 844], ['desktop', 1440, 900]]) {
    for (const scheme of ['paper', 'sepia', 'night']) {
      const { ctx, page } = await openAs(browser, w, h, scheme);
      await page.goto(URL.full + '?view=read'); await ready(page);
      await page.waitForTimeout(400);
      await page.screenshot({ path: path.join(SHOTS, `reading-${name}-${scheme}-front.png`) });
      for (const c of CHAPTERS) {
        await go(page, c);
        await page.waitForTimeout(250);
        await page.screenshot({ path: path.join(SHOTS, `reading-${name}-${scheme}-${c}.png`) });
      }
      await ctx.close();
    }
  }
});
