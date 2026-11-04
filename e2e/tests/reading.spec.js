// Reading view (โหมดอ่านง่าย, a book page): the view switch, its defaults and memory, the six chapters, typography,
// page colours and type size, keeping the reader's place, failure honesty and the deferred globe. Every context here starts from an empty storage state, because
// playwright.config.js stores the map view for the older specs.
const { test, expect, webkit } = require('@playwright/test');
const fs = require('fs');
const path = require('path');
const { URL, SHOTS, writeData, removeData, resetData, seed, collectErrors, noHScroll, repoll } = require('./helpers');

const world = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'world-data.json'), 'utf8'));
const FRESH = { storageState: { cookies: [], origins: [] } };
const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString();
const MIN = 60000, HOUR = 3600000;
const SECTIONS = ['r-latest', 'r-prices', 'r-conflicts', 'r-disasters', 'r-economy', 'r-gold'];
const THREE_RE = /three\.min\.js/;

async function open(browser, w, h, extra = {}) {
  const mobile = w < 500;
  const ctx = await browser.newContext({ ...FRESH, viewport: { width: w, height: h }, colorScheme: 'dark', isMobile: mobile, hasTouch: mobile, ...extra });
  const page = await ctx.newPage();
  return { ctx, page };
}
async function ready(page) { await expect.poll(() => page.evaluate(() => (window.__liveState || {}).polls || 0)).toBeGreaterThan(0); }
const viewOf = (page) => page.evaluate(() => document.documentElement.getAttribute('data-view'));
const stored = (page) => page.evaluate(() => localStorage.getItem('world-view'));
async function expectRead(page) {
  expect(await viewOf(page)).toBe('read');
  await expect(page.locator('#reader')).toBeVisible();
  await expect(page.locator('#stage')).toBeHidden();
  await expect(page.locator('#vw-read')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#vw-map')).toHaveAttribute('aria-pressed', 'false');
}
async function expectMap(page) {
  expect(await viewOf(page)).toBe('map');
  await expect(page.locator('#stage')).toBeVisible();
  await expect(page.locator('#reader')).toBeHidden();
  await expect(page.locator('#vw-map')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#vw-read')).toHaveAttribute('aria-pressed', 'false');
}
// a stored page colour and type size, as if the reader had picked them earlier
async function openAs(browser, w, h, theme, size, extra = {}) {
  const o = await open(browser, w, h, extra);
  await o.page.addInitScript(([t, z]) => { try { if (t) localStorage.setItem('world-read-theme', t); if (z) localStorage.setItem('world-read-size', z); } catch (e) { /* blocked */ } }, [theme, size ? String(size) : null]);
  return o;
}
const openAll = (page) => page.evaluate(() => document.querySelectorAll('#reader details').forEach((d) => { d.open = true; }));

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

    await page.click('#vw-read');
    await expectRead(page);
    expect(await stored(page)).toBe('read');
    expect(page.url()).toContain('view=read');
    await expect(page.locator('#r-gold h2')).toBeVisible();

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

  test('a phone that chose the map stays on the map, and the button at the end of the page goes there too', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
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

  test('blocked localStorage does not break anything', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.addInitScript(() => {
      Storage.prototype.getItem = function () { throw new Error('blocked'); };
      Storage.prototype.setItem = function () { throw new Error('blocked'); };
    });
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
    await page.click('#vw-map');
    await expectMap(page);
    await page.click('#vw-read');
    await expectRead(page);
    expect(errors).toEqual([]);
    await ctx.close();
  });
});

