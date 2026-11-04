// Indicator tiles mapped in tools/live_indicators.json take their value from market.json (updated every hour)
// when the market item is newer than the indicator's as_of day; otherwise (or offline) the static value stays.
// Expectations are read from the data files, so a data update does not break this spec.
const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const { URL, writeData, resetData, collectErrors, repoll, seed } = require('./helpers');

const ROOT = path.join(__dirname, '..', '..');
const LIVE_IND = JSON.parse(fs.readFileSync(path.join(ROOT, 'tools', 'live_indicators.json'), 'utf8'));
const WORLD = JSON.parse(fs.readFileSync(path.join(ROOT, 'data', 'world-data.json'), 'utf8'));
const indicator = (label) => WORLD.indicators.find(i => i.label_th === label);
const fmt = (v, m) => (m.prefix || '') + Number(v).toLocaleString('en-US', { minimumFractionDigits: m.decimals, maximumFractionDigits: m.decimals });
const num = (s) => parseFloat(String(s).replace(/[^0-9.\-]/g, ''));
const tile = (page, label) => page.locator(`#view-overview .tile[data-ind="${label}"]`);

test.beforeEach(() => resetData());
test.afterAll(() => resetData());

test('mapped indicator tiles show the live market.json value with its own time', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const errors = collectErrors(page);
  await page.goto(URL.full);
  await page.waitForTimeout(2500);
  const market = seed('market');
  let liveCount = 0;
  for (const m of LIVE_IND) {
    const ind = indicator(m.label);
    if (!ind) continue;
    const it = market.items.find(x => x.key === m.key);
    const t = tile(page, m.label);
    await expect(t).toHaveCount(1);
    const newer = it && it.as_of && Date.parse(it.as_of) > Date.parse(ind.as_of + 'T23:59:59+07:00');
    if (newer) {
      liveCount++;
      await expect(t).toHaveClass(/is-live/);
      expect(await t.locator('.val').textContent()).toBe(fmt(num(it.value), m));
      expect(await t.locator('.src .live-asof').textContent()).toMatch(/^ณ \d{1,2} \S+ 25\d\d \d\d:\d\d น\.$/);
    } else {
      await expect(t).not.toHaveClass(/is-live/);
      expect(await t.locator('.val').textContent()).toBe(ind.value);
    }
  }
  expect(liveCount, 'at least one tile is live with the seeded market.json').toBeGreaterThan(0);
  // a tile without a live mapping keeps its static value
  const staticInd = WORLD.indicators.find(i => !LIVE_IND.some(m => m.label === i.label_th));
  await expect(tile(page, staticInd.label_th)).not.toHaveClass(/is-live/);
  expect(await tile(page, staticInd.label_th).locator('.val').textContent()).toBe(staticInd.value);
  expect(errors).toEqual([]);
  await ctx.close();
});

test('offline: indicator tiles fall back to the static values', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  await page.goto(URL.nodata);
  await page.waitForTimeout(2500);
  for (const m of LIVE_IND) {
    const ind = indicator(m.label);
    if (!ind) continue;
    await expect(tile(page, m.label)).not.toHaveClass(/is-live/);
    expect(await tile(page, m.label).locator('.val').textContent()).toBe(ind.value);
  }
  await ctx.close();
});

test('a market item older than the indicator is not used, a newer one is (re-poll)', async ({ browser }) => {
  const m = LIVE_IND.find(x => indicator(x.label));
  const ind = indicator(m.label);
  const market = seed('market');
  const old = JSON.parse(JSON.stringify(market));
  old.items = old.items.map(x => x.key === m.key ? { ...x, value: '123.45', as_of: ind.as_of + 'T00:00:00Z' } : x);
  writeData('market', old);
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const errors = collectErrors(page);
  await page.goto(URL.mutable);
  await page.waitForTimeout(2500);
  await expect(tile(page, m.label)).not.toHaveClass(/is-live/);
  expect(await tile(page, m.label).locator('.val').textContent()).toBe(ind.value);
  const fresh = JSON.parse(JSON.stringify(market));
  fresh.updated_at = new Date().toISOString();
  fresh.items = fresh.items.map(x => x.key === m.key ? { ...x, value: '123.45', as_of: new Date(Date.now() - 600000).toISOString() } : x);
  writeData('market', fresh);
  await repoll(page);
  await expect(tile(page, m.label)).toHaveClass(/is-live/);
  expect(await tile(page, m.label).locator('.val').textContent()).toBe(fmt(123.45, m));
  expect(errors).toEqual([]);
  await ctx.close();
});
