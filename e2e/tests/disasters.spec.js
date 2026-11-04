// The ภัยพิบัติ tab: data/disasters.json (updater/disasters.py, GDACS + USGS) as a list, globe pins,
// detail card, overview summary, disaster-tagged headlines, stale / failed-feed / empty states.
const { test, expect } = require('@playwright/test');
const path = require('path');
const { URL, SHOTS, writeData, removeData, resetData, collectErrors, noHScroll, repoll, seed } = require('./helpers');

const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString().replace(/\.\d{3}Z$/, 'Z');
const MIN = 60000, HOUR = 3600000;
const RANK = { red: 0, orange: 1, yellow: 2, green: 3 };

const cases = [
  { name: 'desktop-dark', w: 1280, h: 800, scheme: 'dark' },
  { name: 'desktop-light', w: 1280, h: 800, scheme: 'light' },
  { name: 'mobile375-dark', w: 375, h: 812, scheme: 'dark' },
  { name: 'mobile375-light', w: 375, h: 812, scheme: 'light' },
];
const ctxOpts = (c) => ({ viewport: { width: c.w, height: c.h }, colorScheme: c.scheme, deviceScaleFactor: c.w < 500 ? 3 : 1, isMobile: c.w < 500, hasTouch: c.w < 500 });

// five tabs on one row, no label clipped, nothing scrolling sideways
async function tabsFit(page, label) {
  const t = await page.evaluate(() => {
    const tabs = Array.from(document.querySelectorAll('#tabs .tab'));
    const bar = document.getElementById('tabs');
    return { labels: tabs.map(e => e.textContent), tops: tabs.map(e => Math.round(e.getBoundingClientRect().top)),
      heights: tabs.map(e => Math.round(e.getBoundingClientRect().height)), clipped: tabs.filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent),
      bar: [bar.scrollWidth, bar.clientWidth], right: Math.max(...tabs.map(e => e.getBoundingClientRect().right)), barRight: bar.getBoundingClientRect().right };
  });
  expect(t.labels, label).toEqual(['ภาพรวม', 'ความขัดแย้ง', 'ภัยพิบัติ', 'เศรษฐกิจ', 'ทองคำ']);
  expect(new Set(t.tops).size, `tabs on one row (${label})`).toBe(1);
  expect(Math.max(...t.heights), `tab labels not wrapped (${label})`).toBeLessThan(44);
  expect(t.clipped, `tab labels not clipped (${label})`).toEqual([]);
  expect(t.bar[0], `tab bar does not scroll (${label})`).toBeLessThanOrEqual(t.bar[1]);
  expect(t.right, `last tab inside the bar (${label})`).toBeLessThanOrEqual(t.barRight + 0.5);
}

test.beforeEach(() => resetData());
test.afterAll(() => resetData());

