// The click infographic and the storm and rain layer. Real pin clicks on the canvas, values compared with the data, honesty rules checked.
const { test, expect, webkit } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const { URL, SHOTS, collectErrors, seed, writeData, removeData, resetData } = require('./helpers');

const FX = path.join(__dirname, '..', 'fixtures');
const world = JSON.parse(fs.readFileSync(path.join(FX, 'world-data.json'), 'utf8'));
const gold = JSON.parse(fs.readFileSync(path.join(FX, 'gold.json'), 'utf8'));
const conflicts = world.conflicts.slice().sort((a, b) => (b.intensity || 0) - (a.intensity || 0));   // the page's own order
const PNG_RAIN = fs.readFileSync(path.join(FX, 'gibs-imerg.png'));
const PNG_BLANK = fs.readFileSync(path.join(FX, 'gibs-blank.png'));
const GIBS = /gibs\.earthdata\.nasa\.gov/;

async function ready(page, url = URL.full) {
  await page.goto(url + '?view=map');
  await page.waitForFunction(() => (window.__liveState || {}).polls > 0);
  await page.waitForFunction(() => window.__globeFx && window.__globeFx.stats());
}
const done = (page) => page.waitForFunction(() => window.__globeFx.state === 'done', null, { timeout: 20000 });
const pct = (v) => (v > 0 ? '+' : '') + Number(v).toFixed(1) + '%';

async function clickCentrePin(page) {
  const box = await page.locator('#stage canvas').boundingBox();
  await page.mouse.click(box.x + box.width / 2, box.y + box.height / 2);
}
// fly there, go back, then click the real pin at the centre of the canvas
async function realClick(page, kind, idx) {
  await page.evaluate(([k, i]) => window.__igSelect(k, i), [kind, idx]);
  await done(page);
  await page.waitForTimeout(1100);
  await page.click('#view-detail .back');
  await expect(page.locator('#view-detail')).toBeHidden();
  const before = await page.evaluate(() => window.__globeFx.plays);
  await clickCentrePin(page);
  await page.waitForFunction((n) => window.__globeFx.plays > n, before);
}
async function allFinal(page) {
  const r = await page.evaluate(() => ({
    play: document.querySelectorAll('.ig.play').length, run: document.querySelectorAll('.fx-hud.run').length,
    hidden: Array.from(document.querySelectorAll('.ig-rv')).filter((e) => +getComputedStyle(e).opacity < 1).length,
  }));
  expect(r).toEqual({ play: 0, run: 0, hidden: 0 });
}
// every arc on the globe has a row and a label, both naming its kind
async function arcsLabelled(page) {
  const r = await page.evaluate(() => ({
    arcs: window.__globeFx.arcs,
    gl: window.__globeFx.stats().arcs,
    rows: Array.from(document.querySelectorAll('.ig-link[data-arc="1"]')).map((li) => ({ rel: li.getAttribute('data-rel'), name: li.querySelector('.ig-go').textContent, kind: li.querySelector('.t em').textContent })),
    labels: Array.from(document.querySelectorAll('.fx-lb.on')).map((l) => ({ rel: l.getAttribute('data-rel'), name: l.children[1].textContent, kind: l.children[2].textContent })),
  }));
  const TH = { data: 'ข้อมูลระบุ', geo: 'ภูมิศาสตร์', mention: 'กล่าวถึง' };
  expect(r.gl).toBe(r.arcs.length);
  expect(r.rows.length).toBe(r.arcs.length);
  expect(r.labels.length).toBe(r.arcs.length);
  for (const a of r.arcs) {
    expect(Object.keys(TH)).toContain(a.rel);
    expect(r.rows.find((x) => x.name === a.name && x.rel === a.rel).kind).toBe(TH[a.rel]);
    expect(r.labels.find((x) => x.name === a.name.replace(/\s*\([^)]*\)\s*$/, '') && x.rel === a.rel).kind).toBe(TH[a.rel]);
  }
  // the label of a target behind the horizon hangs on the part of its arc in view, so none is left out
  await page.waitForTimeout(150);
  const hiddenLabels = await page.evaluate(() => Array.from(document.querySelectorAll('.fx-lb.on')).filter((l) => getComputedStyle(l).visibility === 'hidden').map((l) => l.textContent));
  expect(hiddenLabels).toEqual([]);
  return r.arcs;
}

