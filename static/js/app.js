/* ══════════════════════════════════════════════════════
   NetPulse — app.js (slim orchestrator)
   Data fetch · render pipeline · wiring.
   Rendering lives in stats.js / outages.js; tabs/theme in
   tabs.js / theme.js so this file stays under 400 lines.
   ══════════════════════════════════════════════════════ */

import {
  initSpotlightCards,
  initMagneticButtons,
  initTubelightNav,
  textScramble,
  initScrollProgress,
  createProgressRing,
  showStatSkeletons,
  showToast,
  renderEmptyState,
  initModal,
} from './components.js';

import { SpeedTestGauge } from './speedtest.js';
import { initTheme } from './theme.js';
import { initTabs, currentTab } from './tabs.js';
import { renderStatCards } from './stats.js';
import { renderOutages } from './outages.js';

import {
  destroyCharts,
  buildSpeedChart,
  buildLatencyChart,
  buildHourlyChart,
} from './charts.js';

import { formatSpeedText } from './format.js';

/* ── STATE ──────────────────────────────────────────── */
let currentRange = '7d';
let currentEngine = 'all';
let heroScrambled = false;
let lastData = null;

const PILL_POLL_MS = 60_000;

/* ── FORMATTERS ─────────────────────────────────────── */
function timeAgo(isoStr) {
  if (!isoStr) return 'never';
  const then = new Date(isoStr.replace(' ', 'T'));
  const mins = Math.round((Date.now() - then.getTime()) / 60_000);
  if (isNaN(mins)) return 'unknown';
  if (mins < 2) return 'just now';
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/* ── HERO ───────────────────────────────────────────── */
function renderHero(stats, lastMeasured) {
  const ringEl = document.getElementById('uptimeRingContainer');
  if (ringEl) createProgressRing(ringEl, stats.uptime_pct);
  const uptimeVal = document.getElementById('uptimeValue');
  const uptimeSub = document.getElementById('uptimeSubtitle');
  if (uptimeVal) uptimeVal.textContent = stats.uptime_pct !== null ? stats.uptime_pct + '%' : '–';
  if (uptimeSub) uptimeSub.textContent = 'Uptime';
  const pill = document.getElementById('lastMeasuredPill');
  if (pill) {
    pill.innerHTML = `<span class="pulse-dot"></span> last measured ${timeAgo(lastMeasured)}`;
  }
  if (!heroScrambled) {
    heroScrambled = true;
    const el = document.getElementById('heroHeadline');
    if (!el) return;
    const mbps = stats.avg_download_mbps;
    let plain, richHTML;
    if (mbps !== null) {
      const status = stats.uptime_pct >= 99 ? 'healthy' : stats.uptime_pct >= 95 ? 'stable' : 'degraded';
      const avgText = formatSpeedText(mbps);
      plain = `Your internet is ${status} — averaging ${avgText} this week`;
      richHTML = `Your internet is <span class="grad-text">${status}</span> — averaging <span class="grad-text">${avgText}</span> this week`;
    } else {
      plain = 'NetPulse is monitoring your ISP performance';
      richHTML = `NetPulse is <span class="grad-text">monitoring</span> your ISP performance`;
    }
    textScramble(el, plain, 850, richHTML);
  }
}

function buildChartsFor(data, tab) {
  if (tab !== 'trends') return;
  const { measurements, hourly_avg_download } = data;
  if (!measurements.length) return;
  destroyCharts();
  buildSpeedChart(measurements);
  buildLatencyChart(measurements);
  buildHourlyChart(hourly_avg_download);
}

/* ── MAIN RENDER ─────────────────────────────────────── */
function render(data) {
  lastData = data;
  const { stats, measurements, outages, failed_tests, hourly_avg_download, last_measured } = data;
  const failedList = failed_tests || [];
  const isEmpty = !measurements.length && !outages.length && !failedList.length;
  const chartsSection = document.getElementById('chartsSection');
  const outagesSection = document.getElementById('outagesSection');
  if (isEmpty) {
    renderEmptyState(document.getElementById('statsGrid'));
    destroyCharts();
    if (chartsSection) chartsSection.style.display = 'none';
    if (outagesSection) outagesSection.style.display = 'none';
    return;
  }
  if (chartsSection) chartsSection.style.display = '';
  if (outagesSection) outagesSection.style.display = '';
  renderHero(stats, last_measured);
  renderStatCards(stats, currentEngine);
  buildChartsFor(data, currentTab());
  renderOutages(outages, failedList);
  initSpotlightCards();
}

/* ── DATA FETCH ──────────────────────────────────────── */
async function loadData(range) {
  showStatSkeletons(document.getElementById('statsGrid'), 5);
  try {
    const res = await fetch(
      `/api/data?range=${encodeURIComponent(range)}&engine=${encodeURIComponent(currentEngine)}`,
      { cache: 'no-store' }
    );
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    render(await res.json());
  } catch (err) {
    console.error('[NetPulse] Data load error:', err);
    showToast('error', err.message || 'Failed to load data — is the server running?');
  }
}

async function refreshPill() {
  try {
    const res = await fetch(`/api/data?range=${encodeURIComponent(currentRange)}`, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    const pill = document.getElementById('lastMeasuredPill');
    if (pill && data.last_measured) {
      pill.innerHTML = `<span class="pulse-dot"></span> last measured ${timeAgo(data.last_measured)}`;
    }
  } catch {}
}

/* ── BOOT ────────────────────────────────────────────── */
function init() {
  initTheme();
  initScrollProgress(document.getElementById('scrollProgress'));
  initModal();
  const nav = document.getElementById('rangePicker');
  if (nav) {
    initTubelightNav(nav, (range) => {
      currentRange = range;
      loadData(currentRange);
    });
    nav.querySelectorAll('button').forEach((b) => b.classList.add('magnetic-btn'));
    initMagneticButtons();
  }
  const engineFilter = document.getElementById('engineFilter');
  if (engineFilter) {
    engineFilter.addEventListener('change', () => {
      currentEngine = engineFilter.value;
      loadData(currentRange);
    });
  }
  initTabs((tab) => {
    if (tab === 'trends' && lastData) buildChartsFor(lastData, 'trends');
  });
  const gaugeMount = document.getElementById('liveTestMount');
  if (gaugeMount) {
    const gauge = new SpeedTestGauge(gaugeMount, { onComplete: () => loadData(currentRange) });
    gauge.render();
    initSpotlightCards();
    initMagneticButtons();
  }
  window.addEventListener('netpulse:theme', () => {
    if (lastData) buildChartsFor(lastData, currentTab());
  });
  loadData(currentRange);
  setInterval(refreshPill, PILL_POLL_MS);
}

document.addEventListener('DOMContentLoaded', init);
