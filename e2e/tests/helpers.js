const fs = require('fs');
const path = require('path');
const { expect } = require('@playwright/test');

const BASE_PORT = +(process.env.E2E_PORT || 18731);
const PORTS = { full: BASE_PORT, nodata: BASE_PORT + 1, mutable: BASE_PORT + 2 };
const URL = Object.fromEntries(Object.entries(PORTS).map(([m, p]) => [m, `http://127.0.0.1:${p}/global-analysis/`]));
const SHOTS = path.join(__dirname, '..', 'shots');
const SEED = path.join(__dirname, '..', '..', 'site', 'data');
const MUT = path.join(__dirname, '..', '.srv', 'mutable', 'global-analysis', 'data');
fs.mkdirSync(SHOTS, { recursive: true });

function writeData(name, obj) { fs.writeFileSync(path.join(MUT, name + '.json'), JSON.stringify(obj, null, 1)); }
function removeData(name) { try { fs.unlinkSync(path.join(MUT, name + '.json')); } catch (e) { /* already gone */ } }
function resetData() { fs.mkdirSync(MUT, { recursive: true }); for (const n of ['market', 'headlines', 'status']) fs.copyFileSync(path.join(SEED, n + '.json'), path.join(MUT, n + '.json')); }
function seed(name) { return JSON.parse(fs.readFileSync(path.join(SEED, name + '.json'), 'utf8')); }

// console errors + page errors; `allow` = regexes for expected messages (e.g. a deliberate 404)
function collectErrors(page, allow = []) {
  const errors = [];
  page.on('console', m => { if (m.type() === 'error' && !allow.some(r => r.test(m.text() + ' ' + (m.location().url || '')))) errors.push('console: ' + m.text() + ' @ ' + (m.location().url || '')); });
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  return errors;
}
async function noHScroll(page, label) {
  const sw = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth, document.body.scrollWidth]);
  expect(sw[0], `no horizontal scroll (${label})`).toBeLessThanOrEqual(sw[1]);
  expect(sw[2], `body no horizontal scroll (${label})`).toBeLessThanOrEqual(sw[1]);
}
// trigger the page's visibilitychange re-poll and wait until the poll has finished
async function repoll(page) {
  const before = await page.evaluate(() => (window.__liveState || {}).polls || 0);
  await page.waitForTimeout(2200); // the page ignores re-polls < 2 s apart
  await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange')));
  await expect.poll(() => page.evaluate(() => (window.__liveState || {}).polls || 0)).toBeGreaterThan(before);
}

module.exports = { PORTS, URL, SHOTS, writeData, removeData, resetData, seed, collectErrors, noHScroll, repoll };