for (const c of cases) {
  const mobile = c.w < 500;
  test(`disasters tab, pins and detail (${c.name})`, async ({ browser }) => {
    const dz = seed('disasters');
    const ctx = await browser.newContext(ctxOpts(c));
    const page = await ctx.newPage();
    const errors = collectErrors(page);
    await page.goto(URL.full);
    await expect(page.locator('#live-slot .ticker .tk').first()).toBeVisible();
    await expect(page.locator('#dz-slot')).toBeVisible();
    await tabsFit(page, c.name);
    await noHScroll(page, 'initial');

    // overview: compact summary that opens the tab
    const nRed = dz.items.filter(i => i.alert_level === 'red').length;
    const sum = await page.locator('#dz-slot .dz-sum .cnt').textContent();
    expect(sum).toContain(dz.items.length + ' เหตุการณ์');
    if (nRed) expect(sum).toContain('เตือนแดง ' + nRed);
    expect(await page.locator('#dz-slot li').count()).toBe(Math.min(3, dz.items.length));
    if (!mobile) expect(await page.locator('#counts .full').textContent()).toContain(dz.items.length + ' ภัยพิบัติ');
    await page.locator('#dz-slot .dz-sum').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(SHOTS, `disasters-${c.name}-overview.png`) });

    await page.click('#dz-slot .dz-sum');
    await expect(page.locator('#view-disasters')).toBeVisible();
    expect(await page.locator('.tab[data-tab="disasters"]').getAttribute('aria-selected')).toBe('true');
    const rows = page.locator('#view-disasters .list.dz .item');
    await expect(rows).toHaveCount(dz.items.length);
    // red first, then orange, ..., newest first inside a level
    const shown = await rows.evaluateAll(els => els.map(e => ({ id: e.getAttribute('data-id'), nm: e.querySelector('.nm').textContent, meta: e.querySelector('.meta b').textContent })));
    const order = dz.items.slice().sort((a, b) => (RANK[a.alert_level] ?? 4) - (RANK[b.alert_level] ?? 4) || Date.parse(b.start) - Date.parse(a.start));
    expect(shown.map(s => s.id)).toEqual(order.map(i => i.id));
    expect(shown.map(s => s.nm)).toEqual(order.map(i => i.title_th));
    if (nRed) expect(shown[0].meta).toBe('แดง');
    // every row: icon, Thai title, a time, a source link; nothing clipped
    expect(await page.locator('#view-disasters .item .dz-ic svg').count()).toBe(dz.items.length);
    expect(await page.locator('#view-disasters .item .st a').count()).toBe(dz.items.length);
    const clipped = await page.evaluate(() => Array.from(document.querySelectorAll('#view-disasters .item .nm, #view-disasters .item .st, #view-disasters .item .meta')).filter(e => e.scrollWidth > e.clientWidth + 1).map(e => e.textContent));
    expect(clipped, 'disaster text clipped').toEqual([]);
    const wide = await page.evaluate(() => Array.from(document.querySelectorAll('#panel-body *')).filter(e => e.scrollWidth > document.getElementById('panel-body').clientWidth + 1).map(e => e.className || e.tagName).slice(0, 5));
    expect(wide, 'elements wider than panel').toEqual([]);
    const head = await page.locator('#dz-head [data-age]').textContent();
    expect(head).toMatch(/^อัปเดตล่าสุด \d{1,2} \S+ 25\d\d \d\d:\d\d น\. \(/);
    expect(await page.locator('#view-disasters .dz-src').innerText()).toContain('GDACS');
    const txt = await page.locator('#panel-body').innerText();
    expect((txt.match(/\bnull\b|\bNaN\b|undefined/g) || []).length).toBe(0);
    await tabsFit(page, c.name + ' on the tab');
    if (mobile) { await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '90%')); await page.waitForTimeout(400); }
    await page.screenshot({ path: path.join(SHOTS, `disasters-${c.name}.png`) });
    if (mobile) { await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '50%')); await page.waitForTimeout(400); }

    // row -> detail card, globe flies to the pin; the pin itself is clickable
    await rows.first().click();
    await expect(page.locator('#view-detail')).toBeVisible();
    expect(await page.locator('#view-detail h2').textContent()).toBe(order[0].title_th);
    const links = await page.locator('#view-detail .sources a').evaluateAll(as => as.map(a => a.href));
    expect(links[0]).toBe(order[0].source_url);
    expect(await page.locator('#view-detail .pill.alert').textContent()).toMatch(/^เตือนระดับ|^ไม่มีระดับเตือน/);
    await page.waitForTimeout(1400);
    await noHScroll(page, 'detail');
    await page.screenshot({ path: path.join(SHOTS, `disasters-${c.name}-detail.png`) });
    await page.click('#view-detail .back');
    await expect(page.locator('#view-disasters')).toBeVisible();
    await rows.first().click();          // fly there again so the auto-rotation has not started
    await page.waitForTimeout(1100);
    await page.click('#view-detail .back');
    const box = await page.locator('#stage canvas').boundingBox();
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(300);
    await expect(page.locator('#view-detail')).toBeVisible();
    expect(await page.locator('#view-detail h2').textContent(), 'tap the disaster pin at the centre').toBe(order[0].title_th);
    await page.click('#view-detail .back');

    // the layer chip hides the disaster pins: a tap at the same spot no longer opens it
    await page.click('#tg-disasters');
    expect(await page.locator('#tg-disasters').getAttribute('aria-pressed')).toBe('false');
    await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
    await page.waitForTimeout(300);
    const h2 = await page.locator('#view-detail').isVisible() ? await page.locator('#view-detail h2').textContent() : '';
    expect(h2).not.toBe(order[0].title_th);
    await page.click('#tg-disasters');
    expect(errors, 'console/page errors').toEqual([]);
    await ctx.close();
  });
}

function dzDoc(over = {}) {
  const base = seed('disasters');
  return { ...base, updated: iso(30 * MIN), checked: iso(30 * MIN), ...over };
}