test('a click on each kind of marker plays the sequence and ends on the true values', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, colorScheme: 'dark' });
  const page = await ctx.newPage();
  const errors = collectErrors(page);
  await ready(page);
  const market = seed('market').items, dz = seed('disasters').items;
  const mal = world.chokepoints.findIndex((c) => c.name_th.includes('มะละกา'));
  const hai = conflicts.findIndex((c) => c.id === 'haiti_gangs');
  const bra = world.economies.findIndex((e) => e.iso === 'BRA');

  // conflict
  await realClick(page, 'conflict', hai);
  await expect(page.locator('.ig.play')).toHaveCount(1);
  expect(await page.evaluate(() => window.__globeFx.state)).toBe('play');
  await done(page);
  await allFinal(page);
  await expect(page.locator('#view-detail h2')).toHaveText(conflicts[hai].name_th);
  expect(await page.locator('.ig-gauge [data-cu]').textContent()).toBe(String(conflicts[hai].intensity));
  await arcsLabelled(page);
  const deaths = (await page.locator('.ig-stat.wide').first().locator('.ig-fact').allTextContents()).join('; ');
  expect(deaths).toBe(conflicts[hai].deaths_est);

  // economy
  await realClick(page, 'econ', bra);
  await done(page);
  await allFinal(page);
  const e = world.economies[bra];
  await expect(page.locator('#view-detail h2')).toHaveText(e.name_th);
  expect(await page.locator('.ig-stat[data-v="gdp26"] [data-cu]').textContent()).toBe(pct(e.gdp_growth_2026));
  expect(await page.locator('.ig-stat[data-v="gdp27"] [data-cu]').textContent()).toBe(pct(e.gdp_growth_2027));
  await arcsLabelled(page);

  // chokepoint
  await realClick(page, 'choke', mal);
  await done(page);
  await allFinal(page);
  await expect(page.locator('#view-detail h2')).toHaveText(world.chokepoints[mal].name_th);
  expect(await page.locator('.ig-gauge [data-cu]').textContent()).toBe(String(world.chokepoints[mal].level));
  await arcsLabelled(page);

  // disaster: the first item with a size
  const order = await page.evaluate(() => Array.from(document.querySelectorAll('#view-disasters .item')).map((x) => x.getAttribute('data-id')));
  const di = order.findIndex((id) => { const it = dz.find((x) => x.id === id); return it && it.severity_value != null; });
  const d = dz.find((x) => x.id === order[di]);
  await realClick(page, 'disaster', di);
  await done(page);
  await allFinal(page);
  await expect(page.locator('#view-detail h2')).toHaveText(d.title_th);
  const sev = await page.locator('.ig-stat[data-v="severity"] [data-cu]').textContent();
  expect(Number(sev.replace(/,/g, ''))).toBeCloseTo(d.severity_value, d.severity_unit === 'M' ? 1 : -1);
  await arcsLabelled(page);
  for (const a of await page.evaluate(() => window.__globeFx.arcs)) if (a.rel === 'data') expect(a.tKind).toBe('econ');

  // gold: a pin of its own, and the live price
  await realClick(page, 'gold', 0);
  await done(page);
  await allFinal(page);
  await expect(page.locator('#view-detail h2')).toHaveText('ทองคำ');
  const spot = Math.round(Number(market.find((m) => m.key === 'gold').value)).toLocaleString('en-US');
  expect(await page.locator('.ig-stat[data-v="spot"] [data-cu]').textContent()).toBe('$' + spot);
  expect(await page.locator('.ig').innerText()).toContain('สัญลักษณ์');
  await arcsLabelled(page);
  await page.click('[data-gold-open]');
  await expect(page.locator('#view-gold')).toBeVisible();

  expect(errors).toEqual([]);
  await ctx.close();
});

