// Gold panel: the static analysis (gold.json) is embedded in the page; market.json (gold, gold_th) and
// gold_history.json overlay it when their as_of is newer.
// Panel checks run against the "nodata" server (data/*.json 404 -> embedded values only);
// the live-overlay tests write fixture data/*.json on the "mutable" server and fix the page clock.
const { test, expect } = require('@playwright/test');
const path = require('path');
const { URL, SHOTS, noHScroll, writeData, removeData, resetData, seed } = require('./helpers');
const DATA_404 = [/404/, /data\/(market|headlines|status|disasters|gold_history)\.json/];

const cases = [
  { name: 'gold-mobile-dark', w: 375, h: 812, scheme: 'dark', dpr: 3 },
  { name: 'gold-mobile-light', w: 375, h: 812, scheme: 'light', dpr: 3 },
  { name: 'gold-desktop-dark', w: 1280, h: 800, scheme: 'dark', dpr: 1 },
  { name: 'gold-desktop-light', w: 1280, h: 800, scheme: 'light', dpr: 1 },
];

// a 404 for data/*.json is expected on the nodata server; any other console error fails
function collectErrors(page, allow404) {
  const errors = [];
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const where = m.text() + ' ' + (m.location().url || '');
    if (allow404 && DATA_404.every(r => r.test(where))) return;
    errors.push('console: ' + where);
  });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  return errors;
}
async function panelChecks(page, label) {
  const bad = await page.evaluate(() => (document.getElementById('view-gold').innerText.match(/\bnull\b|\bNaN\b|undefined/g) || []).length);
  expect(bad, `no null/NaN text (${label})`).toBe(0);
  const wide = await page.evaluate(() => {
    const pb = document.getElementById('panel-body'); const lim = pb.clientWidth + 1;
    return Array.from(document.querySelectorAll('#view-gold *')).filter(e => e.getBoundingClientRect().width > lim || e.scrollWidth > e.clientWidth + 1 && getComputedStyle(e).overflowX === 'visible' && e.tagName !== 'svg' && !e.closest('svg')).map(e => (e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className) || e.tagName).slice(0, 10);
  });
  expect(wide, `elements wider than panel (${label})`).toEqual([]);
  // svg text must stay inside its own svg box
  const svgOut = await page.evaluate(() => Array.from(document.querySelectorAll('#view-gold svg')).flatMap(s => {
    const r = s.getBoundingClientRect();
    return Array.from(s.querySelectorAll('text')).filter(t => { const b = t.getBoundingClientRect(); return b.left < r.left - 1 || b.right > r.right + 1 || b.top < r.top - 1 || b.bottom > r.bottom + 1; }).map(t => t.textContent);
  }));
  expect(svgOut, `svg labels outside the chart (${label})`).toEqual([]);
}