test.describe('content', () => {
  for (const [name, w, h] of [['phone', 390, 844], ['desktop', 1440, 900]]) {
    test(`all six sections, in order, from the data, no console or page errors (${name})`, async ({ browser }) => {
      const { ctx, page } = await open(browser, w, h);
      const errors = collectErrors(page);
      await page.goto(URL.full + '?view=read'); await ready(page);

      const ids = await page.locator('#reader > section').evaluateAll((els) => els.map((e) => e.id));
      expect(ids).toEqual(SECTIONS);
      for (const id of SECTIONS) {
        await expect(page.locator(`#${id} h2`)).toBeVisible();
        expect((await page.locator(`#${id}`).innerText()).trim().length, id).toBeGreaterThan(40);
      }

      // 1 latest: analysis text and top headlines with their source links
      await expect(page.locator('#r-latest')).toContainText(world.analysis_th.headline);
      const news = seed('headlines').items;
      await expect(page.locator('#r-news > li')).toHaveCount(Math.min(5, news.length));
      await expect(page.locator('#r-news > li').first()).toContainText(news[0].title_th);
      await expect(page.locator('#r-news > li a').first()).toHaveAttribute('href', news[0].source);

      // 2 prices: one plain row per market item, with value, change and its own time
      const market = seed('market');
      await expect(page.locator('#r-price-list > tbody')).toHaveCount(market.items.length);
      const first = page.locator(`#r-price-list > tbody[data-key="${market.items[0].key}"]`);
      await expect(first).toContainText(market.items[0].label_th);
      await expect(first.locator('a')).toHaveAttribute('href', market.items[0].source);
      await expect(page.locator('#r-prices .rd-fresh')).toContainText(bkk(market.updated_at));

      // 3 conflicts: most severe first, severity in words, summary collapsed, sources kept
      const conf = world.conflicts.slice().sort((a, b) => b.intensity - a.intensity);
      const rows = page.locator('#r-conflict-list > li');
      const high = conf.filter((c) => c.intensity >= 4);
      await expect(rows).toHaveCount(high.length);
      const levels = await page.locator('#r-conflicts li.rd-conf').evaluateAll((els) => els.map((e) => +e.getAttribute('data-intensity')));
      expect(levels).toHaveLength(conf.length);
      expect(levels).toEqual(levels.slice().sort((a, b) => b - a));
      const more = page.locator('details[data-rd="conf-rest"]');
      await expect(more.locator('> summary')).toContainText(`อ่านอีก ${conf.length - high.length} เรื่อง`);
      await expect(page.locator('#r-conflict-more')).toBeHidden();
      await more.locator('> summary').click();
      await expect(page.locator('#r-conflict-more')).toBeVisible();
      await expect(page.locator('#r-conflict-more > li')).toHaveCount(conf.length - high.length);
      await expect(page.locator('#r-conflict-more > li').first()).toContainText(conf[high.length].name_th);
      await more.locator('> summary').click();
      await expect(rows.first().locator('h3')).toHaveText(conf[0].name_th);
      await expect(rows.first().locator('.rd-level')).toContainText('รุนแรงที่สุด');
      await expect(rows.first()).toContainText(conf[0].status_th);
      for (const [lvl, word] of [[5, 'รุนแรงที่สุด'], [4, 'รุนแรงมาก'], [3, 'รุนแรงปานกลาง'], [2, 'รุนแรงน้อย'], [1, 'รุนแรงน้อยมาก']]) {
        const r = page.locator(`#r-conflicts li[data-intensity="${lvl}"]`).first();
        if (await r.count()) await expect(r.locator('.rd-level b')).toHaveText(word);
      }
      expect(await page.locator('#r-conflicts details[open]').count(), 'details are collapsed by default').toBe(0);
      await expect(rows.first().locator('.rd-more-b')).toBeHidden();
      await rows.first().locator('summary').click();
      await expect(rows.first().locator('.rd-more-b')).toBeVisible();
      await expect(rows.first()).toContainText(conf[0].summary_th);
      await expect(rows.first().locator('.rd-srcs a')).toHaveCount(conf[0].sources.length);

      // 4 disasters: alert level in words
      const dz = seed('disasters').items;
      if (dz.length) {
        await expect(page.locator('#r-dz-list > li')).toHaveCount(dz.length);
        await expect(page.locator('#r-dz-list > li').first().locator('.rd-level b')).toContainText('เตือนระดับ');
      }

      // 5 economies: one table row per record, the notes and their sources behind one line. Chokepoints are on the page.
      expect(await page.locator('#r-economy details[open]').count()).toBe(0);
      await expect(page.locator('#r-econ-list tbody tr')).toHaveCount(world.economies.length);
      await expect(page.locator('#r-econ-list tbody tr').first()).toContainText(world.economies[0].name_th);
      await expect(page.locator('#r-econ-notes')).toBeHidden();
      await page.locator('#r-economy details[data-rd="econ-notes"] > summary').click();
      await expect(page.locator('#r-econ-notes > li')).toHaveCount(world.economies.length);
      await expect(page.locator('#r-econ-notes > li').first()).toContainText(world.economies[0].note_th);
      await expect(page.locator('#r-choke-list > li')).toHaveCount(world.chokepoints.length);
      await expect(page.locator('#r-choke-list')).toBeVisible();

      // 6 gold: Thai bar and world price
      await expect(page.locator('#r-gold-th')).toContainText('ทองคำแท่งไทย');
      await expect(page.locator('#r-gold-spot')).toContainText('ทองคำโลก');
      await expect(page.locator('#r-gold-spot')).toContainText('$');

      expect(errors).toEqual([]);
      await ctx.close();
    });
  }

  test('prices read as a small table at 390px, digits lined up; a time shows only where it adds something', async ({ browser }) => {
    writeFresh();
    const dayAgo = iso(26 * HOUR);
    const M = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];
    const d = new Date(Date.parse(dayAgo) + 7 * HOUR), closeDay = `${d.getUTCDate()} ${M[d.getUTCMonth()]}`;
    const clock = `${('0' + d.getUTCHours()).slice(-2)}:${('0' + d.getUTCMinutes()).slice(-2)} น.`;
    const mk = (key, label_th, value, unit, change_th, as_of, source) => ({ key, label_th, value, unit, change_th, trend: 'up', as_of, source });
    writeData('market', { updated_at: iso(5 * MIN), note_th: 'ทดสอบ', items: [
      mk('brent', 'น้ำมัน Brent', '101.53', '$/บาร์เรล', '−2.00% (−2.07) จากปิดก่อนหน้า', iso(10 * MIN), 'https://www.cnbc.com/quotes/@LCO.1'),
      mk('gold_th', 'ทองคำแท่ง 96.5% ขายออก (สมาคมค้าทองคำ)', '64400', 'บาท', `ประกาศครั้งที่ 46 เวลา ${clock} +50 บาท · +1,900 จากวันก่อน`, dayAgo, 'https://www.goldtraders.or.th/'),
      mk('spx', 'S&P 500', '7568.92', 'จุด', `ปิด ${closeDay} +0.36% (+27.52)`, dayAgo, 'https://www.cboe.com/x'),
      mk('usdthb', 'ดอลลาร์/บาท', '33.610', 'บาท/$', '−0.44% (−0.150) จากปิดก่อนหน้า', iso(15 * MIN), 'https://finance.yahoo.com/quote/THB=X'),
      mk('stuck', 'รายการค้าง', '12.5', 'จุด', '+1.0% จากปิดก่อนหน้า', iso(8 * HOUR), 'https://www.cnbc.com/y'),
    ] });
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.mutable + '?view=read'); await ready(page);
    const row = (k) => page.locator(`#r-price-list > tbody[data-key="${k}"]`);
    await expect(page.locator('#r-price-list')).toHaveJSProperty('tagName', 'TABLE');
    const cols = await page.locator('#r-price-list > tbody').evaluateAll((els) => els.map((e) => {
      const v = e.querySelector('.val').getBoundingClientRect(), n = e.querySelector('.nm');
      return [e.getAttribute('data-key'), v.right, n.tagName, n.getAttribute('scope'), getComputedStyle(e.querySelector('.val')).fontVariantNumeric];
    }));
    for (const [k, right, tag, scope, nums] of cols) {
      expect(Math.abs(right - cols[0][1]), k + ' numbers end on the same line').toBeLessThan(0.6);
      expect([tag, scope], k + ' a real row header').toEqual(['TH', 'row']);
      expect(nums, k).toContain('tabular-nums');
    }
    // Thai gold: short name, the announcement time kept with its date because it is not from today, no second time beside it
    await expect(row('gold_th').locator('.nm')).toHaveText('ทองคำแท่ง 96.5% ขายออก');
    await expect(row('gold_th').locator('.chg')).toContainText(`${closeDay} ${clock} · +1,900 จากวันก่อน`);
    await expect(row('gold_th').locator('a')).toHaveText('goldtraders');
    await expect(row('gold_th').locator('.val')).toContainText('64,400');
    // a closing date in the change text is enough; a stale item with no date of its own shows its time; fresh ones show none
    await expect(row('spx').locator('.line2 td > span')).toHaveCount(1);
    await expect(row('stuck').locator('.line2 td > span').nth(1)).toContainText('ณ ');
    await expect(row('brent').locator('.line2 td > span')).toHaveCount(1);
    await expect(row('usdthb').locator('a')).toHaveText('yahoo');
    await ctx.close();
  });

  test('gold shows the same value and change under prices and under gold, whatever the history says', async ({ browser }) => {
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
    const inPrices = page.locator('#r-price-list > tbody[data-key="gold"]'), inGold = page.locator('#r-gold-spot');
    await expect(inPrices.locator('.chg')).toContainText('+2.86% (+112.45) จากปิดก่อนหน้า');
    await expect(inGold.locator('.chg')).toContainText('+2.86% (+112.45) จากปิดก่อนหน้า');
    expect(await inGold.locator('.val').innerText()).toBe(await inPrices.locator('.val').innerText());
    expect(await inGold.locator('.u').innerText()).toBe(await inPrices.locator('.u').innerText());
    await expect(page.locator('#r-gold-th .val').first()).toContainText('64,400');
    await expect(page.locator('#r-price-list > tbody[data-key="gold_th"] .chg')).toContainText('+1,900 จากวันก่อน');
    await expect(page.locator('#r-gold-th')).toContainText('+1,900 จากวันก่อน');
    await expect(page.locator('#r-gold-th')).toContainText('เวลา 16:11 น.');
    await page.click('#vw-map');
    await page.click('.tab[data-tab="gold"]');
    await expect(page.locator('#gold-tile-main .delta')).toContainText('+3.1%');   // map view untouched
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('disasters are called the latest, with each event\'s date or range from the data, and none is filtered out', async ({ browser }) => {
    writeFresh();
    const ended = '2026-10-01T05:00:00Z';
    const doc = freshDisasters();
    doc.items = [
      { ...doc.items[0], id: 'range', title_th: 'พายุที่จบแล้ว', type: 'cyclone', alert_level: 'red', start: '2026-09-20T00:00:00Z', end: ended },
      { ...doc.items[0], id: 'one', title_th: 'แผ่นดินไหวเก่า', type: 'earthquake', alert_level: 'orange', start: '2026-09-22T14:33:40Z', end: '2026-09-22T14:33:40Z' },
    ];
    writeData('disasters', doc);
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.mutable + '?view=read'); await ready(page);
    await expect(page.locator('#r-disasters h2')).toHaveText('ภัยพิบัติล่าสุด');
    await expect(page.locator('#r-dz-list > li')).toHaveCount(2);
    await expect(page.locator('#r-dz-list > li[data-id="range"] .rd-dz-date')).toHaveText('20 ก.ย. 2569 – 1 ต.ค. 2569');
    await expect(page.locator('#r-dz-list > li[data-id="one"] .rd-dz-date')).toContainText('22 ก.ย. 2569 (');
    await expect(page.locator('#r-dz-list > li[data-id="one"] .rd-dz-date')).toContainText('วันที่แล้ว');
    await page.click('#vw-map');
    await page.click('.tab[data-tab="disasters"]');
    await expect(page.locator('#dz-head .sec-title')).toHaveText('ภัยพิบัติล่าสุด');
    const html = await (await page.request.get(URL.mutable)).text();
    expect(html).not.toContain('ภัยพิบัติขณะนี้');
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('open sections stay open when new data arrives, and dates follow the data', async ({ browser }) => {
    writeFresh();
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.mutable + '?view=read'); await ready(page);
    const m = freshMarket();
    await expect(page.locator('#r-prices .rd-fresh')).toContainText(bkk(m.updated_at));
    await expect(page.locator('#r-disasters .rd-fresh')).toContainText(bkk(freshDisasters().updated));
    await expect(page.locator('#r-latest .rd-fresh').nth(1)).toContainText(bkk(freshHeadlines().updated_at));
    await expect(page.locator('#r-news > li').first()).toContainText('ข่าวทดสอบหนึ่ง');

    const card = page.locator('#r-conflict-list > li[data-intensity="5"]').filter({ hasText: 'ยูเครน' });
    await card.locator('summary').click();
    await expect(card).toContainText('ข่าวทดสอบหนึ่งของยูเครน');

    const m2 = freshMarket(); m2.updated_at = iso(5 * HOUR); m2.items[0].value = '120.50'; m2.items[0].as_of = iso(8 * HOUR);
    writeData('market', m2);
    await repoll(page);
    await expect(page.locator('#r-prices .rd-fresh')).toContainText(bkk(m2.updated_at));
    await expect(page.locator('#r-price-list > tbody[data-key="brent"]')).toContainText('120.50');
    await expect(card.locator('.rd-more-b')).toBeVisible();
    // a value kept after a failed fetch says so in the row itself
    await expect(page.locator('#r-price-list > tbody[data-key="gold_th"] .chg')).toContainText('ค่าเดิม');
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('no stale update-cadence wording in the page source', () => {
    for (const f of ['tools/template.html', 'tools/gold_module.js']) {
      const src = fs.readFileSync(path.join(__dirname, '..', '..', f), 'utf8');
      expect(src.match(/ทุก 4 ชม|every 4 h/g), f).toBeNull();
    }
  });

  test('the reading-view code has no frozen dates', () => {
    const src = fs.readFileSync(path.join(__dirname, '..', '..', 'tools', 'template.html'), 'utf8');
    const a = src.indexOf('/* ================= reading view'), b = src.indexOf('/* ================= view switch');
    expect(a).toBeGreaterThan(0); expect(b).toBeGreaterThan(a);
    const code = src.slice(a, b).split('\n').filter((l) => !/gdp_growth_/.test(l)).join('\n');   // the field names themselves carry their year
    expect(code.match(/(ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.)/g)).toBeNull();
    expect(code.match(/\b(25[5-9]\d|20[2-9]\d)\b/g)).toBeNull();
  });
});

test.describe('layout and reading comfort', () => {
  // compared with the fixed width: with isMobile, innerWidth grows along with content that is too wide
  async function fitsWidth(page, w, label) {
    const sw = await page.evaluate(() => [document.documentElement.scrollWidth, document.body.scrollWidth]);
    expect(Math.max(...sw), `${w}px ${label}`).toBeLessThanOrEqual(w);
    const wide = await page.evaluate((W) => Array.from(document.querySelectorAll('.topbar *, #reader *')).filter((e) => {
      const r = e.getBoundingClientRect();
      return e.checkVisibility() && r.width > 0 && (r.right > W + 0.5 || r.left < -0.5);   // a shut <details> keeps stale boxes
    }).map((e) => e.tagName + '.' + e.className).slice(0, 8), w);
    expect(wide, `${w}px ${label}`).toEqual([]);
    expect(await page.evaluate(() => innerWidth), `${w}px ${label} layout not widened`).toBe(w);
  }
  for (const w of [360, 390]) {
    for (const size of [1, 3, 4, 6]) {
      test(`no horizontal overflow at ${w}px, type size ${size}, closed, with everything open and with the controls open`, async ({ browser }) => {
        const { ctx, page } = await openAs(browser, w, 800, null, size);
        await page.goto(URL.full + '?view=read'); await ready(page);
        await fitsWidth(page, w, 'closed');
        await openAll(page);
        await fitsWidth(page, w, 'open');
        await page.evaluate(() => { document.getElementById('rd-aa').open = true; });
        await fitsWidth(page, w, 'controls');
        await ctx.close();
      });
    }
  }

  test('map view header still fits at 360px with the switch in it', async ({ browser }) => {
    const { ctx, page } = await open(browser, 360, 740);
    await page.goto(URL.full + '?view=map'); await ready(page);
    expect(await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth])).toEqual([360, 360]);
    const box = await page.locator('.view-switch').boundingBox();
    expect(box.x + box.width).toBeLessThanOrEqual(360);
    await ctx.close();
  });

  test('phone typography and tap targets', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read'); await ready(page);
    await openAll(page);
    const sizes = await page.evaluate(() => ['#r-news .rd-title', '#r-conflict-list > li > p:not(.rd-level)', '.rd-callout p', '#r-conflict-list .rd-more-b > p', '.rd-prose li'].map((sel) => {
      const cs = getComputedStyle(document.querySelector(sel));
      return { sel, size: parseFloat(cs.fontSize), lh: parseFloat(cs.lineHeight) / parseFloat(cs.fontSize) };
    }));
    for (const s of sizes) {
      expect(s.size, s.sel).toBeGreaterThanOrEqual(18);
      expect(s.lh, s.sel).toBeGreaterThanOrEqual(1.7);
    }
    await ctx.close();
  });

  for (const size of [1, 3, 6]) {
    test(`tap targets stay 44px at type size ${size}`, async ({ browser }) => {
      const { ctx, page } = await openAs(browser, 390, 844, null, size);
      await page.goto(URL.full + '?view=read'); await ready(page);
      await openAll(page);
      await page.evaluate(() => { document.getElementById('rd-aa').open = true; });
      const small = await page.evaluate(() => Array.from(document.querySelectorAll('.view-switch button, #reader a, #reader summary, #reader button, #rd-aa summary, #rd-aa button')).filter((e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height < 44;
      }).map((e) => e.tagName + ':' + e.textContent.slice(0, 30) + ':' + Math.round(e.getBoundingClientRect().height)).slice(0, 10));
      expect(small, 'interactive elements under 44px tall').toEqual([]);
      await ctx.close();
    });
  }

  test('a book page, not a dashboard: left-aligned text, no boxes, bars or colour fills on the items', async ({ browser }) => {
    const { ctx, page } = await openAs(browser, 390, 844, 'paper');
    await page.goto(URL.full + '?view=read'); await ready(page);
    await openAll(page);
    const found = await page.evaluate(() => {
      const paper = getComputedStyle(document.documentElement).backgroundColor, bad = [];
      document.querySelectorAll('#reader *').forEach((e) => {
        const cs = getComputedStyle(e);
        if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== paper) bad.push('fill ' + e.tagName + '.' + e.className);
        if (parseFloat(cs.borderLeftWidth) > 0) bad.push('side bar ' + e.tagName + '.' + e.className);
        if (parseFloat(cs.borderRadius) > 2) bad.push('rounded ' + e.tagName + '.' + e.className);
        if (cs.boxShadow !== 'none') bad.push('shadow ' + e.tagName + '.' + e.className);
      });
      return { bad: bad.slice(0, 8), align: getComputedStyle(document.querySelector('.rd-prose li')).textAlign, status: getComputedStyle(document.querySelector('#r-conflict-list > li > p:not(.rd-level)')).textAlign };
    });
    expect(found.bad).toEqual([]);
    expect(found.align, 'justified Thai breaks up vowel marks in a narrow column').not.toBe('justify');
    expect(found.status).not.toBe('justify');
    await ctx.close();
  });

  test('digits share one width in the figures', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read'); await ready(page);
    const w = await page.evaluate(async () => {
      await document.fonts.ready;
      const v = document.querySelector('#r-price-list .val'), probe = v.cloneNode(false);
      probe.style.cssText = 'position:absolute;visibility:hidden;white-space:nowrap';
      v.parentNode.appendChild(probe);
      const out = ['111111', '888888', '000000'].map((t) => { probe.textContent = t; return probe.getBoundingClientRect().width; });
      probe.remove();
      return out;
    });
    expect(Math.abs(w[0] - w[1])).toBeLessThan(0.6);
    expect(Math.abs(w[0] - w[2])).toBeLessThan(0.6);
    await ctx.close();
  });

  // the tallest Thai stacks (tone mark over an upper vowel, and marks below) must fit the line they sit on, so two lines never touch,
  // and nothing around text may cut them off
  for (const size of [1, 3, 6]) {
    test(`Thai stacked marks fit their line and nothing clips them, type size ${size}`, async ({ browser }) => {
      const { ctx, page } = await openAs(browser, 390, 844, null, size);
      await page.goto(URL.full + '?view=read'); await ready(page);
      await openAll(page);
      const res = await page.evaluate(async () => {
        await document.fonts.ready;
        const cx = document.createElement('canvas').getContext('2d');
        const STACK = 'ปุ๋ย ฟื้นฟู กิ๊ฟ ญี่ปุ่น ฎีกา ฏุ ปั้น ที่นี่ ผู้นำ น้ำ';
        const sels = ['.topbar h1', '.topbar .sub', '.view-switch button', '.rd-toc a', '.rd-ch-no', '.rd-sec .rd-ch h2', '.rd-fresh', '.rd-sec h3', '.rd-lead', '.rd-title', '.rd-meta', '.rd-prose li', '.rd-level', '#r-conflict-list > li > p:not(.rd-level)', 'details.rd-more > summary', '.rd-srcs a', '.rd-kv dt', '.rd-kv dd', '.rd-choke h4', '.rd-table .nm', '.rd-table .val', '.rd-table .u', '.rd-table .line2 td', '.rd-econ thead th', '.rd-econ tbody th', '.rd-econ tbody th small', '.rd-econ tbody td', '.rd-note', '.rd-go'];
        const tight = [], clipped = [];
        for (const s of sels) {
          const e = document.querySelector(s); if (!e) { tight.push('missing ' + s); continue; }
          const cs = getComputedStyle(e);
          cx.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
          const m = cx.measureText(STACK), ink = m.actualBoundingBoxAscent + m.actualBoundingBoxDescent, lh = parseFloat(cs.lineHeight);
          if (!(ink <= lh)) tight.push(`${s}: ink ${ink.toFixed(1)} > line ${lh}`);
        }
        document.querySelectorAll('.topbar *, #reader *').forEach((e) => {
          const cs = getComputedStyle(e);
          if (e.getClientRects().length && e.textContent.trim() && (cs.overflowY === 'hidden' || cs.overflowY === 'clip' || cs.overflowX === 'hidden')) clipped.push(e.tagName + '.' + e.className);
        });
        return { tight, clipped: clipped.slice(0, 8), serif: getComputedStyle(document.body).fontFamily };
      });
      expect(res.tight).toEqual([]);
      expect(res.clipped).toEqual([]);
      await ctx.close();
    });
  }

  test('desktop line length is about 65 characters', async ({ browser }) => {
    const { ctx, page } = await open(browser, 1440, 900);
    await page.goto(URL.full + '?view=read'); await ready(page);
    const longest = await page.evaluate(() => {
      const el = document.querySelector('.rd-callout p'), node = el.firstChild, range = document.createRange();
      const lines = new Map();
      for (let i = 0; i < node.length; i++) {
        range.setStart(node, i); range.setEnd(node, i + 1);
        const r = range.getClientRects()[0]; if (!r) continue;
        const y = Math.round(r.top + r.height / 2);
        lines.set(y, (lines.get(y) || 0) + 1);
      }
      return Math.max(...lines.values());
    });
    expect(longest).toBeGreaterThanOrEqual(55);
    expect(longest).toBeLessThanOrEqual(82);   // counts Thai vowel and tone marks, which take no width of their own
    const body = await page.locator('#r-conflict-list > li > p:not(.rd-level)').first().evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
    expect(body).toBeGreaterThanOrEqual(17);
    await ctx.close();
  });

  for (const theme of ['paper', 'sepia', 'night']) {
    test(`text contrast is at least 4.5:1, and body text well above it (${theme})`, async ({ browser }) => {
      writeFresh(); writeData('market', { ...freshMarket(), updated_at: iso(20 * HOUR) });   // brings a warning on screen
      const { ctx, page } = await openAs(browser, 390, 844, theme);
      await page.goto(URL.mutable + '?view=read'); await ready(page);
      await openAll(page);
      await page.evaluate(() => { document.getElementById('rd-aa').open = true; });
      const res = await page.evaluate(() => {
        const cv = document.createElement('canvas').getContext('2d', { willReadFrequently: true });
        const rgba = (c) => { cv.clearRect(0, 0, 1, 1); cv.fillStyle = c; cv.fillRect(0, 0, 1, 1); const d = cv.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255]; };
        const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
        const bgOf = (e) => { for (; e; e = e.parentElement) { const c = rgba(getComputedStyle(e).backgroundColor); if (c[3] > 0.99) return c; } return [255, 255, 255, 1]; };
        const ratio = (e) => { const a = lum(rgba(getComputedStyle(e).color)), b = lum(bgOf(e)); return +((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toFixed(2); };
        const sels = ['.topbar h1', '.topbar .sub', '.view-switch button[aria-pressed="true"]', '.view-switch button[aria-pressed="false"]', '#rd-aa summary', '.rd-aa-panel p', '.sw-paper', '.sw-sepia', '.sw-night', '#rd-size-up', '#rd-size-now', '.rd-toc a', '.rd-ch-no', '.rd-sec .rd-ch h2', '.rd-fresh', '.rd-lead', '.rd-title', '.rd-meta', '.rd-meta a', '.rd-callout p', '.rd-prose li', '.rd-note', '.rd-note.warn', '.rd-note.warn b', '.rd-banner', '.rd-table .nm', '.rd-table .val', '.rd-table .u', '.rd-table .line2 td', '.rd-table .line2 a', '.rd-table .chg', '.rd-econ thead th', '.rd-econ tbody th', '.rd-econ tbody th small', '.rd-econ tbody td', '.rd-level', '.rd-level b', 'details.rd-more > summary', 'details.rd-group > summary', '.rd-kv dt', '.rd-srcs a', '.rd-srcs-k', '.rd-go', '.rd-foot a'];
        const all = sels.map((s) => { const e = document.querySelector(s); return e ? { s, ratio: ratio(e) } : { s, missing: true }; });
        const body = ['.rd-prose li', '.rd-title', '.rd-table .val', '#r-conflict-list > li > p:not(.rd-level)'].map((s) => ({ s, ratio: ratio(document.querySelector(s)) }));
        const page = getComputedStyle(document.documentElement).backgroundColor, ink = getComputedStyle(document.body).color;
        return { all, body, page, ink };
      });
      expect(res.all.filter((r) => r.missing), 'every checked element is on the page').toEqual([]);
      expect(res.all.filter((r) => r.ratio < 4.5)).toEqual([]);
      expect(res.body.filter((r) => r.ratio < 7), 'body text comfortably above the minimum').toEqual([]);
      expect(res.body.filter((r) => r.ratio > 16), 'not pure black on pure white, nor its reverse').toEqual([]);
      for (const c of [res.page, res.ink]) expect(['rgb(255, 255, 255)', 'rgb(0, 0, 0)']).not.toContain(c);
      await ctx.close();
    });
  }
});