test('honesty: every relation of every item can be traced to the data; no impact wording', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await ready(page);
  const out = await page.evaluate(() => {
    const c = window.__globeFx.counts(), all = [];
    for (const [k, n] of [['conflict', c.conflict], ['econ', c.econ], ['choke', c.choke], ['disaster', c.disaster], ['gold', 1]]) {
      for (let i = 0; i < n; i++) all.push({ kind: k, idx: i, rows: window.__globeFx.relations(k, i) });
    }
    return all;
  });
  const dz = await page.evaluate(() => Array.from(document.querySelectorAll('#view-disasters .item')).map((x) => x.getAttribute('data-id')));
  const dzItems = seed('disasters').items;
  const rec = (kind, i) => kind === 'conflict' ? conflicts[i] : kind === 'econ' ? world.economies[i] : kind === 'choke' ? world.chokepoints[i] : kind === 'disaster' ? dzItems.find((x) => x.id === dz[i]) : gold;
  const texts = (kind, r) => kind === 'conflict' ? [r.status_th, r.summary_th] : kind === 'gold' ? [].concat(gold.drivers_th.points, gold.supports_th.points, gold.outlook_th.risks_up, gold.outlook_th.risks_down) : [r.note_th];
  let seen = { data: 0, geo: 0, mention: 0 };
  for (const it of out) {
    const me = rec(it.kind, it.idx);
    for (const r of it.rows) {
      seen[r.rel]++;
      expect(r.text).not.toMatch(/กระทบ|ส่งผล|เป็นเหตุ|ทำให้/);
      const other = rec(r.kind, r.idx);
      if (r.rel === 'mention') {
        // the snippet is verbatim from one of the two items' text, and that item names a source
        const q = r.quote.replace(/^…|…$/g, '');
        const inMine = texts(it.kind, me).some((t) => (t || '').includes(q));
        const inOther = texts(r.kind, other).some((t) => (t || '').includes(q));
        expect(inMine || inOther, `snippet "${q}" of ${it.kind}:${it.idx}`).toBe(true);
        if (inMine && it.kind !== 'gold') { expect(r.src).toMatch(/^https:/); expect(me.sources).toContain(r.src); }
        if (!inMine) { expect(r.src).toMatch(/^https:/); expect(other.sources).toContain(r.src); }
      } else if (r.rel === 'data') {
        const dis = it.kind === 'disaster' ? me : other;
        expect(dis.countries.length).toBeGreaterThan(0);
        expect(r.src).toBe(dis.source_url);
      } else {
        expect(r.rel).toBe('geo');
        expect(r.text).toContain('คำนวณระยะทาง');
        expect(r.text).toMatch(/กม\./);
      }
      expect(['conflict', 'econ', 'choke', 'disaster']).toContain(r.kind);
    }
  }
  expect(seen.mention).toBeGreaterThan(10);
  expect(seen.geo).toBeGreaterThan(10);
  // the South China Sea is not China, the Gulf of Thailand is not Thailand
  const scs = out.find((x) => x.kind === 'conflict' && conflicts[x.idx].id === 'south_china_sea');
  expect(scs.rows.every((r) => !(r.rel === 'mention' && (r.text.includes('“ไทย”'))))).toBe(true);
  await ctx.close();
});

