// The built site/index.html served over http://127.0.0.1/global-analysis/ with the seeded data/*.json
const { test, expect } = require('@playwright/test');
const path = require('path');
const { URL, SHOTS, collectErrors, noHScroll, seed } = require('./helpers');

const cases = [
  { name: 'desktop-dark', w: 1280, h: 800, scheme: 'dark' },
  { name: 'desktop-light', w: 1280, h: 800, scheme: 'light' },
  { name: 'mobile-dark', w: 390, h: 844, scheme: 'dark' },
  { name: 'mobile-light', w: 390, h: 844, scheme: 'light' },
];

async function noNullText(page, label) {
  const bad = await page.evaluate(() => {
    const t = document.getElementById('panel-body').innerText;
    return (t.match(/\bnull\b|\bNaN\b|undefined/g) || []).length;
  });
  expect(bad, `no null/NaN text (${label})`).toBe(0);
}
// fly to a record via the list, close the card, then tap the pin at screen centre
async function tapCentre(page, mobile) {
  await page.click('#view-detail .back');
  await expect(page.locator('#view-detail')).toBeHidden();
  const box = await page.locator('#stage canvas').boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
  await page.waitForTimeout(300);
  await expect(page.locator('#view-detail')).toBeVisible();
  return page.locator('#view-detail h2').textContent();
}

