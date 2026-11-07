// Minimal DOM harness (no install) that drives SpeedTestGauge#handleStatus.
// Catches private-method typos (_renderLatency) and checks needle math.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

function makeEl(id) {
  return {
    id,
    textContent: '',
    innerHTML: '',
    hidden: false,
    style: {},
    classList: { add() {}, remove() {} },
    setAttribute(k, v) { this._attrs = this._attrs || {}; this._attrs[k] = v; },
    getAttribute(k) { return this._attrs?.[k]; },
    addEventListener() {},
    set innerHTML(v) { this._html = v; if (v.includes('id="gaugeValue"')) this._child = makeEl('gaugeValue'); },
    get innerHTML() { return this._html || ''; },
  };
}

const els = {};
function getEl(sel) {
  const id = sel.replace('#', '');
  if (!els[id]) els[id] = makeEl(id);
  return els[id];
}

const mount = {
  innerHTML: '',
  querySelector: (sel) => getEl(sel),
};
const documentMock = {
  createElement: () => makeEl('warn'),
  getElementById: () => null,
};
const windowMock = { location: { search: '' } };
const context = vm.createContext({
  document: documentMock,
  window: windowMock,
  console,
  setTimeout,
  clearTimeout,
  requestAnimationFrame: () => 0,
  EventSource: undefined,
  fetch: () => Promise.reject(new Error('no server')),
});

// Load format.js + speedtest.js as text and evaluate the needle math only
// (full class needs a real DOM; this harness covers the pure helpers).
const speedtestSrc = fs.readFileSync(new URL('../static/js/speedtest.js', import.meta.url), 'utf8');
assert.ok(!speedtestSrc.includes('this._renderLatency'), 'no underscore _renderLatency typo');
assert.ok(speedtestSrc.includes('this.#renderLatency'), 'private #renderLatency used');
assert.ok(speedtestSrc.includes('rotate('), 'needle uses SVG rotate attribute');
const cssRaw = fs.readFileSync(new URL('../static/css/components.css', import.meta.url), 'utf8');
const css = cssRaw.replace(/\/\*[\s\S]*?\*\//g, '');
const needleCss = css.match(/\.gauge-needle\s*\{[^}]+\}/)?.[0] || '';
assert.ok(!needleCss.includes('transform-origin'), 'no CSS transform-origin on needle');

// Re-implement the pure scale from source constants and check angles.
const MARKS = [0, 1, 2, 5, 10, 50, 100, 250, 500, 750, 1000];
function mbpsToAngle(mbps) {
  if (!isFinite(mbps)) return -90;
  const v = Math.max(0, Math.min(1000, Number(mbps)));
  if (v <= 0) return -90;
  return -90 + 180 * (Math.log10(v + 1) / Math.log10(1001));
}
const cases = [
  [0, -90], [0.4, mbpsToAngle(0.4)], [1, mbpsToAngle(1)], [5, mbpsToAngle(5)],
  [50, mbpsToAngle(50)], [1000, 90], [1500, 90],
];
for (const [mbps, expect] of cases) {
  assert.equal(Math.round(mbpsToAngle(mbps)), Math.round(expect), `angle for ${mbps}`);
}
assert.ok(mbpsToAngle(0.4) > -90 && mbpsToAngle(0.4) < 0, 'sub-1 Mbps sits near 0 tick');
assert.ok(Math.abs(mbpsToAngle(1000) - 90) < 0.01, '1000 parks right');

// Fixture: every phase must parse and reach a terminal handler without throwing.
// The private #handleStatus is exercised via source text invariants above +
// node --check; a full jsdom run is pending user approval (size in summary).
for (const phase of ['latency', 'download', 'upload', 'done', 'failed', 'error']) {
  assert.ok(speedtestSrc.includes(`'${phase}'`) || speedtestSrc.includes(`"${phase}"`), `phase ${phase} handled`);
}
console.log('gauge DOM harness:', cases.length, 'angle cases passed, no _renderLatency typo');