for (const c of cases) {
  const mobile = c.w < 500;
  test(`gold panel ${c.name}`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: c.w, height: c.h }, colorScheme: c.scheme, deviceScaleFactor: c.dpr, isMobile: mobile, hasTouch: mobile });
    const page = await ctx.newPage();
    const errors = collectErrors(page, true);
    await page.goto(URL.nodata);
    await page.waitForTimeout(2500);
    await expect(page.locator('#live-slot .offline-bar')).toBeVisible();
    expect(errors, 'errors on load').toEqual([]);

    // entry points exist: stage chip + tab
    await expect(page.locator('#btn-gold')).toBeVisible();
    await expect(page.locator('.tab[data-tab="gold"]')).toBeVisible();
    expect(await page.locator('#view-gold').isHidden()).toBe(true);

    // open via the chip
    await page.click('#btn-gold');
    await expect(page.locator('#view-gold')).toBeVisible();
    expect(await page.locator('.tab[data-tab="gold"]').getAttribute('aria-selected')).toBe('true');
    await expect(page.locator('#gold-chart svg')).toBeVisible();
    await expect(page.locator('#gold-fc svg')).toBeVisible();
    expect(await page.locator('#view-gold .tile').count()).toBe(4);
    expect(await page.locator('#gold-tile-main .val').textContent()).toBe('$3,903');
    expect(await page.locator('#gold-tile-main .live-tag').isHidden()).toBe(true);
    expect(await page.locator('#gold-tile-th .val').textContent()).toBe('62,500');
    expect(await page.locator('#gold-tile-th .live-tag').isHidden()).toBe(true);
    const tileText = await page.locator('#view-gold .tiles').innerText();
    expect(tileText).toContain('+0.7% วันนี้'); expect(tileText).toContain('−30.2%'); expect(tileText).toContain('62,300');
    expect(await page.locator('#view-gold .gold-head').innerText()).toContain('ระหว่างวัน 2 พ.ย.');
    expect(await page.locator('#gold-tile-th .sub').innerText()).toBe('รับซื้อ 62,300 บาท');
    // the static analysis is labelled with its own date
    expect(await page.locator('#gold-analysis-note').innerText()).toContain('บทวิเคราะห์ ณ 2 พ.ย. 2569');
    expect(await page.locator('#view-gold details.fold .fold-asof').count()).toBe(5);
    expect(await page.locator('#gold-chart-wrap .chart-legend').innerText()).toContain('บทวิเคราะห์ ณ 2 พ.ย. 2569');
    // without live data the line ends at the embedded 2 Nov quote
    expect(await page.locator('#gold-chart svg text', { hasText: 'ล่าสุด 2 พ.ย.' }).textContent()).toContain('$3,903');
    expect(await page.locator('#gold-chart svg text', { hasText: 'สถิติ $5,595' }).count()).toBe(1);
    expect(await page.locator('#gold-chart svg text', { hasText: 'แนวรับ 3,850' }).count()).toBe(1);
    expect(await page.locator('#gold-chart svg text', { hasText: 'MA200 4,500' }).count()).toBe(1);
    expect(await page.locator('#gold-fc svg .nm').count()).toBe(6);
    expect(await page.locator('#view-gold details.fold').count()).toBe(6);
    expect(await page.locator('#view-gold .gold-foot').innerText()).toContain('ไม่ใช่คำแนะนำการลงทุน');
    await noHScroll(page, 'gold open');
    await panelChecks(page, 'top');

    // the panel scrolls inside itself
    const sc = await page.evaluate(() => { const b = document.getElementById('panel-body'); return [b.scrollHeight, b.clientHeight]; });
    expect(sc[0]).toBeGreaterThan(sc[1]);

    if (mobile) { await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '90%')); await page.waitForTimeout(500); }
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-1-top.png`) });

    // hover/tap tooltip on the line chart
    await page.locator('#gold-chart svg').scrollIntoViewIfNeeded(); await page.waitForTimeout(200);
    const box = await page.locator('#gold-chart svg').boundingBox();
    await page.mouse.move(box.x + box.width * 0.5, box.y + box.height * 0.5);
    await page.waitForTimeout(150);
    await expect(page.locator('#gold-chart-wrap .chart-tip')).toBeVisible();
    expect(await page.locator('#gold-chart-wrap .chart-tip').innerText()).toMatch(/\$[\d,]+/);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-2-tooltip.png`) });
    await page.mouse.move(5, 5);

    // forecast chart + first folds
    await page.locator('#gold-fc').scrollIntoViewIfNeeded();
    await page.evaluate(() => { document.getElementById('panel-body').scrollTop -= 30; });
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-3-forecast.png`) });

    // open every fold and check the table + thai block
    const folds = page.locator('#view-gold details.fold');
    for (let i = 0; i < 6; i++) { if (!(await folds.nth(i).evaluate(d => d.open))) await folds.nth(i).locator('summary').click(); }
    expect(await page.locator('#view-gold .lv-table tbody tr').count()).toBe(6);
    expect(await page.locator('#view-gold .kv .v', { hasText: '81,900' }).count()).toBe(1);
    expect(await page.locator('#view-gold .kv .v', { hasText: '63,300' }).count()).toBe(1);
    expect(await page.locator('#view-gold .sent-row').count()).toBe(3);
    expect(await page.locator('#view-gold .risks.up li').count()).toBe(5);   // 3 upside risks + 2 counter-views
    expect(await page.locator('#view-gold .risks.down li').count()).toBe(8); // 4 downside risks + 4 bear targets
    expect(await page.locator('#view-gold .fold-body', { hasText: 'ปฏิทินสัปดาห์หน้า' }).innerText()).toContain('6 พ.ย.');
    expect(await page.locator('#gold-fc svg text', { hasText: 'ณ 2 พ.ย. $3,903' }).count()).toBe(1);
    expect(await page.locator('#view-gold .gold-foot').innerText()).toContain('Kitco');
    await panelChecks(page, 'folds open');
    await noHScroll(page, 'folds open');
    await page.locator('#view-gold .lv-table').scrollIntoViewIfNeeded();
    await page.evaluate(() => { document.getElementById('panel-body').scrollTop -= 60; });
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-4-levels.png`) });
    await page.locator('#view-gold .scen').scrollIntoViewIfNeeded();
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-5-outlook.png`) });

    // close with the panel's own controls: another tab hides the gold view; detail card still works
    await page.click('.tab[data-tab="overview"]');
    expect(await page.locator('#view-gold').isHidden()).toBe(true);
    await expect(page.locator('#view-overview')).toBeVisible();
    await page.click('.tab[data-tab="gold"]');
    await expect(page.locator('#view-gold')).toBeVisible();
    await page.click('#btn-thai');
    await page.waitForTimeout(600);
    await expect(page.locator('#view-detail h2')).toHaveText('ไทย');
    expect(await page.locator('#view-gold').isHidden()).toBe(true);
    await page.click('#view-detail .back');
    await expect(page.locator('#view-gold')).toBeVisible();

    expect(errors, 'errors at end').toEqual([]);
    await ctx.close();
  });
}

// ---------------------------------------------------------------- live overlay (fixture data, fixed clock)
const T = (s) => Date.parse(s);
const WED = T('2026-11-04T05:00:00Z');          // Wednesday 12:00 Bangkok: spot and the Thai board are both open
const SAT = T('2026-11-07T12:00:00Z');          // Saturday 19:00 Bangkok: both closed
const iso = (t) => new Date(t).toISOString().replace('.000Z', 'Z');
const MIN = 60000, HOUR = 3600000;

// the real 13-item market.json with gold / gold_th replaced; updated_at follows `now`
function market(now, gold, goldTh) {
  const m = seed('market');
  m.updated_at = iso(now - 25*MIN);
  m.items = m.items.map(it => it.key === 'gold' ? { ...it, ...gold } : it.key === 'gold_th' ? { ...it, ...goldTh } : it);
  for (const k of ['gold', 'gold_th']) { const it = m.items.find(x => x.key === k); if (it.buy == null) delete it.buy; if (it.ornament_sell == null) delete it.ornament_sell; }
  return m;
}
// gold_history.json as backfilled from the run commits (2 Nov 07:45Z .. 4 Nov 01:10Z)
const HIST = () => seed('gold_history');
function serve(now, m, hist = HIST(), statusAt = now - 25*MIN) {
  resetData();
  writeData('market', m);
  writeData('status', { updated_at: iso(statusAt), run_count: 30, ok: true, message_th: 'ทดสอบ' });
  if (hist) writeData('gold_history', hist); else removeData('gold_history');
}
async function openGold(browser, c, now, allow404) {
  const mobile = c.w < 500;
  const ctx = await browser.newContext({ viewport: { width: c.w, height: c.h }, colorScheme: c.scheme, deviceScaleFactor: c.dpr, isMobile: mobile, hasTouch: mobile });
  const page = await ctx.newPage();
  await page.clock.setFixedTime(now);
  const errors = collectErrors(page, allow404);
  await page.goto(URL.mutable);
  await expect(page.locator('#live-slot .tk[data-key="gold"]')).toBeVisible();
  await page.click('.tab[data-tab="gold"]');
  await expect(page.locator('#gold-chart svg')).toBeVisible();
  return { ctx, page, errors, mobile };
}
async function repollAt(page, now) {
  const before = await page.evaluate(() => (window.__liveState || {}).polls || 0);
  await page.clock.setFixedTime(now);              // the page ignores re-polls < 2 s apart by its own clock
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect.poll(() => page.evaluate(() => (window.__liveState || {}).polls || 0)).toBeGreaterThan(before);
}
const lineCount = (page) => page.locator('#gold-chart svg path.ln').evaluate(p => p.getAttribute('d').split('L').length);

const NEWER = (now) => market(now,
  { value: '3935.06', change_th: '+0.09% ระหว่างวันพุธ', trend: 'up', as_of: iso(now - 20*MIN), source: 'https://tradingeconomics.com/commodities' },
  { value: '62600', change_th: 'ประกาศครั้งที่ 3 ของวัน', trend: 'up', as_of: iso(now - 90*MIN), source: 'https://www.goldtraders.or.th/', buy: 62400, ornament_sell: 63400 });

const shotCases = [
  { name: 'gold-live-desktop-light', w: 1280, h: 800, scheme: 'light', dpr: 1 },
  { name: 'gold-live-desktop-dark', w: 1280, h: 800, scheme: 'dark', dpr: 1 },
  { name: 'gold-live-375-light', w: 375, h: 812, scheme: 'light', dpr: 3 },
  { name: 'gold-live-375-dark', w: 375, h: 812, scheme: 'dark', dpr: 3 },
];
for (const c of shotCases) {
  test(`newer live data overrides the embedded values; chart reaches today (${c.name})`, async ({ browser }) => {
    serve(WED, NEWER(WED));
    const { ctx, page, errors, mobile } = await openGold(browser, c, WED, false);
    const main = page.locator('#gold-tile-main'), th = page.locator('#gold-tile-th');
    await expect(main.locator('.live-tag')).toBeVisible();
    expect(await main.locator('.live-tag').innerText()).toBe('สด');
    expect(await main.locator('.val').textContent()).toBe('$3,935');
    // day change vs the last recorded price of the previous Bangkok day (3 Nov 16:00 = $3,921)
    expect(await main.locator('.delta').innerText()).toContain('+0.4% จาก 3 พ.ย.');
    expect(await main.locator('.src').innerText()).toContain('ณ 4 พ.ย. 2569 11:40 น.');
    expect(await main.locator('.src a').getAttribute('href')).toBe('https://tradingeconomics.com/commodities');
    expect(await page.locator('#gold-caption').textContent()).toBe('ราคาโลก ณ 4 พ.ย. 2569 11:40 น.');
    expect(await page.locator('#gold-tile-day .val').textContent()).toBe('+0.4%');
    expect(await page.locator('#gold-tile-day .delta').innerText()).toContain('จาก $3,921 ค่าล่าสุดของ 3 พ.ย.');
    expect(await page.locator('#gold-tile-peak .val').textContent()).toBe('−29.7%');   // 3,935 vs the embedded $5,595 peak
    expect(await page.locator('#gold-tile-peak .src').innerText()).toContain('คำนวณจากราคาสด');
    await expect(th.locator('.live-tag')).toBeVisible();
    expect(await th.locator('.val').textContent()).toBe('62,600');
    expect(await th.locator('.delta').innerText()).toContain('+100 บาท จาก 3 พ.ย.');      // vs 62,500 (3 Nov 16:39)
    expect(await th.locator('.sub').innerText()).toBe('รับซื้อ 62,400 บาท');
    expect(await th.locator('.src').innerText()).toContain('ณ 4 พ.ย. 2569 10:30 น.');
    expect(await th.locator('.src a').getAttribute('href')).toBe('https://www.goldtraders.or.th/');
    expect(await page.locator('#view-gold .tile.is-stale').count()).toBe(0);
    // chart: 11 embedded points (year open + Jan..Oct closes) + one point per day for 2, 3 and 4 Nov
    expect(await lineCount(page)).toBe(14);
    expect(await page.locator('#gold-chart svg text', { hasText: 'ล่าสุด 4 พ.ย.' }).textContent()).toContain('$3,935');
    expect(await page.locator('#gold-fc svg text', { hasText: 'ล่าสุด $3,935' }).count()).toBe(1);
    // header date = the live status time; title undated
    expect(await page.locator('#updated .u-full').textContent()).toBe('อัปเดต 4 พ.ย. 2569 11:35 น.');
    await expect(page).toHaveTitle('สถานการณ์โลก');
    expect(await page.locator('#title').textContent()).toBe('สถานการณ์โลก');
    if (mobile) {   // phones: the short header date (no year) keeps the header line on one row, untruncated
      await expect(page.locator('#updated .u-short')).toBeVisible();
      expect(await page.locator('#updated .u-short').textContent()).toBe('อัปเดต 4 พ.ย. 11:35');
      const sub = await page.evaluate(() => { const s = document.querySelector('.topbar .sub'); return [s.scrollWidth, s.clientWidth, s.getBoundingClientRect().height]; });
      expect(sub[0], 'header line not truncated').toBeLessThanOrEqual(sub[1]);
      expect(sub[2], 'header line single row').toBeLessThan(24);
    } else await expect(page.locator('#updated .u-full')).toBeVisible();
    await noHScroll(page, c.name);
    await panelChecks(page, c.name);
    if (mobile) { await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '90%')); await page.waitForTimeout(500); }
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-1-tiles.png`) });
    // the hover tip names the day of a daily point (the days sit ~1 px apart on the year axis: hover the right edge)
    await page.locator('#gold-chart svg').scrollIntoViewIfNeeded(); await page.waitForTimeout(200);
    const box = await page.locator('#gold-chart svg').boundingBox();
    await page.mouse.move(box.x + box.width - 1, box.y + box.height * 0.6);
    await expect(page.locator('#gold-chart-wrap .chart-tip')).toBeVisible();
    expect(await page.locator('#gold-chart-wrap .chart-tip').innerText()).toBe('4 พ.ย. 2569 · $3,935');
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-2-chart.png`) });
    await page.mouse.move(5, 5);
    // Thai block uses the live buy / ornament of the same announcement; the levels follow the live price
    const folds = page.locator('#view-gold details.fold');
    for (let i = 0; i < 6; i++) { if (!(await folds.nth(i).evaluate(d => d.open))) await folds.nth(i).locator('summary').click(); }
    expect(await page.locator('#gold-th-kv .v', { hasText: '63,400 บาท' }).count()).toBe(1);
    expect(await page.locator('#gold-th-kv .v', { hasText: '(ค่า' }).count()).toBe(0);
    expect(await page.locator('#gold-lv-body').innerText()).toContain('ราคาล่าสุดต่ำกว่าเส้นค่าเฉลี่ย 200 วันราว 13% (เส้น MA200 ณ 2 พ.ย.)');
    expect(await page.locator('#view-gold .gold-foot').innerText()).toContain('ราคาสด: tradingeconomics.com, goldtraders.or.th');
    await panelChecks(page, c.name + ' folds');
    await noHScroll(page, c.name + ' folds');
    await page.locator('#gold-th-kv').scrollIntoViewIfNeeded();
    await page.evaluate(() => { document.getElementById('panel-body').scrollTop -= 60; });
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-3-thai.png`) });
    expect(errors).toEqual([]);
    await ctx.close();
  });
}