test.describe('page colour and type size', () => {
  const themeOf = (page) => page.evaluate(() => document.documentElement.getAttribute('data-rd-theme'));
  const sizeOf = (page) => page.evaluate(() => [document.documentElement.getAttribute('data-rd-size'), parseFloat(getComputedStyle(document.querySelector('.rd-prose li')).fontSize)]);

  test('the first visit follows the phone: light takes paper, dark takes the warm night page, and a later change follows until the reader chooses', async ({ browser }) => {
    const light = await open(browser, 390, 844, { colorScheme: 'light' });
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

  test('the controls are tucked away, and a chosen colour and size come back on the next visit before anything is painted', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844, { colorScheme: 'light' });
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read'); await ready(page);
    await expect(page.locator('.rd-aa-panel')).toBeHidden();
    await page.click('#rd-aa summary');
    await expect(page.locator('.rd-aa-panel')).toBeVisible();
    await expect(page.locator('[data-rd-theme-set="paper"]')).toHaveAttribute('aria-pressed', 'true');
    await page.click('[data-rd-theme-set="night"]');
    await expect(page.locator('[data-rd-theme-set="night"]')).toHaveAttribute('aria-pressed', 'true');
    expect(await page.evaluate(() => getComputedStyle(document.body).backgroundColor)).toBe('rgb(29, 26, 23)');
    expect(await page.locator('meta[name="theme-color"]').first().getAttribute('content'), 'the browser bar takes the page colour').toBe('#1d1a17');
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
    const { ctx, page } = await openAs(browser, 390, 844, 'pink', 99, { colorScheme: 'light' });
    await page.goto(URL.full + '?view=read'); await ready(page);
    expect(await themeOf(page)).toBe('paper');
    expect((await sizeOf(page))[0]).toBe('3');
    await ctx.close();
  });

  test('blocked storage: the controls still work for this page and nothing breaks', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844, { colorScheme: 'dark' });
    const errors = collectErrors(page);
    await page.addInitScript(() => {
      Storage.prototype.getItem = function () { throw new Error('blocked'); };
      Storage.prototype.setItem = function () { throw new Error('blocked'); };
      Storage.prototype.removeItem = function () { throw new Error('blocked'); };
    });
    await page.goto(URL.full + '?view=read'); await ready(page);
    expect(await themeOf(page)).toBe('night');
    await page.click('#rd-aa summary');
    await page.click('[data-rd-theme-set="sepia"]');
    expect(await themeOf(page)).toBe('sepia');
    await page.click('#rd-size-down');
    expect((await sizeOf(page))[0]).toBe('2');
    await page.evaluate(() => window.scrollTo(0, 3000));
    await page.waitForTimeout(600);   // the place would be saved here
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('the colour and size stay out of the map view', async ({ browser }) => {
    const plain = await open(browser, 1440, 900, { colorScheme: 'light' });
    await plain.page.goto(URL.full + '?view=map');
    const want = await plain.page.evaluate(() => [getComputedStyle(document.body).backgroundColor, getComputedStyle(document.body).fontSize, getComputedStyle(document.body).fontFamily, document.querySelector('meta[name="theme-color"][media*="light"]').content]);
    await plain.ctx.close();
    const { ctx, page } = await openAs(browser, 1440, 900, 'night', 6, { colorScheme: 'light' });
    await page.goto(URL.full + '?view=read'); await ready(page);
    expect(await page.locator('meta[name="theme-color"][media*="light"]').getAttribute('content')).toBe('#1d1a17');
    await page.click('#vw-map');
    await expectMap(page);
    await expect(page.locator('#rd-aa')).toBeHidden();
    await expect(page.locator('#rd-progress')).toBeHidden();
    expect(await page.evaluate(() => [getComputedStyle(document.body).backgroundColor, getComputedStyle(document.body).fontSize, getComputedStyle(document.body).fontFamily, document.querySelector('meta[name="theme-color"][media*="light"]').content])).toEqual(want);
    await ctx.close();
  });

  test('each view asks only for its own fonts', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const asked = [];
    page.on('request', (r) => { if (/fonts\.gstatic\.com/.test(r.url())) asked.push(r.url()); });
    await page.goto(URL.full + '?view=read'); await ready(page);
    await page.waitForTimeout(500);
    expect(asked.filter((u) => /ibmplex|notosansthai/i.test(u)), 'no sans-serif faces on a book page').toEqual([]);
    await ctx.close();
    const map = await open(browser, 1440, 900);
    const asked2 = [];
    map.page.on('request', (r) => { if (/fonts\.gstatic\.com/.test(r.url())) asked2.push(r.url()); });
    await map.page.goto(URL.full + '?view=map'); await ready(map.page);
    await map.page.waitForTimeout(500);
    expect(asked2.filter((u) => /notoserifthai/i.test(u)), 'the map view does not fetch the book face').toEqual([]);
    await map.ctx.close();
  });

  test('if the web font fails the page is still readable: a Thai system face, the same layout rules, no errors', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page, [/fonts\.g/, /ERR_FAILED/]);
    await page.route(/fonts\.(googleapis|gstatic)\.com/, (r) => r.abort());
    await page.goto(URL.full + '?view=read'); await ready(page);
    const r = await page.evaluate(() => ({ family: getComputedStyle(document.body).fontFamily, h: document.querySelector('.rd-prose li').getBoundingClientRect().height, loaded: Array.from(document.fonts).filter((f) => f.status === 'loaded').length }));
    expect(r.loaded, 'the web font really is blocked').toBe(0);
    expect(r.family).toContain('Thonburi');
    expect(r.h).toBeGreaterThan(50);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
    await page.screenshot({ path: path.join(SHOTS, 'reading-no-webfont-390.png') });
    expect(errors).toEqual([]);
    await ctx.close();
  });
});

