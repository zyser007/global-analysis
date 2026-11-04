// Live layer: data/{market,headlines,status}.json fetched relatively (no-store), re-polled on
// visibilitychange / every 10 min, feeding the same ticker / news / gold render functions.
const { test, expect } = require('@playwright/test');
const path = require('path');
const { URL, SHOTS, writeData, removeData, resetData, collectErrors, noHScroll, repoll } = require('./helpers');

const iso = (msAgo) => new Date(Date.now() - msAgo).toISOString();
const MIN = 60000, HOUR = 3600000;

function market1() {
  return { updated_at: iso(25*MIN), note_th: 'ราคาจากงานตั้งเวลา วันละ 6 รอบ', items: [
    {key:'brent',label_th:'น้ำมัน Brent',value:'116.4',unit:'$/บาร์เรล',change_th:'+1.2% วันนี้',trend:'up',as_of:iso(30*MIN),source:'https://www.eia.gov'},
    {key:'wti',label_th:'น้ำมัน WTI',value:'112.8',unit:'$/บาร์เรล',change_th:'+0.9% วันนี้',trend:'up',as_of:iso(30*MIN),source:'https://www.eia.gov'},
    {key:'gold',label_th:'ทองคำ',value:'3,842.50',unit:'$/ออนซ์',change_th:'−1.2% วันนี้',trend:'down',as_of:iso(30*MIN),source:'https://www.lbma.org.uk'},
    {key:'gold_th',label_th:'ทองคำแท่งไทย (ขายออก)',value:'61,900',unit:'บาท',change_th:'−350 บาท วันนี้',trend:'down',as_of:iso(20*MIN),source:'https://www.goldtraders.or.th'},
    {key:'dxy',label_th:'ดัชนีดอลลาร์ DXY',value:'104.2',unit:'จุด',change_th:'ทรงตัว',trend:'flat',source:'https://www.marketwatch.com'},
    {key:'spx',label_th:'S&P 500',value:'6,210',unit:'จุด',change_th:'−1.1% วันนี้',trend:'down',source:'https://www.reuters.com'},
    {key:'ndx',label_th:'Nasdaq 100',value:'20,480',unit:'จุด',change_th:'−1.6% วันนี้',trend:'down',source:'https://www.reuters.com'},
    {key:'btc',label_th:'Bitcoin',value:'88,900',unit:'$',change_th:'+2.3% วันนี้',trend:'up',source:'https://www.coindesk.com'},
    {key:'usdthb',label_th:'USD/THB',value:'35.82',unit:'บาท/$',change_th:'+0.2% วันนี้',trend:'up',source:'https://www.bot.or.th'},
    {key:'us10y',label_th:'ยีลด์สหรัฐ 10 ปี',value:'4.62',unit:'%',change_th:'+5bp',trend:'up',source:'https://www.treasury.gov'},
    {key:'vix',label_th:'VIX',value:'24.1',unit:'จุด',change_th:'+3.0 วันนี้',trend:'up',source:'https://www.cboe.com'}
  ]};
}
function head1() {
  return { updated_at: iso(20*MIN), items: [
    {id:'h1',conflict_id:'iran_us_israel_war',title_th:'อิหร่านยิงขีปนาวุธใส่เรือบรรทุกน้ำมันใกล้ฮอร์มุซ สหรัฐเตือนตอบโต้',time:iso(40*MIN),source:'https://www.reuters.com/world',source_name:'Reuters'},
    {id:'h2',conflict_id:'economy',title_th:'เฟดคงดอกเบี้ย ส่งสัญญาณขึ้นต่อหากน้ำมันไม่ลด',time:iso(2*HOUR),source:'https://www.cnbc.com',source_name:'CNBC'},
    {id:'h3',conflict_id:'ukraine_russia',title_th:'รัสเซียโจมตีโครงข่ายไฟฟ้าเคียฟ ดับทั้งเมืองคืนที่สาม',time:iso(3*HOUR),source:'https://www.bbc.com',source_name:'BBC'},
    {id:'h4',conflict_id:'iran_us_israel_war',title_th:'กาตาร์เสนอกรอบเจรจาใหม่ อิหร่านยังไม่ตอบรับ',time:iso(5*HOUR),source:'https://www.aljazeera.com',source_name:'Al Jazeera'},
    {id:'h5',conflict_id:'sudan_civil_war',title_th:'RSF ยึดเมืองเอลโอเบด ประชาชนอพยพนับแสน',time:iso(6*HOUR),source:'https://www.unocha.org',source_name:'OCHA'},
    {id:'h6',conflict_id:'world',title_th:'IMF เตือนเศรษฐกิจโลกเสี่ยงชะลอเพิ่มหากน้ำมันค้างเหนือ 110 ดอลลาร์',time:iso(7*HOUR),source:'https://www.imf.org',source_name:'IMF'},
    {id:'h7',conflict_id:'gaza_israel',title_th:'ขบวนความช่วยเหลือเข้ากาซาเพิ่มเป็น 400 คันต่อวัน',time:iso(9*HOUR),source:'https://www.unocha.org',source_name:'OCHA'},
    {id:'h8',conflict_id:'myanmar_civil_war',title_th:'การสู้รบใกล้แม่สอด ผู้ลี้ภัยข้ามแดนเพิ่มอีก 2,000 คน',time:iso(11*HOUR),source:'https://www.unhcr.org',source_name:'UNHCR'},
    {id:'h9',conflict_id:'thailand',title_th:'ธปท. คงดอกเบี้ย จับตาต้นทุนพลังงาน',time:iso(13*HOUR),source:'https://www.bot.or.th',source_name:'ธปท.'},
    {id:'h10',conflict_id:'thailand_cambodia',title_th:'ไทย–กัมพูชาเปิดด่านช่องจอมอีกครั้งหลังหยุดยิง',time:iso(20*HOUR),source:'https://www.bangkokpost.com',source_name:'Bangkok Post'},
    {id:'h11',conflict_id:'iran_us_israel_war',title_th:'ค่าประกันภัยเรือผ่านฮอร์มุซพุ่งแตะ 2% ของมูลค่าเรือ',time:iso(30*HOUR),source:'https://www.lloydslist.com',source_name:"Lloyd's List"},
    {id:'h12',conflict_id:'yemen_houthi_saudi',title_th:'ฮูตีประกาศหยุดโจมตีเรือในทะเลแดงชั่วคราว',time:iso(40*HOUR),source:'https://www.reuters.com',source_name:'Reuters'}
  ]};
}
const status1 = () => ({ updated_at: iso(25*MIN), run_count: 41, ok: true, message_th: 'รอบล่าสุดสำเร็จ' });
const DATA_404 = (name) => (m) => /404/.test(m) && new RegExp('data/' + name + '\\.json').test(m);

