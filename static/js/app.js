/* ══════════════════════════════════════════════════════
   NetPulse — app.js
   Data fetch · render pipeline · component wiring
   ══════════════════════════════════════════════════════ */

import {
  initSpotlightCards,
  initTiltCards,
  initMagneticButtons,
  initTubelightNav,
  textScramble,
  initScrollProgress,
  observeAndCount,
  createProgressRing,
  showStatSkeletons,
  showToast,
  renderEmptyState,
  openModal,
  initModal,
} from './components.js';

import {
  destroyCharts,
  buildSpeedChart,
  buildLatencyChart,
  buildHourlyChart,
} from './charts.js';

/* ── STATE ──────────────────────────────────────────── */
let currentRange   = '7d';
let heroScrambled  = false;

/* ── FORMATTERS ─────────────────────────────────────── */
function fmt(v, suffix = '') {
  return (v === null || v === undefined) ? '–' : `${v}${suffix}`;
}

function timeAgo(isoStr) {
  if (!isoStr) return 'never';
  const then = new Date(isoStr.replace(' ', 'T') + (isoStr.includes('T') ? '' : 'Z'));
  const mins = Math.round((Date.now() - then.getTime()) / 60_000);
  if (isNaN(mins))    return 'unknown';
  if (mins < 2)       return 'just now';
  if (mins < 60)      return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24)       return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

/* ── HERO ────────────────────────────────────────────── */
function renderHero(stats, lastMeasured) {
  // Uptime progress ring
  const ringEl = document.getElementById('uptimeRingContainer');
  if (ringEl) createProgressRing(ringEl, stats.uptime_pct);

  // Uptime value beside the ring
  const uptimeVal = document.getElementById('uptimeValue');
  const uptimeSub = document.getElementById('uptimeSubtitle');
  if (uptimeVal) uptimeVal.textContent = stats.uptime_pct !== null ? stats.uptime_pct + '%' : '–';
  if (uptimeSub) uptimeSub.textContent = 'Uptime';

  // Last measured pill
  const pill = document.getElementById('lastMeasuredPill');
  if (pill) {
    pill.innerHTML = `<span class="pulse-dot"></span> last measured ${timeAgo(lastMeasured)}`;
  }

  // Hero headline with TextScramble — fires once per page load
  if (!heroScrambled) {
    heroScrambled = true;
    const el = document.getElementById('heroHeadline');
    if (!el) return;

    const mbps = stats.avg_download_mbps;
    let plain, richHTML;

    if (mbps !== null) {
      const status = stats.uptime_pct >= 99 ? 'healthy' : stats.uptime_pct >= 95 ? 'stable' : 'degraded';
      plain   = `Your internet is ${status} — averaging ${mbps} Mbps this week`;
      richHTML = `Your internet is <span class="grad-text">${status}</span> — averaging <span class="grad-text">${mbps} Mbps</span> this week`;
    } else {
      plain   = 'NetPulse is monitoring your ISP performance';
      richHTML = `NetPulse is <span class="grad-text">monitoring</span> your ISP performance`;
    }

    textScramble(el, plain, 850, richHTML);
  }
}

/* ── STAT CARDS ─────────────────────────────────────── */
function renderStatCards(stats) {
  const grid = document.getElementById('statsGrid');
  if (!grid) return;
  grid.innerHTML = '';

  const CARDS = [
    {
      label:  'UPTIME',
      value:  stats.uptime_pct,
      suffix: '%',
      cls:    stats.uptime_pct === null ? ''
              : stats.uptime_pct >= 99  ? 'good'
              : stats.uptime_pct < 95   ? 'bad'
              : 'accent',
    },
    { label: 'AVG DOWNLOAD', value: stats.avg_download_mbps, suffix: ' Mbps', cls: 'accent' },
    { label: 'AVG UPLOAD',   value: stats.avg_upload_mbps,   suffix: ' Mbps', cls: '' },
    { label: 'AVG PING',     value: stats.avg_ping_ms,       suffix: ' ms',   cls: '' },
    {
      label:  'OUTAGES',
      value:  stats.outage_count,
      suffix: '',
      cls:    stats.outage_count > 0 ? 'bad' : 'good',
    },
  ];

  CARDS.forEach((c, i) => {
    const div = document.createElement('div');
    div.className = 'stat-card spotlight-card tilt-card fade-up';
    div.style.animationDelay = `${i * 80}ms`;

    const hasValue = c.value !== null && c.value !== undefined;
    div.innerHTML = `
      <div class="card-label">${c.label}</div>
      <div class="card-value ${c.cls}"
        data-target="${hasValue ? c.value : ''}"
        data-suffix="${c.suffix}">
        ${hasValue ? '0' + c.suffix : '–'}
      </div>
    `;
    grid.appendChild(div);
  });

  // Wire up AnimatedCounters
  grid.querySelectorAll('.card-value[data-target]').forEach(el => {
    const t = parseFloat(el.dataset.target);
    if (!isNaN(t)) observeAndCount(el, t, el.dataset.suffix, 1000);
  });

  // Re-init interactive effects on dynamically created cards
  initSpotlightCards();
  initTiltCards();
}