test.describe('reading without interruptions', () => {
  const placeTop = (page, sel) => page.locator(sel).evaluate((e) => Math.round(e.getBoundingClientRect().top));

  test('nothing moves: no animation or transition on the page, and the progress line stays thin and out of the way', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844, { reducedMotion: 'reduce' });
    await page.goto(URL.full + '?view=read'); await ready(page);
    await openAll(page);
    const r = await page.evaluate(() => {
      const moving = [];
      document.querySelectorAll('.topbar, .topbar *, #reader, #reader *, #rd-progress').forEach((e) => {
        const cs = getComputedStyle(e);
        if (parseFloat(cs.transitionDuration) > 0 && cs.transitionProperty !== 'none') moving.push('transition ' + e.tagName + '.' + e.className);
        if (cs.animationName !== 'none') moving.push('animation ' + e.tagName + '.' + e.className);
      });
      const p = document.getElementById('rd-progress'), cs = getComputedStyle(p);
      return { moving: moving.slice(0, 5), running: document.getAnimations().length, smooth: getComputedStyle(document.documentElement).scrollBehavior, h: p.getBoundingClientRect().height, events: cs.pointerEvents, hidden: p.getAttribute('aria-hidden') };
    });
    expect(r.moving).toEqual([]);
    expect(r.running).toBe(0);
    expect(r.smooth).toBe('auto');
    expect([r.h, r.events, r.hidden]).toEqual([2, 'none', 'true']);
    const scale = () => page.locator('#rd-progress').evaluate((e) => new DOMMatrix(getComputedStyle(e).transform).a);
    expect(await scale()).toBe(0);
    await page.evaluate(() => window.scrollTo(0, (document.documentElement.scrollHeight - innerHeight) / 2));
    await expect.poll(scale).toBeGreaterThan(0.4);
    expect(await scale()).toBeLessThan(0.6);
    await ctx.close();
  });

  test('every source link in the data can be reached on the page', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.full + '?view=read'); await ready(page);
    await openAll(page);
    const hrefs = new Set(await page.locator('#reader a').evaluateAll((els) => els.map((e) => e.getAttribute('href'))));
    const want = [].concat(...world.conflicts.map((c) => c.sources || []), ...world.economies.map((c) => c.sources || []), ...world.chokepoints.map((c) => c.sources || []));
    want.push(...seed('headlines').items.map((i) => i.source).filter(Boolean), ...seed('market').items.map((i) => i.source).filter(Boolean), ...seed('disasters').items.map((i) => i.source_url).filter(Boolean));
    expect(want.filter((u) => !hrefs.has(u))).toEqual([]);
    await ctx.close();
  });

  test('new data arriving, or a change of type size, leaves the reader on the same item', async ({ browser }) => {
    writeFresh();
    const { ctx, page } = await open(browser, 390, 844);
    await page.goto(URL.mutable + '?view=read'); await ready(page);
    const card = page.locator('#r-conflict-list > li').nth(4);
    await card.evaluate((e) => { e.scrollIntoView(); window.scrollBy(0, -60); });
    await page.waitForTimeout(100);
    const y0 = await card.evaluate((e) => Math.round(e.getBoundingClientRect().top));
    const scroll0 = await page.evaluate(() => scrollY);

    // eight more news rows above it
    const hd = freshHeadlines();
    for (let i = 3; i < 10; i++) hd.items.push({ id: 'n' + i, conflict_id: 'economy', title_th: 'ข่าวเพิ่มเติมที่ทำให้หน้ายาวขึ้น ' + i, time: iso(3 * HOUR), source: 'https://www.reuters.com/x' + i, source_name: 'Reuters' });
    writeData('headlines', hd);
    await repoll(page);
    expect(Math.abs(await card.evaluate((e) => Math.round(e.getBoundingClientRect().top)) - y0), 'same place on screen').toBeLessThan(3);
    expect(await page.evaluate(() => scrollY), 'the page itself grew above').not.toBe(scroll0);

    await page.evaluate(() => document.getElementById('rd-size-up').click());
    expect(Math.abs(await card.evaluate((e) => Math.round(e.getBoundingClientRect().top)) - y0), 'same place after a size change').toBeLessThan(3);
    await ctx.close();
  });

  test('coming back to the tab returns to the same item with what was open still open; the top stays the top', async ({ browser }) => {
    const { ctx, page } = await open(browser, 390, 844);
    const errors = collectErrors(page);
    await page.goto(URL.full + '?view=read'); await ready(page);
    const card = page.locator('#r-conflict-list > li').nth(3);
    await card.locator('summary').click();
    await card.evaluate((e) => { e.scrollIntoView(); window.scrollBy(0, -80); });
    await page.waitForTimeout(700);   // saved after the scroll settles
    await page.reload(); await ready(page);
    await expect(card.locator('.rd-more-b')).toBeVisible();
    await expect.poll(() => card.evaluate((e) => Math.round(e.getBoundingClientRect().top))).toBeLessThan(160);
    expect(await card.evaluate((e) => Math.round(e.getBoundingClientRect().top))).toBeGreaterThan(0);

    // back at the top: the next load starts at the top
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(700);
    await page.reload(); await ready(page);
    expect(await page.evaluate(() => scrollY)).toBeLessThan(5);

    // a link to a chapter wins over a saved place
    await card.evaluate((e) => { e.scrollIntoView(); });
    await page.waitForTimeout(700);
    await page.goto(URL.full + '?view=read#r-economy'); await ready(page);
    await expect.poll(() => page.locator('#r-economy').evaluate((e) => Math.round(e.getBoundingClientRect().top))).toBeLessThan(40);
    expect(errors).toEqual([]);
    await ctx.close();
  });
});