test('failed feed, stale data, missing file and empty list (mobile 375 light)', async ({ browser }) => {
  const heads = seed('headlines');
  heads.items[1] = { ...heads.items[1], conflict_id: 'disaster', title_th: 'ไต้ฝุ่นขึ้นฝั่งเวียดนามตอนกลาง ฝนตกหนักถึงภาคอีสานของไทย', source: 'https://www.example.com/typhoon', source_name: 'Example' };
  writeData('headlines', heads);
  writeData('disasters', dzDoc());
  const ctx = await browser.newContext(ctxOpts({ w: 375, h: 812, scheme: 'light' }));
  const page = await ctx.newPage();
  const errors = collectErrors(page, [/404/]);
  await page.goto(URL.mutable);
  await expect(page.locator('#live-slot .ticker .tk').first()).toBeVisible();
  await page.click('.tab[data-tab="disasters"]');
  const note = page.locator('#dz-head .note');
  await expect(page.locator('#view-disasters .list.dz .item')).toHaveCount(seed('disasters').items.length);
  await expect(note).toBeHidden();
  expect(await page.locator('#dz-head .sdot').getAttribute('class')).toContain('fresh');
  // disaster-tagged headline shows in the tab with its tag
  await expect(page.locator('#dz-news .news li')).toHaveCount(1);
  expect(await page.locator('#dz-news .news li .tag').textContent()).toBe('ภัยพิบัติ');
  expect(await page.locator('#dz-news .news li .nt').textContent()).toContain('ไต้ฝุ่น');

  // 1. one feed failed this round -> its message, warning colour
  writeData('disasters', dzDoc({ ok: false, message_th: 'โหลดข้อมูลจาก USGS ไม่สำเร็จรอบนี้ แสดงเหตุการณ์จากรอบก่อนของแหล่งนั้น' }));
  await repoll(page);
  await expect(note).toHaveText('โหลดข้อมูลจาก USGS ไม่สำเร็จรอบนี้ แสดงเหตุการณ์จากรอบก่อนของแหล่งนั้น');
  expect(await note.getAttribute('class')).toContain('warn');

  // 2. older than 10 h -> stale marker
  writeData('disasters', dzDoc({ updated: iso(11 * HOUR), checked: iso(11 * HOUR) }));
  await repoll(page);
  await expect(note).toContainText('ข้อมูลภัยพิบัติเก่ากว่า 6 ชม.');
  expect(await page.locator('#dz-head').getAttribute('class')).toContain('is-stale');
  expect(await page.locator('#dz-head .sdot').getAttribute('class')).toContain('stale');
  expect(await page.locator('#dz-head [data-age]').textContent()).toContain('(11 ชม. ที่แล้ว)');
  await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '90%'));
  await page.waitForTimeout(400);
  await noHScroll(page, 'stale');
  await page.screenshot({ path: path.join(SHOTS, 'disasters-stale-mobile375-light.png') });

  // 3. the file disappears -> last list kept, prices are NOT marked as failed
  removeData('disasters');
  await repoll(page);
  await expect(note).toHaveText('โหลดข้อมูลภัยพิบัติรอบล่าสุดไม่สำเร็จ แสดงรายการล่าสุดที่ได้รับ');
  await expect(page.locator('#view-disasters .list.dz .item')).toHaveCount(seed('disasters').items.length);
  expect(await page.evaluate(() => window.__liveState.fetchError)).toBe(false);

  // 4. nothing current -> clean empty state, overview summary hidden
  writeData('disasters', dzDoc({ items: [], feeds: { gdacs: { ...seed('disasters').feeds.gdacs, count: 0 }, usgs: { ...seed('disasters').feeds.usgs, count: 0 } } }));
  await repoll(page);
  await expect(page.locator('#view-disasters .dz-empty')).toHaveText(/^ขณะนี้ไม่มีภัยพิบัติที่ GDACS เตือนระดับส้มหรือแดง/);
  await expect(note).toBeHidden();
  expect(await page.locator('#view-disasters .list.dz').count()).toBe(0);
  await page.click('.tab[data-tab="overview"]');
  await expect(page.locator('#dz-slot')).toBeHidden();
  await page.click('.tab[data-tab="disasters"]');
  await page.screenshot({ path: path.join(SHOTS, 'disasters-empty-mobile375-light.png') });
  expect(errors).toEqual([]);
  await ctx.close();
});

test('no disasters.json at all: the tab says so and the rest of the page is fine (desktop dark)', async ({ browser }) => {
  removeData('disasters');
  const ctx = await browser.newContext(ctxOpts({ w: 1280, h: 800, scheme: 'dark' }));
  const page = await ctx.newPage();
  const errors = collectErrors(page, [/404/]);
  await page.goto(URL.mutable);
  await expect(page.locator('#live-slot .ticker .tk').first()).toBeVisible();
  expect(await page.locator('#live-slot .live-head .note').getAttribute('class')).not.toContain('warn');
  await expect(page.locator('#dz-slot')).toBeHidden();
  await page.click('.tab[data-tab="disasters"]');
  await expect(page.locator('#view-disasters .dz-empty')).toHaveText('โหลดข้อมูลภัยพิบัติไม่สำเร็จ จะลองใหม่อัตโนมัติ');
  expect(await page.locator('#counts .full').textContent()).not.toContain('ภัยพิบัติ');
  // it comes back on the next poll
  resetData();
  await repoll(page);
  await expect(page.locator('#view-disasters .list.dz .item')).toHaveCount(seed('disasters').items.length);
  await page.screenshot({ path: path.join(SHOTS, 'disasters-recovered-desktop-dark.png') });
  expect(errors).toEqual([]);
  await ctx.close();
});