test('an item without relations draws no arcs and says nothing about links', async ({ browser }) => {
  resetData();
  const d0 = seed('disasters');
  const lonely = { ...d0.items[0], id: 'usgs-lonely1', type: 'earthquake', title_th: 'แผ่นดินไหวทดสอบกลางมหาสมุทรใต้', country: '', country_th: '', countries: [], lat: -62, lon: -135, alert_level: null, severity_th: 'ขนาด 5.0', severity_value: 5, severity_unit: 'M', source_name: 'USGS', source_url: 'https://earthquake.usgs.gov/x' };
  delete lonely.alt_source_url; delete lonely.alt_source_name;
  writeData('disasters', { ...d0, items: [lonely] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await ready(page, URL.mutable);
  await page.waitForFunction(() => window.__globeFx.counts().disaster === 1);
  await page.evaluate(() => window.__igSelect('disaster', 0));
  await done(page);
  expect(await page.evaluate(() => window.__globeFx.arcs)).toEqual([]);
  expect((await page.evaluate(() => window.__globeFx.stats())).arcs).toBe(0);
  await expect(page.locator('.fx-lb.on')).toHaveCount(0);
  await expect(page.locator('.ig-link')).toHaveCount(0);
  await expect(page.locator('#view-detail h2')).toHaveText(lonely.title_th);
  await ctx.close();
  resetData();
});

test('a second click cancels the running sequence cleanly', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const errors = collectErrors(page);
  await ready(page);
  const ua = conflicts.findIndex((c) => c.id === 'ukraine_russia'), tha = world.economies.findIndex((e) => e.iso === 'THA');
  await page.evaluate((i) => window.__igSelect('conflict', i), ua);
  await page.waitForTimeout(350);
  expect(await page.evaluate(() => window.__globeFx.state)).toBe('play');
  await page.evaluate((i) => window.__igSelect('econ', i), tha);
  expect(await page.evaluate(() => window.__globeFx.cancels)).toBe(1);
  await done(page);
  await allFinal(page);
  await expect(page.locator('#view-detail h2')).toHaveCount(1);
  await expect(page.locator('#view-detail h2')).toHaveText('ไทย');
  await arcsLabelled(page);
  expect(await page.locator('.ig-stat[data-v="gdp26"] [data-cu]').textContent()).toBe(pct(world.economies[tha].gdp_growth_2026));
  // leaving while it plays stops it too: no overlay, no card, no arcs
  await page.evaluate((i) => window.__igSelect('conflict', i), ua);
  await page.waitForTimeout(200);
  await page.keyboard.press('Escape');
  await expect(page.locator('#view-detail')).toBeHidden();
  await expect(page.locator('#fx-hud')).toBeHidden();
  expect(await page.evaluate(() => window.__globeFx.state)).toBe('idle');
  await expect(page.locator('#stage.has-fx')).toHaveCount(0);
  expect(errors).toEqual([]);
  await ctx.close();
});

test('prefers-reduced-motion skips the sequence and shows the final state at once', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: 'reduce' });
  const page = await ctx.newPage();
  await ready(page);
  const tha = world.economies.findIndex((e) => e.iso === 'THA');
  const st = await page.evaluate((i) => { window.__igSelect('econ', i); return { state: window.__globeFx.state, play: document.querySelectorAll('.ig.play').length, val: document.querySelector('.ig-stat[data-v="gdp26"] [data-cu]').textContent, hidden: Array.from(document.querySelectorAll('.ig-rv')).filter((e) => +getComputedStyle(e).opacity < 1).length, run: document.querySelectorAll('.fx-hud.run').length }; }, tha);
  expect(st).toEqual({ state: 'done', play: 0, val: pct(world.economies[tha].gdp_growth_2026), hidden: 0, run: 0 });
  await arcsLabelled(page);
  await page.waitForTimeout(120);
  const s = await page.evaluate(() => window.__globeFx.stats());
  expect(s.camLat).toBeCloseTo(world.economies[tha].lat, 1);
  await ctx.close();
});

test('keyboard: a list item opens the card, links go through, Escape closes', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await ready(page);
  await page.click('.tab[data-tab="conflicts"]');
  await page.locator('#view-conflicts .item', { hasText: 'สงครามอิหร่าน' }).focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#view-detail h2')).toContainText('อิหร่าน');
  await done(page);
  const go = page.locator('.ig-go').first(), name = await go.textContent();
  await go.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('#view-detail h2')).toHaveText(name);
  await done(page);
  await page.keyboard.press('Escape');
  await expect(page.locator('#view-detail')).toBeHidden();
  await expect(page.locator('#view-conflicts')).toBeVisible();
  await ctx.close();
});