test.describe('iPhone engine', () => {
  test('headless WebKit at 390px: page, controls, memory and width all hold', async () => {
    let browser;
    try { browser = await webkit.launch(); } catch (e) { test.skip(true, 'WebKit is not installed here: ' + String(e.message).slice(0, 80)); }
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true, colorScheme: 'light', storageState: { cookies: [], origins: [] } });
    const page = await ctx.newPage();
    const errors = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(URL.full); await ready(page);
    await expectRead(page);
    await expect(page.locator('#r-conflict-list > li').first()).toBeVisible();
    const fits = async (label) => { const sw = await page.evaluate(() => [document.documentElement.scrollWidth, document.body.scrollWidth]); expect(Math.max(...sw), label).toBeLessThanOrEqual(390); };
    await fits('closed');
    await openAll(page);
    await fits('open');
    await page.tap('#rd-aa summary');
    await expect(page.locator('.rd-aa-panel')).toBeVisible();
    await page.tap('[data-rd-theme-set="night"]');
    for (let i = 0; i < 3; i++) await page.tap('#rd-size-up');
    await fits('largest type');
    expect(await page.evaluate(() => [document.documentElement.getAttribute('data-rd-theme'), document.documentElement.getAttribute('data-rd-size'), localStorage.getItem('world-read-theme')])).toEqual(['night', '6', 'night']);
    expect(await page.evaluate(() => Array.from(document.querySelectorAll('#r-price-list .val')).map((e) => e.getBoundingClientRect().right).every((r, i, a) => Math.abs(r - a[0]) < 0.6))).toBe(true);
    await page.screenshot({ path: path.join(SHOTS, 'reading-webkit-night-large.png') });
    expect(errors).toEqual([]);
    await browser.close();
  });
});