for (const c of cases) {
  const mobile = c.w < 500;
  test(`renders ${c.name}`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: c.w, height: c.h }, colorScheme: c.scheme, deviceScaleFactor: mobile ? 3 : 1, isMobile: mobile, hasTouch: mobile });
    const page = await ctx.newPage();
    const errors = collectErrors(page);
    await page.goto(URL.full);
    await page.waitForTimeout(3000);
    // live layer: the seeded data/*.json arrived through relative fetches
    const m = seed('market');
    await expect(page.locator('#live-slot .ticker .tk')).toHaveCount(m.items.length);
    expect(await page.locator('#live-slot .offline-bar').count()).toBe(0);
    expect(await page.locator('#live-slot .tk[data-key="brent"] .v').textContent()).toBe(m.items.find(i => i.key === 'brent').value);
    expect(await page.locator('#live-slot .live-head [data-age]').textContent()).toMatch(/^อัปเดตล่าสุด \d{1,2} \S+ 25\d\d \d\d:\d\d น\. \(/);
    expect(await page.locator('#foot-live').textContent()).toContain('อัปเดตล่าสุด');
    await expect(page.locator('#news-slot')).toBeVisible();
    await page.screenshot({ path: path.join(SHOTS, `${c.name}.png`) });
    expect(errors, 'console/page errors').toEqual([]);
    expect(await page.locator('#stage canvas').count()).toBe(1);
    expect(await page.locator('#fallback.on').count()).toBe(0);
    expect(await page.locator('#sample-badge').isHidden()).toBe(true);
    await noHScroll(page, 'initial');

    // header count line single row on mobile
    if (mobile) {
      const sub = await page.locator('.topbar .sub').boundingBox();
      expect(sub.height, 'count line is one row').toBeLessThan(24);
    }

    // (2) overview: 20 tiles, none overflowing; analysis 6 points, 4 risks
    expect(await page.locator('#view-overview .tile').count()).toBe(20);
    const overflow = await page.evaluate(() => Array.from(document.querySelectorAll('#view-overview .tile')).filter(t => t.scrollWidth > t.clientWidth + 1).map(t => t.querySelector('.lbl').textContent));
    expect(overflow, 'tiles overflowing').toEqual([]);
    const textOverflow = await page.evaluate(() => Array.from(document.querySelectorAll('#panel-body *')).filter(e => !e.closest('.ticker') && e.scrollWidth > document.getElementById('panel-body').clientWidth + 1).map(e => e.className || e.tagName).slice(0, 10));
    expect(textOverflow, 'elements wider than panel').toEqual([]);
    expect(await page.locator('#view-overview .points > li').count()).toBe(6);
    expect(await page.locator('#view-overview .risks > li').count()).toBe(4);
    expect(await page.locator('#view-overview .callout').count()).toBe(1);
    await noNullText(page, 'overview');
    // screenshot of the analysis section
    if (mobile) { await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '90%')); await page.waitForTimeout(400); }
    await page.locator('#view-overview .headline').scrollIntoViewIfNeeded();
    await page.evaluate(() => { const b = document.getElementById('panel-body'); b.scrollTop -= 40; });
    await page.waitForTimeout(200);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-analysis.png`) });
    await page.evaluate(() => { document.getElementById('panel-body').scrollTop = 0; });
    if (mobile) { await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '50%')); await page.waitForTimeout(400); }

    // (5) conflicts tab ordering + badges
    await page.click('.tab[data-tab="conflicts"]');
    const items = await page.locator('#view-conflicts .item').evaluateAll(els => els.map(e => ({ lvl: +e.querySelector('.meta b').textContent.replace(/\D/g, ''), st: e.querySelector('.st').textContent, nm: e.querySelector('.nm').textContent })));
    expect(items.length).toBe(25);
    for (let i = 1; i < items.length; i++) expect(items[i].lvl, 'sorted desc at ' + i).toBeLessThanOrEqual(items[i - 1].lvl);
    expect(items[0].lvl).toBe(5); expect(items[items.length - 1].lvl).toBe(1);
    const gaza = items.find(x => x.nm.startsWith('กาซา')); expect(gaza.st.startsWith('หยุดยิง')).toBe(true);
    const ukr = items.find(x => x.nm.startsWith('ยูเครน')); expect(ukr.st.startsWith('สงครามระหว่างรัฐ')).toBe(true);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-conflicts.png`) });

    // (3)+(4) Iran: open from list, long text in card, then tap the pin itself amid the Middle-East cluster
    await page.locator('#view-conflicts .item', { hasText: 'สงครามอิหร่าน' }).click();
    await expect(page.locator('#view-detail')).toBeVisible();
    await page.waitForTimeout(1300);
    await noHScroll(page, 'iran card');
    await noNullText(page, 'iran card');
    const cardScroll = await page.evaluate(() => { const b = document.getElementById('panel-body'); return [b.scrollHeight, b.clientHeight]; });
    console.log(`${c.name}: iran card scrollHeight=${cardScroll[0]} clientHeight=${cardScroll[1]}`);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-iran.png`) });
    const pickedIran = await tapCentre(page, mobile);
    console.log(`${c.name}: tap near Iran/Hormuz/Iraq cluster -> ${pickedIran}`);
    expect(pickedIran).toContain('อิหร่าน');
    expect(pickedIran).not.toContain('อิรัก');

    // Gaza vs Lebanon (~2 deg apart)
    await page.click('#view-detail .back');
    await page.locator('#view-conflicts .item', { hasText: 'กาซา' }).click();
    await page.waitForTimeout(1300);
    const pickedGaza = await tapCentre(page, mobile);
    console.log(`${c.name}: tap Gaza (Lebanon 2deg away) -> ${pickedGaza}`);
    expect(pickedGaza).toContain('กาซา');

    // (3) Thailand card via button, then pin tap; nulls in economies tab
    await page.click('#view-detail .back');
    await page.click('#btn-thai');
    await page.waitForTimeout(1400);
    await expect(page.locator('#view-detail h2')).toHaveText('ไทย');
    await noHScroll(page, 'thai card');
    await noNullText(page, 'thai card');
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-thai.png`) });
    const pickedThai = await tapCentre(page, mobile);
    expect(pickedThai).toBe('ไทย');

    await page.click('#view-detail .back');
    await page.click('.tab[data-tab="economies"]');
    expect(await page.locator('#view-economies .item').count()).toBe(21);
    await noNullText(page, 'economies list');
    const argText = await page.locator('#view-economies .item', { hasText: 'อาร์เจนตินา' }).innerText();
    expect(argText).toContain('—');
    await page.locator('#view-economies .item', { hasText: 'อาร์เจนตินา' }).click();
    await noNullText(page, 'argentina card');
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(SHOTS, `${c.name}-argentina.png`) });
    await noHScroll(page, 'end');
    expect(errors).toEqual([]);
    await ctx.close();
  });
}