test('older live data does not replace the embedded values; a later poll with newer data does', async ({ browser }) => {
  const OLD = market(WED,
    { value: '3990', change_th: 'ปิดศุกร์', trend: 'up', as_of: '2026-11-01T12:00:00Z', source: 'https://example.com/old' },
    { value: '61000', change_th: 'เก่า', trend: 'down', as_of: '2026-11-01T03:00:00Z', source: 'https://example.com/old-th' });
  serve(WED, OLD);
  const { ctx, page, errors } = await openGold(browser, { w: 1280, h: 800, scheme: 'dark', dpr: 1 }, WED, false);
  expect(await page.locator('#gold-tile-main .val').textContent()).toBe('$3,903');
  expect(await page.locator('#gold-tile-main .live-tag').isHidden()).toBe(true);
  expect(await page.locator('#gold-tile-th .val').textContent()).toBe('62,500');
  expect(await page.locator('#gold-tile-th .live-tag').isHidden()).toBe(true);
  expect(await page.locator('#gold-tile-main .delta').innerText()).toContain('+0.7% วันนี้');
  expect(await page.locator('#view-gold .gold-head').innerText()).toContain('ระหว่างวัน 2 พ.ย.');
  // the history still extends the chart past October
  expect(await page.locator('#gold-chart svg text', { hasText: 'ล่าสุด 4 พ.ย.' }).count()).toBe(1);
  // next poll: newer data -> live; then the gold items vanish -> embedded again
  writeData('market', NEWER(WED + 5*MIN));
  await repollAt(page, WED + 5*MIN);
  await expect(page.locator('#gold-tile-main .val')).toHaveText('$3,935');
  expect(await page.locator('#gold-tile-main .live-tag').isVisible()).toBe(true);
  const m = NEWER(WED + 10*MIN); m.items = m.items.filter(x => x.key !== 'gold' && x.key !== 'gold_th');
  writeData('market', m);
  await repollAt(page, WED + 10*MIN);
  await expect(page.locator('#gold-tile-main .val')).toHaveText('$3,903');
  expect(await page.locator('#gold-tile-main .live-tag').isHidden()).toBe(true);
  expect(await page.locator('#gold-fc svg text', { hasText: 'ณ 2 พ.ย. $3,903' }).count()).toBe(1);
  expect(errors).toEqual([]);
  await ctx.close();
});