test.describe('failure honesty', () => {
  test('no live data at all: says so at the top and in every live section, embedded values keep their own dates', async ({ browser }) => {
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
      await expect(page.locator('#r-prices .rd-note.warn')).toContainText('โหลดราคาสดไม่สำเร็จ');
      await expect(page.locator('#r-latest .rd-note.warn').last()).toContainText('โหลดข่าวล่าสุดไม่สำเร็จ');
      await expect(page.locator('#r-disasters .rd-note.warn')).toContainText('โหลดข้อมูลภัยพิบัติไม่สำเร็จ');
      await expect(page.locator('#r-gold .rd-note.warn')).toContainText('โหลดราคาสดไม่สำเร็จ');
      // fallback prices are the embedded ones, labelled and dated, not shown as current
      const rows = page.locator('#r-price-list > tbody');
      expect(await rows.count()).toBeGreaterThan(0);
      await expect(rows.first()).toContainText('ค่าล่าสุดที่ฝังในหน้าเว็บ ณ');
      await expect(page.locator('#r-prices [data-age]')).toHaveCount(0);
      // what does not depend on a feed is still there
      await expect(page.locator('#r-conflicts li.rd-conf')).toHaveCount(world.conflicts.length);
      await expect(page.locator('#r-gold-th')).toBeVisible();
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
    await page.goto(URL.mutable + '?view=read'); await ready(page);
    const warns = () => page.locator('#reader .rd-note.warn').evaluateAll((els) => els.map((e) => e.textContent).filter((t) => !/ไม่ได้ทบทวนมาแล้ว/.test(t)));   // the frozen e2e fixture is old on purpose
    expect(await warns()).toEqual([]);

    // headlines fail after a good load: last items stay, with a warning
    removeData('headlines');
    await repoll(page);
    await expect(page.locator('#r-latest .rd-note.warn').last()).toContainText('โหลดข่าวรอบล่าสุดไม่สำเร็จ');
    await expect(page.locator('#r-news > li').first()).toContainText('ข่าวทดสอบหนึ่ง');
    await expect(page.locator('#r-banner')).toContainText('ข่าว');

    // disasters fail too
    removeData('disasters');
    await repoll(page);
    await expect(page.locator('#r-disasters .rd-note.warn')).toContainText('โหลดข้อมูลภัยพิบัติรอบล่าสุดไม่สำเร็จ');
    await expect(page.locator('#r-dz-list > li')).toHaveCount(1);

    // everything back: warnings gone, banner hidden unless the fixture's age keeps it
    writeFresh();
    await repoll(page);
    expect(await warns()).toEqual([]);

    // stale prices
    writeData('market', { ...freshMarket(), updated_at: iso(7 * HOUR) });
    await repoll(page);
    await expect(page.locator('#r-prices .rd-note.warn')).toContainText('เก่ากว่า 6 ชม.');
    await expect(page.locator('#r-banner')).toContainText('ราคา');

    // stale news
    writeData('headlines', { ...freshHeadlines(), updated_at: iso(15 * HOUR) });
    await repoll(page);
    await expect(page.locator('#r-latest .rd-note.warn').last()).toContainText('เก่ากว่า 14 ชม.');

    // stale disasters
    writeData('disasters', { ...freshDisasters(), updated: iso(7 * HOUR) });
    await repoll(page);
    await expect(page.locator('#r-disasters .rd-note.warn')).toContainText('เก่ากว่า 6 ชม.');

    // disasters partly failed, in the feed's own words
    writeData('disasters', { ...freshDisasters(), ok: false, message_th: 'GDACS ล้มเหลวรอบนี้' });
    await repoll(page);
    await expect(page.locator('#r-disasters .rd-note.warn')).toContainText('GDACS ล้มเหลวรอบนี้');

    // a failed run, in the status file's own words
    writeData('status', { ...freshStatus(), ok: false, message_th: 'รอบล่าสุดล้มเหลว เกินวงเงิน' });
    await repoll(page);
    await expect(page.locator('#r-prices .rd-note.warn')).toContainText('รอบล่าสุดล้มเหลว เกินวงเงิน');
    await page.screenshot({ path: path.join(SHOTS, 'reading-stale-390.png'), fullPage: false });
    expect(errors).toEqual([]);
    await ctx.close();
  });

  test('stale gold says which price is stale', async ({ browser }) => {
    // a fixed clock long after the fixture's date: both quotes are newer than the embedded ones and still many trading hours old
    const now = Date.parse(JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'fixtures', 'gold.json'), 'utf8')).as_of) + 15 * 86400000;
    const quoteAt = new Date(now - 8 * 86400000).toISOString();
    const m = { updated_at: new Date(now - HOUR).toISOString(), items: [
      { key: 'gold', label_th: 'ทองคำ (spot)', value: '4000.00', unit: '$/ออนซ์', change_th: '+1.00% จากปิดก่อนหน้า', trend: 'up', as_of: quoteAt, source: 'https://www.swissquote.com/' },
      { key: 'gold_th', label_th: 'ทองคำแท่ง', value: '64000', unit: 'บาท', change_th: '+50 บาท', trend: 'up', as_of: quoteAt, source: 'https://www.goldtraders.or.th/' },
    ] };
    writeData('market', m);
    const { ctx, page } = await open(browser, 390, 844);
    await page.clock.setFixedTime(new Date(now));
    await page.goto(URL.mutable + '?view=read'); await ready(page);
    const note = page.locator('#r-gold .rd-note.warn');
    await expect(note).toContainText('ข้อมูลเก่า');
    await expect(note).toContainText('ทองคำแท่งไทย');
    await expect(note).toContainText('ทองคำโลก');
    await expect(page.locator('#r-gold-spot')).toContainText(bkk(quoteAt));
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
    await page.waitForTimeout(800);
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
    await expect(page.locator('#r-gold h2')).toBeVisible();
    await ctx.close();
  });
});

test('screenshots of the reading view', async ({ browser }) => {
  for (const [name, w, h] of [['phone', 390, 844], ['desktop', 1440, 900]]) {
    for (const scheme of ['paper', 'sepia', 'night']) {
      const { ctx, page } = await openAs(browser, w, h, scheme);
      await page.goto(URL.full + '?view=read'); await ready(page);
      await page.waitForTimeout(500);
      await page.screenshot({ path: path.join(SHOTS, `reading-${name}-${scheme}-top.png`) });
      // viewport shots: this page is taller than the software GL used by these tests can capture in one piece
      for (const id of ['r-prices', 'r-conflicts', 'r-gold']) {
        await page.locator('#' + id).evaluate((e) => e.scrollIntoView());
        await page.screenshot({ path: path.join(SHOTS, `reading-${name}-${scheme}-${id}.png`) });
      }
      await ctx.close();
    }
  }
});