/* ── OUTAGES ─────────────────────────────────────────── */
function renderOutages(outages) {
  const list = document.getElementById('outagesList');
  if (!list) return;

  if (!outages.length) {
    list.innerHTML = `
      <p style="color:var(--muted);font-size:0.875rem;padding:6px 0;">
        No outages in this period. 🎉
      </p>`;
    return;
  }

  list.innerHTML = '';
  // Show newest first, cap at 30
  [...outages].reverse().slice(0, 30).forEach((o, i) => {
    const card = document.createElement('div');
    card.className = 'outage-card fade-up';
    card.style.animationDelay = `${i * 55}ms`;
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-label', `Outage detail — ${o.timestamp}`);
    card.innerHTML = `
      <div>
        <div class="outage-reason">${o.reason || 'Connection lost'}</div>
        <div class="outage-time">${o.timestamp}</div>
      </div>
      <span class="outage-chip">OUTAGE</span>
    `;

    const openDetail = () => openModal(`
      <div class="modal-header">
        <p class="section-label">INCIDENT DETAIL</p>
        <h3>Outage #${o.id}</h3>
      </div>
      <div class="modal-field">
        <div class="field-label">Timestamp</div>
        <div class="field-value">${o.timestamp}</div>
      </div>
      <div class="modal-field">
        <div class="field-label">Reason</div>
        <div class="field-value">${o.reason || 'Unknown — connectivity check failed'}</div>
      </div>
      <div class="modal-field">
        <div class="field-label">Record ID</div>
        <div class="field-value" style="color:var(--muted)">#${o.id}</div>
      </div>
    `);

    card.addEventListener('click', openDetail);
    card.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDetail(); }
    });
    list.appendChild(card);
  });
}

/* ── MAIN RENDER ─────────────────────────────────────── */
function render(data) {
  const { stats, measurements, outages, hourly_avg_download, last_measured } = data;
  const isEmpty = !measurements.length && !outages.length;

  const chartsSection  = document.getElementById('chartsSection');
  const outagesSection = document.getElementById('outagesSection');

  if (isEmpty) {
    renderEmptyState(document.getElementById('statsGrid'));
    destroyCharts();
    if (chartsSection)  chartsSection.style.display  = 'none';
    if (outagesSection) outagesSection.style.display = 'none';
    return;
  }

  if (chartsSection)  chartsSection.style.display  = '';
  if (outagesSection) outagesSection.style.display = '';

  renderHero(stats, last_measured);
  renderStatCards(stats);

  destroyCharts();
  buildSpeedChart(measurements);
  buildLatencyChart(measurements);
  buildHourlyChart(hourly_avg_download);

  renderOutages(outages);

  // Spotlight on static chart cards
  initSpotlightCards();
}

/* ── DATA FETCH ──────────────────────────────────────── */
async function loadData(range) {
  showStatSkeletons(document.getElementById('statsGrid'), 5);

  try {
    const res = await fetch(`/api/data?range=${encodeURIComponent(range)}`);
    if (!res.ok) throw new Error(`Server responded with ${res.status}`);
    const data = await res.json();
    render(data);
  } catch (err) {
    console.error('[NetPulse] Data load error:', err);
    showToast('error', err.message || 'Failed to load data — is the server running?');
  }
}

/* ── BOOT ────────────────────────────────────────────── */
function init() {
  // Scroll progress bar
  initScrollProgress(document.getElementById('scrollProgress'));

  // Modal close handlers
  initModal();

  // Range picker (TubelightNav + MagneticButton)
  const nav = document.getElementById('rangePicker');
  if (nav) {
    initTubelightNav(nav, range => {
      currentRange = range;
      loadData(currentRange);
    });
    // Mark nav buttons as magnetic
    nav.querySelectorAll('button').forEach(b => b.classList.add('magnetic-btn'));
    initMagneticButtons();
  }

  // Initial fetch
  loadData(currentRange);
}

document.addEventListener('DOMContentLoaded', init);