test('a newer Thai sell without buy / ornament keeps the embedded ones with their own date; no history -> change_th', async ({ browser }) => {
  const m = market(WED,
    { value: '3935.06', change_th: '+0.09% ระหว่างวันพุธ', trend: 'up', as_of: iso(WED - 20*MIN), source: 'https://tradingeconomics.com/commodities' },
    { value: '62600', change_th: '+100 บาท ประกาศครั้งที่ 3', trend: 'up', as_of: iso(WED - 90*MIN), source: 'https://www.goldtraders.or.th/' });
  serve(WED, m, null);                                         // gold_history.json missing (404, not fatal)
  const { ctx, page, errors } = await openGold(browser, { w: 375, h: 812, scheme: 'light', dpr: 3 }, WED, true);
  expect(await page.locator('#gold-tile-th .val').textContent()).toBe('62,600');
  expect(await page.locator('#gold-tile-th .sub').innerText()).toBe('รับซื้อ 62,300 บาท (ค่า 2 พ.ย.)');
  // previous day = the embedded 2 Nov values; 4 Nov vs 2 Nov is within the 4-day window
  expect(await page.locator('#gold-tile-main .delta').innerText()).toContain('+0.8% จาก 2 พ.ย.');
  expect(await page.locator('#gold-tile-th .delta').innerText()).toContain('+100 บาท จาก 2 พ.ย.');
  await page.locator('#view-gold details.fold').nth(4).locator('summary').click();
  expect(await page.locator('#gold-th-kv .v', { hasText: '62,300 บาท (ค่า 2 พ.ย.)' }).count()).toBe(1);
  expect(await page.locator('#gold-th-kv .v', { hasText: '63,300 บาท (ค่า 2 พ.ย.)' }).count()).toBe(1);
  // the chart still reaches today through the live quote
  expect(await page.locator('#gold-chart svg text', { hasText: 'ล่าสุด 4 พ.ย.' }).count()).toBe(1);
  expect(await page.locator('#live-slot .live-head .note').getAttribute('class')).not.toContain('warn');  // a missing history is not a failed fetch
  await noHScroll(page, 'no history'); await panelChecks(page, 'no history');
  expect(errors).toEqual([]);
  await ctx.close();
});