test('pooled objects: many clicks and weather switches add nothing; counts are logged', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await page.route(GIBS, (r) => r.fulfill({ status: 200, contentType: 'image/png', body: PNG_RAIN }));
  await ready(page);
  const idle = await page.evaluate(() => new Promise((ok) => requestAnimationFrame(() => requestAnimationFrame(() => ok(window.__globeFx.stats())))));
  console.log('idle (with gold pin)', JSON.stringify(idle));
  for (let i = 0; i < 8; i++) await page.evaluate((n) => window.__igSelect('conflict', n), i);
  await done(page);
  await page.waitForTimeout(200);
  const one = await page.evaluate(() => window.__globeFx.stats());
  console.log('playing', JSON.stringify(one));
  for (let i = 0; i < 12; i++) await page.evaluate((n) => window.__igSelect('econ', n), i);
  await done(page);
  await page.waitForTimeout(200);
  const two = await page.evaluate(() => window.__globeFx.stats());
  expect(two.objects).toBe(one.objects);
  expect(two.geometries).toBe(one.geometries);
  expect(two.textures).toBe(0);
  expect(two.calls).toBeLessThanOrEqual(idle.calls + 4);   // the existing highlight ring, then ripple, arcs, landing pulses
  await page.click('#tg-weather');
  await page.waitForFunction(() => window.__globeFx.weather().gl.rainDots > 0 && window.__globeFx.weather().gl.stormDots >= 0 && window.__globeFx.weather().storms !== null);
  await page.waitForTimeout(200);
  const w1 = await page.evaluate(() => window.__globeFx.stats());
  console.log('weather on', JSON.stringify(w1), JSON.stringify(await page.evaluate(() => window.__globeFx.weather())));
  expect(w1.calls).toBeLessThanOrEqual(two.calls + 3);
  for (let i = 0; i < 4; i++) { await page.click('#tg-weather'); await page.waitForTimeout(60); await page.click('#tg-weather'); await page.waitForTimeout(60); }
  await page.waitForTimeout(400);
  const w2 = await page.evaluate(() => window.__globeFx.stats());
  expect(w2.geometries).toBe(w1.geometries);
  expect(w2.objects).toBe(w1.objects);
  await ctx.close();
});

for (const w of [360, 390]) {
  test(`phone ${w}: the drawer holds the card, no horizontal overflow against the fixed width`, async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: w, height: 760 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: 'dark' });
    const page = await ctx.newPage();
    const errors = collectErrors(page);
    await page.route(GIBS, (r) => r.fulfill({ status: 200, contentType: 'image/png', body: PNG_RAIN }));
    await ready(page);
    const check = async (label) => {
      const v = await page.evaluate((FIXED) => ({ doc: document.documentElement.scrollWidth, body: document.body.scrollWidth,
        wide: Array.from(document.querySelectorAll('#panel *, .fx-bar, .wx-box')).filter((e) => { if (e.closest('.ticker') || !e.checkVisibility()) return false; const b = e.getBoundingClientRect(); return b.width > 0 && (b.right > FIXED + 0.5 || b.left < -0.5); }).map((e) => String(e.className || e.tagName)).slice(0, 4) }), w);
      expect(v.doc, label).toBeLessThanOrEqual(w);
      expect(v.body, label).toBeLessThanOrEqual(w);
      expect(v.wide, label).toEqual([]);
    };
    for (const [k, i] of [['conflict', 0], ['econ', 20], ['choke', 0], ['disaster', 0], ['gold', 0]]) {
      await page.evaluate(([kk, ii]) => window.__igSelect(kk, ii), [k, i]);
      await done(page);
      await check(`${k} ${w}`);
      await expect(page.locator('.ig-hero')).toBeVisible();
      await expect(page.locator('#footnote')).toBeHidden();
      await page.screenshot({ path: path.join(SHOTS, `infographic-${w}-${k}.png`) });
    }
    await page.click('#tg-weather');
    await page.waitForFunction(() => window.__globeFx.weather().rainAt);
    await check(`weather ${w}`);
    await page.click('#view-detail .back');
    await check(`weather, no card ${w}`);
    await expect(page.locator('#footnote')).toBeVisible();
    expect(errors).toEqual([]);
    await ctx.close();
  });
}

