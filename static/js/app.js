/* ══════════════════════════════════════════════════════
   NetPulse — app.js (slim orchestrator)
   Data fetch · render pipeline · wiring.
   Rendering lives in stats.js / outages.js / log.js /
   insights.js / settings.js; tabs/theme in tabs.js / theme.js.
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
import { LogView } from './log.js';
import { SettingsView } from './settings.js';
import {
  renderCompatibility,
  renderHealth,
  renderHeatmap,
  renderPlanInfo,
  renderWorseChip,
} from './insights.js';
import { formatLatency, formatSpeedText } from './format.js';

import {
  destroyCharts,
  buildSpeedChart,
  buildLatencyChart,
  buildHourlyChart,
} from './charts.js';

/* ── STATE ──────────────────────────────────────────── */
let currentRange = '7d';
let currentEngine = 'all';
let includeFlagged = false;
let heroScrambled = false;
let lastData = null;
let lastInsights = null;

const PILL_POLL_MS = 60_000;
const INCIDENT_POLL_MS = 20_000;
const ERROR_POLL_MS = 60_000;

const logView = new LogView();
const settingsView = new SettingsView();

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
      `/api/data?range=${encodeURIComponent(range)}`
      + `&engine=${encodeURIComponent(currentEngine)}`
      + `&include_flagged=${includeFlagged ? '1' : '0'}`,
      { cache: 'no-store' }
    );
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    render(await res.json());
  } catch (err) {
    console.error('[NetPulse] Data load error:', err);
    showToast('error', err.message || 'Failed to load data — is the server running?');
  }
}

async function loadInsights() {
  try {
    const res = await fetch(
      `/api/insights?range=${encodeURIComponent(currentRange)}`
      + `&include_flagged=${includeFlagged ? '1' : '0'}`,
      { cache: 'no-store' }
    );
    if (!res.ok) return;
    lastInsights = await res.json();
    renderHealth(document.getElementById('healthCard'), lastInsights.health);
    renderCompatibility(document.getElementById('compatCard'), lastInsights.compatibility);
    renderPlanInfo(document.getElementById('planInfo'), lastInsights.plan);
    renderWorseChip(document.getElementById('worseChip'), lastInsights.worse_than_usual);
    renderHeatmap(document.getElementById('heatmapMount'), lastInsights.heatmap);
  } catch (err) {
    console.error('[NetPulse] insights load error:', err);
  }
}

/* ── Internal error banner ──────────────────────────── */
async function pollErrors() {
  try {
    const res = await fetch('/api/errors', { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    const banner = document.getElementById('errorBanner');
    if (!banner) return;
    if (data.show_banner) {
      document.getElementById('errorBannerTitle').textContent =
        `NetPulse hit ${data.consecutive} internal errors`;
      const last = (data.errors || [])[0];
      document.getElementById('errorBannerText').textContent = last
        ? `${last.kind}: ${last.message} (${last.timestamp}) — measurements are paused until this is fixed.`
        : 'Measurements are paused until this is fixed.';
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  } catch {
    // Transient error — the next tick retries.
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

/* ── LIVE INCIDENT TOASTS ────────────────────────────── */
let lastIncidentTimestamp = null;

async function pollIncidents() {
  try {
    const url = lastIncidentTimestamp
      ? `/api/updates?since=${encodeURIComponent(lastIncidentTimestamp)}`
      : '/api/updates';
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    if (data.latest_timestamp) lastIncidentTimestamp = data.latest_timestamp;
    const events = data.events || [];
    if (!events.length) return;
    for (const ev of events) {
      const kind = ev.kind === 'outage' ? 'Outage recorded' : 'Test failed';
      showToast('error', `${kind} — ${ev.reason || 'no reason given'} (${ev.timestamp})`);
    }
    logView.prependEntries(events.map((ev) => ({
      kind: ev.kind, id: ev.id, timestamp: ev.timestamp, reason: ev.reason,
      download_mbps: null, upload_mbps: null, ping_cloudflare_ms: null,
      loaded_ms: null, jitter_ms: null, loss_cloudflare_pct: null,
      engine: null, server: null, client: null,
    })));
    loadData(currentRange);
  } catch {
    // Transient error — the next tick retries.
  }
}

/* ── COPY SUMMARY ───────────────────────────────────── */
function copySummary() {
  const latest = lastInsights && lastInsights.latest;
  if (!latest) {
    showToast('info', 'No measurement to summarise yet.');
    return;
  }
  const lines = [
    'NetPulse result',
    `When: ${latest.timestamp}`,
    `Download: ${formatSpeedText(latest.download_mbps)}`,
    `Upload: ${formatSpeedText(latest.upload_mbps)}`,
    `Idle latency (1.1.1.1): ${formatLatency(latest.ping_cloudflare_ms)}`,
    `Loaded latency (1.1.1.1): ${formatLatency(latest.loaded_ms)}`,
    `Jitter (1.1.1.1): ${formatLatency(latest.jitter_ms)}`,
    `Engine: ${latest.engine || '–'}`,
    `Server: ${latest.server || '–'}`,
  ];
  const plan = lastInsights.plan || {};
  if (plan.plan_speed_mbps && plan.pct_of_plan != null) {
    lines.push(`% of plan (${plan.plan_speed_mbps} Mbps): ${plan.pct_of_plan}%`);
  }
  if (lastInsights.health) {
    lines.push(`Health score: ${lastInsights.health.score}/100 (${lastInsights.health.verdict})`);
  }
  const text = lines.join('\n');
  navigator.clipboard.writeText(text)
    .then(() => showToast('success', 'Result summary copied (no IP included).'))
    .catch(() => showToast('error', 'Could not copy the summary.'));
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
      loadInsights();
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
  const flaggedToggle = document.getElementById('includeFlagged');
  if (flaggedToggle) {
    flaggedToggle.addEventListener('change', () => {
      includeFlagged = flaggedToggle.checked;
      loadData(currentRange);
      loadInsights();
      logView.setFilters({ include_flagged: includeFlagged });
    });
  }
  const bannerClose = document.getElementById('errorBannerClose');
  if (bannerClose) {
    bannerClose.addEventListener('click', () => {
      const banner = document.getElementById('errorBanner');
      if (banner) banner.hidden = true;
    });
  }
  logView.init();
  settingsView.init();
  initTabs((tab) => {
    if (tab === 'trends' && lastData) buildChartsFor(lastData, 'trends');
    if (tab === 'log') logView.load();
    if (tab === 'settings') settingsView.load();
  });
  const gaugeMount = document.getElementById('liveTestMount');
  if (gaugeMount) {
    const gauge = new SpeedTestGauge(gaugeMount, { onComplete: () => { loadData(currentRange); loadInsights(); } });
    gauge.render();
    initSpotlightCards();
    initMagneticButtons();
  }
  const copyBtn = document.getElementById('copySummary');
  if (copyBtn) copyBtn.addEventListener('click', copySummary);
  window.addEventListener('netpulse:theme', () => {
    if (lastData) buildChartsFor(lastData, currentTab());
  });
  window.addEventListener('netpulse:settings', () => {
    loadInsights();
    loadData(currentRange);
  });
  loadData(currentRange);
  loadInsights();
  pollErrors();
  setInterval(refreshPill, PILL_POLL_MS);
  setInterval(pollIncidents, INCIDENT_POLL_MS);
  setInterval(pollErrors, ERROR_POLL_MS);
}

document.addEventListener('DOMContentLoaded', init);