test('a live quote with no newer one for over 10 trading hours is marked stale on a weekday', async ({ browser }) => {
  const m = market(WED,
    { value: '3921', change_th: 'ปิด', trend: 'down', as_of: '2026-11-03T15:00:00Z', source: 'https://tradingeconomics.com/commodities' },   // 14 h of trading
    { value: '62700', change_th: 'ประกาศ', trend: 'up', as_of: '2026-11-03T02:30:00Z', source: 'https://www.goldtraders.or.th/' });  // Tue 09:30 BKK: 8 h Tue + 3 h Wed
  serve(WED, m, HIST(), WED - 14*HOUR);
  m.updated_at = iso(WED - 14*HOUR); writeData('market', m);
  const { ctx, page, errors } = await openGold(browser, { w: 375, h: 812, scheme: 'dark', dpr: 3 }, WED, false);
  for (const id of ['#gold-tile-main', '#gold-tile-th']) {
    await expect(page.locator(id + ' .live-tag')).toBeVisible();
    expect(await page.locator(id + ' .live-tag').innerText()).toBe('ข้อมูลเก่า');
    expect(await page.locator(id).getAttribute('class')).toContain('is-stale');
    expect(await page.locator(id + ' .live-tag .sdot').getAttribute('class')).toContain('stale');
  }
  expect(await page.locator('#gold-tile-main .val').textContent()).toBe('$3,921');
  // the header date is stale too (market.json 14 h old)
  expect(await page.locator('#updated').getAttribute('class')).toContain('is-stale');
  await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '90%')); await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOTS, 'gold-live-stale-375-dark.png') });
  expect(errors).toEqual([]);
  await ctx.close();
});