test('storm and rain layer: off and not fetched until pressed; labelled, dated, credited; off again removes it', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const errors = collectErrors(page);
  const reqs = [], probes = [];
  page.on('request', (r) => reqs.push(r.url()));
  let blanks = 2;
  await page.route(GIBS, (r) => { probes.push(r.request().url()); if (blanks-- > 0) return r.fulfill({ status: 200, contentType: 'image/png', body: PNG_BLANK }); return r.fulfill({ status: 200, contentType: 'image/png', body: PNG_RAIN }); });
  await ready(page);
  await page.waitForTimeout(800);
  expect(reqs.filter((u) => /storms\.json/.test(u) || GIBS.test(u))).toEqual([]);
  await expect(page.locator('#tg-weather')).toHaveAttribute('aria-pressed', 'false');
  await expect(page.locator('#wx-box')).toBeHidden();

  await page.click('#tg-weather');
  await expect(page.locator('#tg-weather')).toHaveAttribute('aria-pressed', 'true');
  await page.waitForFunction(() => { const w = window.__globeFx.weather(); return w.rainAt && w.storms !== null; });
  const w = await page.evaluate(() => window.__globeFx.weather());
  expect(w.gl.rainDots).toBeGreaterThan(100);
  expect(w.gl.rainDots).toBeLessThan(6000);
  // newest first: the first two times were blank, so the shown time is one hour older than the first asked
  expect(probes.length).toBe(3);
  const times = probes.map((u) => Date.parse(/TIME=([^&]+)/.exec(u)[1]));
  expect(times[0] - times[1]).toBe(1800000);
  expect(Date.parse(w.rainAt)).toBe(times[2]);
  // the summary stays visible while the box is shut: time, not a forecast, the credit
  const shut = await page.locator('#wx-box summary').innerText();
  expect(shut).toMatch(/ฝน ณ \d{1,2} \S+ 25\d\d \d\d:\d\d น\./);
  expect(shut).toContain('ไม่ใช่พยากรณ์');
  expect(shut).toContain('NASA GIBS/IMERG');
  expect(shut).toContain('GDACS');
  await page.click('#wx-box summary');
  const txt = await page.locator('#wx-box').innerText();
  expect(txt).toContain('ฝนและหิมะ');
  expect(txt).toMatch(/ภาพ ณ \d{1,2} \S+ 25\d\d \d\d:\d\d น\./);
  expect(txt).toContain('ไม่ใช่พยากรณ์');
  expect(txt).toContain('ไม่ควรใช้ตัดสินใจ');
  expect(txt).toContain('GIBS');
  expect(txt).toContain('IMERG');
  expect(txt).toContain('NASA');
  expect(txt).toContain('GDACS');
  expect(await page.locator('[data-wx-warn]').count()).toBe(0);
  await expect(page.locator('[data-wx-credit] a', { hasText: 'GDACS' })).toHaveAttribute('href', 'https://www.gdacs.org/');
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOTS, 'weather-on-desktop.png') });

  await page.click('#tg-weather');
  await expect(page.locator('#wx-box')).toBeHidden();
  const off = await page.evaluate(() => window.__globeFx.weather().gl);
  expect(off).toMatchObject({ on: false, rainDots: 0, stormDots: 0, swirlDots: 0 });
  expect(errors).toEqual([]);
  await ctx.close();
});

