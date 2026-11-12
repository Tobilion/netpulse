// Puppeteer guard for the failure-handling UI: flagged-rows toggle, the
// "Measured to" field in the Log detail, and the internal-error banner.
import puppeteer from 'puppeteer-core';
import assert from 'node:assert/strict';

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const BASE = process.env.NETPULSE_URL || 'http://localhost:5000';

const browser = await puppeteer.launch({
  executablePath: CHROME, headless: 'new', args: ['--no-sandbox'],
});

try {
  const page = await browser.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.setViewport({ width: 1280, height: 900 });
  await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 30000 });

  // A remembered tab must load its content on page load.
  await page.evaluate(() => localStorage.setItem('netpulse-tab', 'log'));
  await page.reload({ waitUntil: 'networkidle2' });
  await page.waitForSelector('[data-log-id]', { timeout: 15000 });

  const hasToggle = await page.evaluate(() => !!document.querySelector('#includeFlagged'));
  assert.ok(hasToggle, 'flagged-rows toggle present');

  // The toggle must be able to change the result set.
  const rowsBefore = await page.evaluate(() => document.querySelectorAll('[data-log-id]').length);
  await page.evaluate(() => {
    const cb = document.querySelector('#includeFlagged');
    cb.checked = true;
    cb.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await new Promise((r) => setTimeout(r, 1500));
  const rowsAfter = await page.evaluate(() => document.querySelectorAll('[data-log-id]').length);
  assert.ok(rowsAfter >= rowsBefore, 'including flagged rows does not hide rows');

  // The detail modal must say where the measurement was taken.
  await page.evaluate(() => document.querySelector('[data-log-id]').click());
  await new Promise((r) => setTimeout(r, 600));
  const fields = await page.evaluate(() => [...document.querySelectorAll('#modalContent .field-label')]
    .map((e) => e.textContent));
  assert.ok(fields.includes('Measured to'), `detail shows "Measured to": ${fields.join(', ')}`);

  // The internal-error banner exists and stays hidden while healthy.
  const banner = await page.evaluate(() => {
    const b = document.getElementById('errorBanner');
    return { exists: !!b, hidden: b ? b.hidden : null };
  });
  assert.ok(banner.exists, 'internal-error banner element exists');
  assert.equal(banner.hidden, true, 'banner hidden while the tool is healthy');

  assert.deepEqual(errors, [], `no console errors: ${errors.join(' | ')}`);
  await page.close();
} finally {
  await browser.close();
}
console.log('puppeteer failure-handling UI guard passed');
