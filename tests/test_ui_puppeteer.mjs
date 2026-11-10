// Puppeteer-core UI guard: narrow widths + Trends tab charts, both themes.
// Uses the installed Chrome against the running copy server.
import puppeteer from 'puppeteer-core';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const SHOT_DIR = fileURLToPath(new URL('./screenshots/', import.meta.url));
fs.mkdirSync(SHOT_DIR, { recursive: true });
const BASE = process.env.NETPULSE_URL || 'http://localhost:5000';

async function noOverflow(page, label) {
  const overflow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  assert.ok(
    overflow.scrollWidth <= overflow.clientWidth + 2,
    `${label}: no horizontal overflow (${overflow.scrollWidth} > ${overflow.clientWidth})`
  );
}

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: 'new',
  args: ['--no-sandbox', '--disable-dev-shm-usage'],
});

try {
  for (const theme of ['dark', 'light']) {
    for (const viewport of [{ w: 1280, h: 900, name: 'desktop' }, { w: 375, h: 780, name: 'mobile' }]) {
      const page = await browser.newPage();
      const errors = [];
      page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
      page.on('pageerror', (e) => errors.push(String(e)));
      await page.setViewport({ width: viewport.w, height: viewport.h });
      await page.goto(BASE, { waitUntil: 'networkidle2', timeout: 30000 });
      await page.evaluate((t) => {
        localStorage.setItem('netpulse-theme', t);
        localStorage.setItem('netpulse-tab', 'measure');
        document.documentElement.setAttribute('data-theme', t);
      }, theme);
      await page.reload({ waitUntil: 'networkidle2' });
      // The gauge is built on DOMContentLoaded; wait for it explicitly.
      await page.waitForSelector('.gauge-svg', { timeout: 15000 });
      // Last-tab memory is a feature: make the tab explicit for the check.
      await page.evaluate(() => {
        document.querySelector('[data-tab-btn="measure"]').click();
      });
      await new Promise((r) => setTimeout(r, 300));
      const label = `${theme}/${viewport.name}`;

      // Measure tab renders and does not overflow.
      await noOverflow(page, `${label} measure`);
      const gaugeVisible = await page.evaluate(() => {
        const g = document.querySelector('.gauge-svg');
        if (!g) return { ok: false, w: 0, h: 0 };
        const r = g.getBoundingClientRect();
        return { ok: r.width > 50 && r.height > 20, w: Math.round(r.width), h: Math.round(r.height) };
      });
      assert.ok(
        gaugeVisible.ok,
        `${label}: gauge is rendered (${gaugeVisible.w}x${gaugeVisible.h})`
      );

      // Trends tab: switch, charts must build and be visible.
      await page.evaluate(() => {
        document.querySelector('[data-tab-btn="trends"]').click();
      });
      await new Promise((r) => setTimeout(r, 1200));
      const charts = await page.evaluate(() => {
        const sizes = {};
        for (const id of ['speedChart', 'latencyChart', 'hourlyChart']) {
          const c = document.getElementById(id);
          const r = c ? c.getBoundingClientRect() : null;
          sizes[id] = r ? { w: Math.round(r.width), h: Math.round(r.height) } : null;
        }
        const panel = document.getElementById('tab-trends');
        return { charts: sizes, trendsHidden: panel ? panel.hidden : null };
      });
      assert.equal(charts.trendsHidden, false, `${label}: trends panel visible`);
      for (const [id, size] of Object.entries(charts.charts)) {
        assert.ok(size && size.w > 40 && size.h > 40, `${label}: ${id} rendered (${JSON.stringify(size)})`);
      }
      await noOverflow(page, `${label} trends`);

      // Log tab renders rows.
      await page.evaluate(() => { document.querySelector('[data-tab-btn="log"]').click(); });
      await new Promise((r) => setTimeout(r, 1200));
      const logState = await page.evaluate(() => ({
        rows: document.querySelectorAll('[data-log-id]').length,
        filters: !!document.querySelector('[data-log-filter="range"]'),
        hidden: document.getElementById('tab-log')?.hidden,
      }));
      assert.equal(logState.hidden, false, `${label}: log panel visible`);
      assert.ok(logState.filters, `${label}: log filters present`);
      await noOverflow(page, `${label} log`);

      // Settings tab renders the plan-speed field.
      await page.evaluate(() => { document.querySelector('[data-tab-btn="settings"]').click(); });
      await new Promise((r) => setTimeout(r, 800));
      const hasPlan = await page.evaluate(() => !!document.getElementById('planSpeed'));
      assert.ok(hasPlan, `${label}: settings has plan speed field`);
      await noOverflow(page, `${label} settings`);

      await page.screenshot({ path: path.join(SHOT_DIR, `ui-${theme}-${viewport.name}.png`), fullPage: false });
      assert.deepEqual(errors, [], `${label}: no console errors: ${errors.join(' | ')}`);
      await page.close();
    }
  }
} finally {
  await browser.close();
}
console.log('puppeteer UI guard passed (dark/light x desktop/mobile)');
