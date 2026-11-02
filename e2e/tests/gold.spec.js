// Gold panel: the static analysis (gold.json) is embedded in the page.
// Panel checks run against the "nodata" server (data/*.json 404 -> embedded values only);
// the live-override test rewrites data/market.json on the "mutable" server.
const { test, expect } = require('@playwright/test');
const path = require('path');
const { URL, SHOTS, noHScroll, writeData, resetData, repoll } = require('./helpers');
const DATA_404 = [/404/, /data\/(market|headlines|status)\.json/];

const cases = [
  { name: 'gold-mobile-dark', w: 390, h: 844, scheme: 'dark', dpr: 3 },
  { name: 'gold-mobile-light', w: 390, h: 844, scheme: 'light', dpr: 3 },
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
    expect(await page.locator('#gold-fc svg text', { hasText: 'ตอนนี้ $3,903' }).count()).toBe(1);
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

// live override: data/market.json carries gold / gold_th -> headline tiles show them with the "สด" tag;
// the next poll drops them -> embedded values return
test('live gold override from served data/market.json', async ({ browser }) => {
  resetData();
  const now = Date.now(); const iso = (ms) => new Date(now - ms).toISOString();
  writeData('market', { updated_at: iso(10*60000), items: [
    {key:'brent',label_th:'น้ำมัน Brent',value:'116.4',unit:'$/บาร์เรล',change_th:'+1.2% วันนี้',trend:'up'},
    {key:'gold',label_th:'ทองคำ',value:'3,842.50',unit:'$/ออนซ์',change_th:'−1.2% วันนี้',trend:'down',as_of:iso(12*60000),source:'https://www.investing.com/commodities/gold'},
    {key:'gold_th',label_th:'ทองแท่งขายออก',value:'61,900',unit:'บาท',change_th:'−350 บาท วันนี้',trend:'down',as_of:iso(8*60000),source:'https://www.goldtraders.or.th'} ]});
  writeData('status', { updated_at: iso(10*60000), run_count: 5, ok: true, message_th: 'ทดสอบ' });
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'dark', deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  const errors = collectErrors(page, false);
  await page.goto(URL.mutable);
  await expect(page.locator('#live-slot .tk[data-key="gold"]')).toBeVisible();
  await page.click('.tab[data-tab="gold"]');
  await expect(page.locator('#gold-tile-main .live-tag')).toBeVisible();
  expect(await page.locator('#gold-tile-main .val').textContent()).toBe('$3,843');
  expect(await page.locator('#gold-tile-main .delta').innerText()).toContain('−1.2% วันนี้');
  expect(await page.locator('#gold-tile-main .src').innerText()).toContain('สด');
  await expect(page.locator('#gold-tile-th .live-tag')).toBeVisible();
  expect(await page.locator('#gold-tile-th .val').textContent()).toBe('61,900');
  expect(await page.locator('#gold-tile-th .delta').innerText()).toContain('−350 บาท');
  expect(await page.locator('#gold-fc svg text', { hasText: 'ตอนนี้ $3,843' }).count()).toBe(1);
  await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '90%'));
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOTS, 'gold-live-mobile.png') });
  // next poll: the gold items are gone -> embedded values return
  writeData('market', { updated_at: iso(1000), items: [ {key:'brent',label_th:'น้ำมัน Brent',value:'117.0',unit:'$/บาร์เรล',change_th:'+1.7% วันนี้',trend:'up'} ]});
  await repoll(page);
  await expect(page.locator('#gold-tile-main .live-tag')).toBeHidden();
  expect(await page.locator('#gold-tile-main .val').textContent()).toBe('$3,903');
  expect(await page.locator('#gold-tile-th .live-tag').isHidden()).toBe(true);
  expect(await page.locator('#gold-tile-th .val').textContent()).toBe('62,500');
  expect(await page.locator('#gold-fc svg text', { hasText: 'ตอนนี้ $3,903' }).count()).toBe(1);
  expect(await page.locator('#live-slot .tk[data-key="brent"] .v').textContent()).toBe('117.0');
  expect(errors).toEqual([]);
  await ctx.close();
  resetData();
});
