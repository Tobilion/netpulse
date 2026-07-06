/* ══════════════════════════════════════════════════════
   NetPulse — charts.js
   Chart.js configuration · gradient fills · styled tooltips
   Signature moment: speed chart draws left → right (1.2s)
   ══════════════════════════════════════════════════════ */

/* Chart.js is loaded as a global from CDN — no import needed */

const C_ACCENT  = '#38bdf8';
const C_ACCENT2 = '#818cf8';
const C_WARN    = '#f87171';
const C_YELLOW  = '#fbbf24';
const C_MUTED   = '#8b93a3';

/* ── GLOBAL CHART.JS DEFAULTS ───────────────────────── */
Chart.defaults.color      = C_MUTED;
Chart.defaults.borderColor = 'rgba(255,255,255,0.04)';
Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
Chart.defaults.font.size   = 12;

/* ── SHARED TOOLTIP STYLE ───────────────────────────── */
const TOOLTIP_DEFAULTS = {
  backgroundColor:  '#12151c',
  titleColor:       '#f2f4f8',
  bodyColor:        '#8b93a3',
  borderColor:      'rgba(255,255,255,0.12)',
  borderWidth:      1,
  padding:          14,
  cornerRadius:     12,
  displayColors:    true,
  boxWidth:         8,
  boxHeight:        8,
  usePointStyle:    true,
  caretSize:        6,
};

/* ── SHARED SCALE OPTIONS ───────────────────────────── */
const BASE_SCALES = {
  x: {
    grid:   { display: false },
    border: { display: false },
    ticks:  { maxTicksLimit: 10, maxRotation: 0, color: C_MUTED, padding: 6 },
  },
  y: {
    beginAtZero: true,
    grid: {
      color:      'rgba(255,255,255,0.04)',
      drawTicks:  false,
    },
    border: { display: false },
    ticks:  { color: C_MUTED, padding: 10 },
  },
};

/* ── BASE LINE OPTIONS ──────────────────────────────── */
const BASE_LINE_OPTIONS = {
  responsive:         true,
  maintainAspectRatio: false,
  interaction:        { mode: 'index', intersect: false },
  plugins: {
    legend:  { labels: { usePointStyle: true, color: C_MUTED, padding: 20 } },
    tooltip: TOOLTIP_DEFAULTS,
  },
  scales: BASE_SCALES,
  elements: {
    point: { radius: 0, hitRadius: 12, hoverRadius: 4 },
    line:  { tension: 0.35, borderWidth: 2 },
  },
};

/* ── GRADIENT HELPER ────────────────────────────────── */
function makeGradient(ctx, colorTop, colorBottom, height = 290) {
  const g = ctx.createLinearGradient(0, 0, 0, height);
  g.addColorStop(0,   colorTop);
  g.addColorStop(1,   colorBottom);
  return g;
}

/* ── CHART INSTANCES ────────────────────────────────── */
let _speedChart   = null;
let _latencyChart = null;
let _hourlyChart  = null;

export function destroyCharts() {
  _speedChart?.destroy();
  _latencyChart?.destroy();
  _hourlyChart?.destroy();
  _speedChart = _latencyChart = _hourlyChart = null;
}

/* ── SPEED CHART (signature: draws left → right) ────── */
export function buildSpeedChart(measurements) {
  const canvas = document.getElementById('speedChart');
  if (!canvas) return;
  _speedChart?.destroy();

  const ctx    = canvas.getContext('2d');
  const dlGrad = makeGradient(ctx, 'rgba(56,189,248,0.28)',  'rgba(56,189,248,0.01)');
  const ulGrad = makeGradient(ctx, 'rgba(129,140,248,0.22)', 'rgba(129,140,248,0.01)');
  const labels = measurements.map(m => m.timestamp.slice(5, 16));

  _speedChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label:           'Download (Mbps)',
          data:            measurements.map(m => m.download_mbps),
          borderColor:     C_ACCENT,
          backgroundColor: dlGrad,
          fill:            true,
        },
        {
          label:           'Upload (Mbps)',
          data:            measurements.map(m => m.upload_mbps),
          borderColor:     C_ACCENT2,
          backgroundColor: ulGrad,
          fill:            true,
        },
      ],
    },
    options: {
      ...BASE_LINE_OPTIONS,
      /* ✦ SIGNATURE MOMENT — chart draws left → right on load */
      animation: {
        duration: 1200,
        easing:   'easeOutQuart',
        onProgress(ctx) {
          // Clip everything to the left of current progress
          const { chart } = ctx;
          const { ctx: c, chartArea } = chart;
          if (!chartArea) return;
          const x = chartArea.left +
            chartArea.width * (ctx.currentStep / ctx.numSteps);
          c.save();
          c.rect(chartArea.left, chartArea.top - 10,
            x - chartArea.left, chartArea.height + 20);
          c.clip();
        },
        onComplete(ctx) {
          ctx.chart.ctx.restore?.();
        },
      },
    },
  });
}

/* ── LATENCY CHART ──────────────────────────────────── */
export function buildLatencyChart(measurements) {
  const canvas = document.getElementById('latencyChart');
  if (!canvas) return;
  _latencyChart?.destroy();

  const ctx     = canvas.getContext('2d');
  const cfGrad  = makeGradient(ctx, 'rgba(251,191,36,0.18)',  'rgba(251,191,36,0.01)');
  const goGrad  = makeGradient(ctx, 'rgba(129,140,248,0.14)', 'rgba(129,140,248,0.01)');
  const labels  = measurements.map(m => m.timestamp.slice(5, 16));

  _latencyChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label:           'Cloudflare (1.1.1.1)',
          data:            measurements.map(m => m.ping_cloudflare_ms),
          borderColor:     C_YELLOW,
          backgroundColor: cfGrad,
          fill:            true,
        },
        {
          label:           'Google (8.8.8.8)',
          data:            measurements.map(m => m.ping_google_ms),
          borderColor:     C_ACCENT2,
          backgroundColor: goGrad,
          fill:            true,
        },
      ],
    },
    options: {
      ...BASE_LINE_OPTIONS,
      animation: { duration: 800, easing: 'easeOutQuart' },
    },
  });
}

/* ── HOURLY BAR CHART ───────────────────────────────── */
export function buildHourlyChart(hourlyData) {
  const canvas = document.getElementById('hourlyChart');
  if (!canvas) return;
  _hourlyChart?.destroy();

  const ctx     = canvas.getContext('2d');
  const barGrad = makeGradient(ctx, 'rgba(56,189,248,0.75)', 'rgba(129,140,248,0.3)');

  _hourlyChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, '0')}:00`),
      datasets: [{
        label:           'Avg Download (Mbps)',
        data:            hourlyData,
        backgroundColor: barGrad,
        borderColor:     C_ACCENT,
        borderWidth:     1,
        borderRadius:    5,
        borderSkipped:   false,
      }],
    },
    options: {
      ...BASE_LINE_OPTIONS,
      plugins: {
        ...BASE_LINE_OPTIONS.plugins,
        legend: { display: false },
      },
      animation: { duration: 700, easing: 'easeOutQuart' },
    },
  });
}