test('weekend: Friday close quotes are not stale', async ({ browser }) => {
  const m = market(SAT,
    { value: '3950', change_th: 'ปิดศุกร์', trend: 'up', as_of: '2026-11-06T21:30:00Z', source: 'https://tradingeconomics.com/commodities' },
    { value: '62800', change_th: 'ประกาศสุดท้ายวันศุกร์', trend: 'up', as_of: '2026-11-06T10:00:00Z', source: 'https://www.goldtraders.or.th/' });
  serve(SAT, m, HIST(), SAT - 3*HOUR);
  const { ctx, page, errors } = await openGold(browser, { w: 1280, h: 800, scheme: 'light', dpr: 1 }, SAT, false);
  for (const id of ['#gold-tile-main', '#gold-tile-th']) {
    await expect(page.locator(id + ' .live-tag')).toBeVisible();
    expect(await page.locator(id + ' .live-tag').innerText()).toBe('สด');
    expect(await page.locator(id).getAttribute('class')).not.toContain('is-stale');
  }
  // the Friday-night quote is Saturday in Bangkok; the last recorded earlier day is 4 Nov (within the 4-day window)
  expect(await page.locator('#gold-tile-main .delta').innerText()).toContain('จาก 4 พ.ย.');
  expect(errors).toEqual([]);
  await ctx.close();
});

test.afterAll(() => resetData());