test('storm feed: failed, ok=false, stale and empty are all said plainly', async ({ browser }) => {
  resetData();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await page.route(GIBS, (r) => r.fulfill({ status: 200, contentType: 'image/png', body: PNG_RAIN }));
  const errors = collectErrors(page, [/404/, /storms\.json/]);
  const storms = JSON.parse(fs.readFileSync(path.join(__dirname, '..', '..', 'site', 'data', 'storms.json'), 'utf8'));
  const iso = (ago) => new Date(Date.now() - ago).toISOString().replace(/\.\d+Z$/, 'Z');
  const open = async (doc) => { if (doc) writeData('storms', doc); else removeData('storms'); await ready(page, URL.mutable); await page.click('#tg-weather'); await page.waitForFunction(() => { const w = window.__globeFx.weather(); return w.rainAt && (w.storms !== null || w.stormsErr); }); };
  // the file is missing
  await open(null);
  expect(await page.locator('[data-wx-warn="storm"]').textContent()).toContain('ไม่สำเร็จ');
  expect((await page.evaluate(() => window.__globeFx.weather())).gl.rainDots).toBeGreaterThan(100);
  // the updater kept old data and said so
  await open({ ...storms, updated: iso(3600000), ok: false, message_th: 'โหลดข้อมูลพายุจาก GDACS ไม่สำเร็จรอบนี้ แสดงข้อมูลล่าสุดที่ได้รับ' });
  expect(await page.locator('[data-wx-warn="storm"]').textContent()).toContain('GDACS ไม่สำเร็จ');
  await expect(page.locator('#wx-box summary.warn')).toHaveCount(1);
  // nobody has updated it for ten hours
  await open({ ...storms, updated: iso(10 * 3600000), ok: true, message_th: '' });
  expect(await page.locator('[data-wx-warn="storm"]').textContent()).toContain('เก่ากว่า 6 ชม.');
  // no storms is a plain statement, no warning
  await open({ ...storms, updated: iso(60000), ok: true, message_th: '', items: [] });
  await expect(page.locator('[data-wx-warn]')).toHaveCount(0);
  expect(await page.locator('[data-wx-storm]').textContent()).toContain('ไม่มีในขณะนี้');
  expect(errors).toEqual([]);
  await ctx.close();
  resetData();
});

test('rain feed: network blocked, nothing published, and an old picture are said plainly; the page keeps working', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const errors = collectErrors(page, [/gibs\.earthdata/, /ERR_FAILED/, /Failed to load resource/]);
  let mode = 'block', served = 0;
  await page.route(GIBS, (r) => {
    if (mode === 'block') return r.abort();
    served++;
    if (mode === 'blank') return r.fulfill({ status: 200, contentType: 'image/png', body: PNG_BLANK });
    return r.fulfill({ status: 200, contentType: 'image/png', body: served > 20 ? PNG_RAIN : PNG_BLANK });
  });
  const open = async () => { await ready(page); await page.click('#tg-weather'); await page.waitForFunction(() => { const w = window.__globeFx.weather(); return !w.busy && w.storms !== null && (w.rainAt || w.rainMsg); }); };
  await open();
  expect(await page.locator('[data-wx-warn="rain"]').textContent()).toContain('โหลดภาพฝนไม่สำเร็จ');
  expect((await page.evaluate(() => window.__globeFx.weather())).gl.rainDots).toBe(0);
  await expect(page.locator('#wx-box summary')).toContainText('ไม่มีภาพฝน');
  // the rest of the globe still answers
  await page.evaluate(() => window.__igSelect('conflict', 0));
  await done(page);
  await expect(page.locator('#view-detail h2')).toHaveText(conflicts[0].name_th);

  mode = 'blank'; await open();
  expect(await page.locator('[data-wx-warn="rain"]').textContent()).toContain('ไม่พบภาพฝน');
  expect((await page.evaluate(() => window.__globeFx.weather())).requests).toBe(22);

  mode = 'old'; served = 0; await open();
  expect(await page.locator('[data-wx-warn="rain"]').textContent()).toContain('เก่ากว่า 12 ชม.');
  expect((await page.evaluate(() => window.__globeFx.weather())).gl.rainDots).toBeGreaterThan(100);
  expect(errors).toEqual([]);
  await ctx.close();
});