test.beforeEach(() => resetData());
test.afterAll(() => resetData());

for (const vp of [{ name: 'desktop', w: 1280, h: 800, dpr: 1 }, { name: 'mobile', w: 390, h: 844, dpr: 3 }]) {
  const mobile = vp.w < 500;
  const ctxOpts = (scheme) => ({ viewport: { width: vp.w, height: vp.h }, colorScheme: scheme, deviceScaleFactor: vp.dpr, isMobile: mobile, hasTouch: mobile });

  test(`data fetch 404 -> offline banner, embedded data still shown (${vp.name})`, async ({ browser }) => {
    const ctx = await browser.newContext(ctxOpts('dark'));
    const page = await ctx.newPage();
    const errors = []; const allowed = [];
    page.on('console', m => { if (m.type() !== 'error') return; const t = m.text() + ' ' + (m.location().url || ''); (/404/.test(t) && /data\/(market|headlines|status|disasters|gold_history)\.json/.test(t) ? allowed : errors).push(t); });
    page.on('pageerror', e => errors.push('pageerror: ' + e.message));
    await page.goto(URL.nodata); await page.waitForTimeout(2500);
    expect(errors).toEqual([]);
    expect(allowed.length, 'the data/*.json requests 404ed').toBeGreaterThanOrEqual(1);
    await expect(page.locator('#live-slot .offline-bar')).toBeVisible();
    expect(await page.locator('#live-slot .offline-bar').innerText()).toContain('โหมดออฟไลน์');
    expect(await page.locator('#live-slot .ticker').count()).toBe(0);
    expect(await page.locator('#news-slot').isHidden()).toBe(true);
    expect(await page.locator('#live-flag-dot').getAttribute('class')).toContain('old');
    expect(await page.locator('#foot-live').textContent()).toBe('');
    // embedded data is still all there; the header falls back to the embedded date
    expect(await page.locator('#updated .u-full').textContent()).toBe('อัปเดต 2 พ.ย. 2569');
    expect(await page.locator('#updated').getAttribute('class')).not.toContain('is-stale');
    await expect(page).toHaveTitle('สถานการณ์โลก');
    expect(await page.locator('#title').textContent()).toBe('สถานการณ์โลก');
    expect(await page.locator('#view-overview .tile').count()).toBe(20);
    await page.click('.tab[data-tab="conflicts"]');
    expect(await page.locator('#view-conflicts .item').count()).toBe(25);
    await page.click('.tab[data-tab="gold"]');
    expect(await page.locator('#gold-tile-main .val').textContent()).toBe('$3,903');
    expect(await page.locator('#gold-tile-main .live-tag').isHidden()).toBe(true);
    await page.click('.tab[data-tab="overview"]');
    await noHScroll(page, 'offline');
    await page.screenshot({ path: path.join(SHOTS, `live-offline-${vp.name}.png`) });
    await ctx.close();
  });

  test(`served data feeds tiles, ticker, news and gold; re-poll picks up new files (${vp.name})`, async ({ browser }) => {
    writeData('market', market1()); writeData('headlines', head1()); writeData('status', status1());
    const ctx = await browser.newContext(ctxOpts('dark'));
    const page = await ctx.newPage(); const errors = collectErrors(page);
    const reqs = []; page.on('request', r => { if (/\/data\//.test(r.url())) reqs.push(new globalThis.URL(r.url()).pathname); });
    await page.goto(URL.mutable);
    await expect(page.locator('#live-slot .ticker .tk')).toHaveCount(11);
    // relative fetches resolve under the Pages sub-path
    expect([...new Set(reqs)].sort()).toEqual(['/global-analysis/data/disasters.json', '/global-analysis/data/gold_history.json', '/global-analysis/data/headlines.json', '/global-analysis/data/market.json', '/global-analysis/data/status.json']);
    // page title stays undated; the header date is the last live update in Bangkok time
    await expect(page).toHaveTitle('สถานการณ์โลก');
    expect(await page.locator('#title').textContent()).toBe('สถานการณ์โลก');
    expect(await page.locator('#live-slot .tk[data-key="brent"] .v').textContent()).toBe('116.4');
    expect(await page.locator('#live-slot .tk[data-key="spx"] .tk-c').getAttribute('class')).toContain('down');
    expect(await page.locator('#live-slot .live-head .sdot').getAttribute('class')).toContain('fresh');
    const age = await page.locator('#live-slot .live-head [data-age]').textContent();
    expect(age).toMatch(/^อัปเดตล่าสุด \d{1,2} (ม\.ค\.|ก\.พ\.|มี\.ค\.|เม\.ย\.|พ\.ค\.|มิ\.ย\.|ก\.ค\.|ส\.ค\.|ก\.ย\.|ต\.ค\.|พ\.ย\.|ธ\.ค\.) 25\d\d \d\d:\d\d น\. \(2[45] นาทีที่แล้ว\)$/);
    // Bangkok time (UTC+7) of status.updated_at
    const st = JSON.parse(JSON.stringify(status1()));
    const bkk = new Date(Date.parse(st.updated_at) + 7*HOUR);
    expect(age).toContain(('0' + bkk.getUTCHours()).slice(-2) + ':');
    expect(age).toContain(String(bkk.getUTCFullYear() + 543));
    const TH_M = ['ม.ค.','ก.พ.','มี.ค.','เม.ย.','พ.ค.','มิ.ย.','ก.ค.','ส.ค.','ก.ย.','ต.ค.','พ.ย.','ธ.ค.'];
    const hdr = 'อัปเดต ' + bkk.getUTCDate() + ' ' + TH_M[bkk.getUTCMonth()] + ' ' + (bkk.getUTCFullYear() + 543) + ' ' + ('0' + bkk.getUTCHours()).slice(-2) + ':' + ('0' + bkk.getUTCMinutes()).slice(-2) + ' น.';
    expect(await page.locator('#updated .u-full').textContent()).toBe(hdr);
    expect(await page.locator('#updated').getAttribute('class')).not.toContain('is-stale');
    expect(await page.locator('#live-slot .live-head .note').innerText()).toBe('ราคาจากงานตั้งเวลา วันละ 6 รอบ');
    expect(await page.locator('#live-flag-dot').getAttribute('class')).toContain('fresh');
    const sub = await page.evaluate(() => { const s = document.querySelector('.topbar .sub'); return [s.scrollWidth, s.clientWidth, s.getBoundingClientRect().height]; });
    expect(sub[0], 'header line not truncated').toBeLessThanOrEqual(sub[1]);
    expect(sub[2], 'header line single row').toBeLessThan(24);
    await expect(page.locator('#news-slot')).toBeVisible();
    expect(await page.locator('#news-slot .news li').count()).toBe(6);
    await page.click('#news-slot .news-more');
    expect(await page.locator('#news-slot .news li').count()).toBe(12);
    expect(await page.locator('#news-slot .news li.linked').count()).toBe(9);
    expect(await page.locator('#news-slot .news li', { hasText: 'ธปท.' }).locator('.tag').textContent()).toBe('ไทย');
    const tk = await page.evaluate(() => { const t = document.querySelector('#live-slot .ticker'); return [t.scrollWidth, t.clientWidth]; });
    expect(tk[0], 'ticker scrolls inside itself').toBeGreaterThan(tk[1]);
    await noHScroll(page, 'first load');
    await page.screenshot({ path: path.join(SHOTS, `live-served-${vp.name}-1.png`) });
    // gold tiles take the live gold / gold_th items
    await page.click('.tab[data-tab="gold"]');
    await expect(page.locator('#gold-tile-main .live-tag')).toBeVisible();
    expect(await page.locator('#gold-tile-main .val').textContent()).toBe('$3,843');
    expect(await page.locator('#gold-tile-th .val').textContent()).toBe('61,900');
    await page.click('.tab[data-tab="overview"]');

    // new files on the server -> visibilitychange re-poll
    const m2 = market1(); m2.updated_at = iso(MIN); m2.items[0].value = '118.0'; m2.items[0].change_th = '+2.6% วันนี้'; m2.items[2].value = '3,861.20';
    const h2 = head1(); h2.updated_at = iso(30000);
    h2.items.unshift({id:'h0',conflict_id:'iran_us_israel_war',title_th:'ด่วน: อิหร่านประกาศหยุดยิงชั่วคราว 72 ชม. ตามข้อเสนอกาตาร์',time:iso(5*MIN),source:'https://www.reuters.com',source_name:'Reuters'});
    writeData('market', m2); writeData('headlines', h2); writeData('status', { ...status1(), updated_at: iso(MIN), run_count: 42 });
    await repoll(page);
    await expect(page.locator('#live-slot .tk[data-key="brent"] .v')).toHaveText('118.0');
    expect(await page.locator('#live-slot .tk[data-key="gold"] .v').textContent()).toBe('3,861.20');
    expect(await page.locator('#live-slot .tk[data-key="wti"] .v').textContent()).toBe('112.8');
    expect(await page.locator('#live-slot .live-head [data-age]').textContent()).toMatch(/\((1 นาทีที่แล้ว|เมื่อสักครู่)\)$/);
    { const b2 = new Date(Date.now() - MIN + 7*HOUR), b3 = new Date(Date.now() + 7*HOUR);   // the new status time (a minute ago, give or take the poll)
      const hd = await page.locator('#updated .u-full').textContent();
      expect([b2, b3].some(b => hd.includes(('0' + b.getUTCHours()).slice(-2) + ':'))).toBe(true); }
    expect(await page.locator('#news-slot .news li').count()).toBe(13);
    expect(await page.locator('#news-slot .news li').first().innerText()).toContain('ด่วน');
    await page.click('.tab[data-tab="gold"]');
    expect(await page.locator('#gold-tile-main .val').textContent()).toBe('$3,861');
    await page.click('.tab[data-tab="overview"]');
    await page.screenshot({ path: path.join(SHOTS, `live-served-${vp.name}-2.png`) });
    // linked headline -> conflict card with a "ล่าสุด" block
    await page.locator('#news-slot .news li.linked').first().click();
    await expect(page.locator('#view-detail')).toBeVisible();
    expect(await page.locator('#view-detail h2').textContent()).toContain('อิหร่าน');
    await expect(page.locator('#card-latest .latest')).toBeVisible();
    expect(await page.locator('#card-latest .latest li').count()).toBe(3);
    await page.waitForTimeout(1300);
    await noHScroll(page, 'iran card');
    await page.screenshot({ path: path.join(SHOTS, `live-served-${vp.name}-iran.png`) });
    expect(errors).toEqual([]);
    await ctx.close();
  });
}

test('failed run, stale data and a failed re-poll keep the last data with a warning (mobile light)', async ({ browser }) => {
  writeData('market', market1()); writeData('headlines', head1()); writeData('status', status1());
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, colorScheme: 'light', deviceScaleFactor: 3, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  const errors = []; page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !DATA_404('market')(m.text() + ' ' + (m.location().url || ''))) errors.push('console: ' + m.text()); });
  await page.goto(URL.mutable);
  await expect(page.locator('#live-slot .ticker .tk')).toHaveCount(11);
  const note = page.locator('#live-slot .live-head .note');

  // 1. the updater failed: status.ok=false -> warning note, "อัปเดตล่าสุด" falls back to the market time
  writeData('status', { updated_at: iso(MIN), run_count: 42, ok: false, message_th: 'อัปเดตอัตโนมัติไม่สำเร็จ (ทดสอบ) แสดงค่าล่าสุดที่ได้รับ' });
  await repoll(page);
  await expect(note).toHaveText('อัปเดตอัตโนมัติไม่สำเร็จ (ทดสอบ) แสดงค่าล่าสุดที่ได้รับ');
  expect(await note.getAttribute('class')).toContain('warn');
  expect(await page.locator('#live-slot .live-head [data-age]').textContent()).toMatch(/\(2[45] นาทีที่แล้ว\)$/);

  // 2. data older than 10 h -> stale dot + note
  const old = market1(); old.updated_at = iso(11*HOUR);
  writeData('market', old); writeData('status', { updated_at: iso(11*HOUR), run_count: 43, ok: true, message_th: 'สำเร็จ' });
  await repoll(page);
  await expect(note).toContainText('ข้อมูลเก่ากว่า 10 ชม.');
  expect(await page.locator('#live-slot .live-head .sdot').getAttribute('class')).toContain('stale');
  expect(await page.locator('#live-flag-dot').getAttribute('class')).toContain('stale');
  expect(await page.locator('#live-slot .live-head').getAttribute('class')).toContain('is-stale');
  expect(await page.locator('#live-slot .live-head [data-age]').textContent()).toContain('(11 ชม. ที่แล้ว)');
  // the header date shows the same old time and is marked stale like the live flag
  expect(await page.locator('#updated').getAttribute('class')).toContain('is-stale');
  expect(await page.locator('#updated .u-full').textContent()).toMatch(/^อัปเดต \d{1,2} \S+ 25\d\d \d\d:\d\d น\.$/);
  await page.evaluate(() => document.getElementById('main').style.setProperty('--sheet-h', '90%'));
  await page.waitForTimeout(400);
  await noHScroll(page, 'stale');
  await page.screenshot({ path: path.join(SHOTS, 'live-stale-mobile-light.png') });

  // 3. market.json disappears on a later poll -> last data kept, no offline banner, warning note
  removeData('market');
  await repoll(page);
  await expect(note).toHaveText('โหลดข้อมูลรอบล่าสุดไม่สำเร็จ แสดงค่าล่าสุดที่ได้รับ');
  expect(await page.locator('#live-slot .offline-bar').count()).toBe(0);
  expect(await page.locator('#live-slot .tk[data-key="brent"] .v').textContent()).toBe('116.4');

  // 4. back to normal
  writeData('market', market1()); writeData('status', status1());
  await repoll(page);
  await expect(note).toHaveText('ราคาจากงานตั้งเวลา วันละ 6 รอบ');
  expect(await note.getAttribute('class')).not.toContain('warn');
  expect(await page.locator('#updated').getAttribute('class')).not.toContain('is-stale');
  expect(errors).toEqual([]);
  await ctx.close();
});

test('re-polls on its own on a timer (10 min in production, ?poll=1500 here)', async ({ browser }) => {
  writeData('market', market1()); writeData('headlines', head1()); writeData('status', status1());
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage(); const errors = collectErrors(page);
  await page.goto(URL.mutable + '?poll=1500');
  await expect(page.locator('#live-slot .ticker .tk')).toHaveCount(11);
  const polls = () => page.evaluate(() => (window.__liveState || {}).polls || 0);
  const m2 = market1(); m2.items[0].value = '120.5'; writeData('market', m2);
  await expect(page.locator('#live-slot .tk[data-key="brent"] .v')).toHaveText('120.5', { timeout: 8000 });
  expect(await polls()).toBeGreaterThanOrEqual(2);
  // production interval stays 10 minutes
  const html = await (await page.request.get(URL.mutable)).text();
  expect(html).toContain('var POLL_MS = 10*60*1000;');
  expect(errors).toEqual([]);
  await ctx.close();
});