test('?view=read loads neither three.js nor the layer data, whatever happens on the page', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, storageState: { cookies: [], origins: [] } });
  const page = await ctx.newPage();
  const reqs = [];
  page.on('request', (r) => reqs.push(r.url()));
  await page.goto(URL.full + '?view=read');
  await page.waitForFunction(() => (window.__liveState || {}).polls > 0);
  await page.waitForTimeout(800);
  expect(reqs.filter((u) => /three|storms\.json|gibs\.earthdata/.test(u))).toEqual([]);
  await expect(page.locator('#tg-weather')).toBeHidden();
  await expect(page.locator('.ig')).toHaveCount(0);
  await ctx.close();
});

test('gold tab: the Thai price labels carry no fixed date', async ({ browser }) => {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  await ready(page);
  await page.click('.tab[data-tab="gold"]');
  const keys = (await page.locator('#gold-th-kv .k').allTextContents()).filter((x) => /^(ปิด|ปรับ)/.test(x));
  expect(keys.length).toBe(3);
  for (const k of keys) expect(k).toMatch(/^(ปิดวันศุกร์|ปรับวันเสาร์|ปรับวันอาทิตย์) \(ข้อมูล ณ \d{1,2} \S+\)$/);
  await ctx.close();
});

test('headless WebKit at 390 px: a click plays and ends right, the layer opens', async () => {
  test.skip(!fs.existsSync(webkit.executablePath()), 'WebKit is not installed here');
  const b = await webkit.launch({ headless: true });
  const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true, colorScheme: 'dark',
    storageState: { cookies: [], origins: [{ origin: new (require('url').URL)(URL.full).origin, localStorage: [{ name: 'world-view', value: 'map' }] }] } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.route(GIBS, (r) => r.fulfill({ status: 200, contentType: 'image/png', body: PNG_RAIN, headers: { 'Access-Control-Allow-Origin': '*' } }));
  await page.goto(URL.full + '?view=map');
  await page.waitForFunction(() => (window.__liveState || {}).polls > 0);
  await page.waitForTimeout(1500);
  const webgl = await page.evaluate(() => !!(window.__globeFx && window.__globeFx.stats()));
  const tha = world.economies.findIndex((e) => e.iso === 'THA');
  await page.evaluate((i) => window.__igSelect('econ', i), tha);
  await done(page);
  await allFinal(page);
  expect(await page.locator('.ig-stat[data-v="gdp26"] [data-cu]').textContent()).toBe(pct(world.economies[tha].gdp_growth_2026));
  if (webgl) await arcsLabelled(page);
  const sw = await page.evaluate(() => [document.documentElement.scrollWidth, document.body.scrollWidth]);
  expect(Math.max(...sw)).toBeLessThanOrEqual(390);
  console.log('webkit 390: webgl', webgl, 'stats', JSON.stringify(await page.evaluate(() => window.__globeFx.stats())));
  await page.screenshot({ path: path.join(SHOTS, 'webkit-390-thai.png') });
  if (webgl) {
    await page.click('#tg-weather');
    await page.waitForFunction(() => { const w = window.__globeFx.weather(); return !w.busy && w.storms !== null && (w.rainAt || w.rainMsg); }, null, { timeout: 30000 });
    const w = await page.evaluate(() => window.__globeFx.weather());
    expect(w.rainMsg).toBe('');
    expect(w.gl.rainDots).toBeGreaterThan(100);
    await page.screenshot({ path: path.join(SHOTS, 'webkit-390-weather.png') });
  }
  expect(errors).toEqual([]);
  await ctx.close();
  await b.close();
});
