/* ══════════════════════════════════════════════════════
   NetPulse — charts.js
   Chart.js configuration · gradient fills · styled tooltips
   Signature moment: speed chart draws left → right (1.2s)
   ══════════════════════════════════════════════════════ */

/* Chart.js is loaded as a global from CDN — no import needed */
import { formatLatency, formatSpeedText } from './format.js';

/* Theme-aware palette (built fresh per chart so light mode re-themes). */
function palette() {
  const light = document.documentElement.getAttribute('data-theme') === 'light';
  return light
    ? { accent: '#075985', accent2: '#5B21B6', warn: '#B91C1C',
        yellow: '#B45309', muted: '#5E574D', grid: 'rgba(43,38,32,0.07)',
        bg: '#FBF8F1', title: '#2B2620', border: 'rgba(43,38,32,0.2)' }
    : { accent: '#38bdf8', accent2: '#818cf8', warn: '#f87171',
        yellow: '#fbbf24', muted: '#8b93a3', grid: 'rgba(255,255,255,0.04)',
        bg: '#12151c', title: '#f2f4f8', border: 'rgba(255,255,255,0.12)' };
}

// const C_ACCENT  = '#38bdf8';
// const C_ACCENT2 = '#818cf8';
const C_WARN    = '#f87171';
// const C_YELLOW  = '#fbbf24';
// const C_MUTED   = '#8b93a3';

function applyDefaults() {
  const c = palette();
  Chart.defaults.color = c.muted;
  Chart.defaults.borderColor = c.grid;
  Chart.defaults.font.family = "'Inter', system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  return c;
}

function tooltipDefaults() {
  const c = palette();
  return {
    backgroundColor: c.bg,
    titleColor: c.title,
    bodyColor: c.muted,
    borderColor: c.border,
    borderWidth: 1,
    padding: 14,
    cornerRadius: 12,
    displayColors: true,
    boxWidth: 8,
    boxHeight: 8,
    usePointStyle: true,
    caretSize: 6,
  };
}

/* ── SHARED SCALE OPTIONS (built fresh per chart) ───── */
function baseScales() {
  const c = applyDefaults();
  return {
    x: {
      grid: { display: false },
      border: { display: false },
      ticks: { maxTicksLimit: 10, maxRotation: 0, color: c.muted, padding: 6 },
    },
    y: {
      beginAtZero: true,
      grid: { color: c.grid, drawTicks: false },
      border: { display: false },
      ticks: { color: c.muted, padding: 10 },
    },
  };
}

/* ── BASE LINE OPTIONS (built fresh per chart) ──────── */
function baseLineOptions() {
  const c = applyDefaults();
  const scales = baseScales();
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { labels: { usePointStyle: true, color: c.muted, padding: 20 } },
      tooltip: tooltipDefaults(),
    },
    scales,
    elements: {
      point: { radius: 0, hitRadius: 12, hoverRadius: 4 },
      line: { tension: 0.35, borderWidth: 2 },
    },
  };
}

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

/* Marks where the measurement engine changed (e.g. Python -> Ookla). */
const engineChangePlugin = {
  id: 'engineChange',
  afterDatasetsDraw(chart) {
    const { ctx, chartArea } = chart;
    if (!chartArea) return;
    const rows = chart.data._measurements || [];
    ctx.save();
    ctx.strokeStyle = 'rgba(248,113,113,0.5)';
    ctx.setLineDash([4, 4]);
    ctx.lineWidth = 1;
    for (let i = 1; i < rows.length; i++) {
      if ((rows[i].engine || null) !== (rows[i - 1].engine || null)) {
        const x = chart.scales.x.getPixelForValue(i);
        ctx.beginPath();
        ctx.moveTo(x, chartArea.top);
        ctx.lineTo(x, chartArea.bottom);
        ctx.stroke();
        if (rows[i].engine) {
          ctx.fillStyle = 'rgba(248,113,113,0.8)';
          ctx.font = '600 10px Inter, sans-serif';
          ctx.fillText(`engine: ${rows[i].engine}`, x + 4, chartArea.top + 10);
        }
      }
    }
    ctx.restore();
  },
};

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
      _measurements: measurements,
      datasets: [
        {
          label:           'Download',
          data:            measurements.map(m => m.download_mbps),
          borderColor:     palette().accent,
          backgroundColor: dlGrad,
          fill:            true,
        },
        {
          label:           'Upload',
          data:            measurements.map(m => m.upload_mbps),
          borderColor:     palette().accent2,
          backgroundColor: ulGrad,
          fill:            true,
        },
      ],
    },
    options: {
      ...baseLineOptions(),
      plugins: {
        ...baseLineOptions().plugins,
        tooltip: {
          ...tooltipDefaults(),
          callbacks: {
            label: (item) =>
              ` ${item.dataset.label}: ${formatSpeedText(item.parsed.y)}`,
          },
        },
      },
      scales: {
        ...baseScales(),
        y: {
          ...baseScales().y,
          ticks: {
            ...baseScales().y.ticks,
            callback: (v) => formatSpeedText(v),
          },
        },
      },
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
    plugins: [engineChangePlugin],
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
      _measurements: measurements,
      datasets: [
        {
          label:           'Cloudflare (1.1.1.1)',
          data:            measurements.map(m => m.ping_cloudflare_ms),
          borderColor:     palette().yellow,
          backgroundColor: cfGrad,
          fill:            true,
        },
        {
          label:           'Google (8.8.8.8)',
          data:            measurements.map(m => m.ping_google_ms),
          borderColor:     palette().accent2,
          backgroundColor: goGrad,
          fill:            true,
        },
      ],
    },
    options: {
      ...baseLineOptions(),
      plugins: {
        ...baseLineOptions().plugins,
        tooltip: {
          ...tooltipDefaults(),
          callbacks: {
            label: (item) =>
              ` ${item.dataset.label}: ${formatLatency(item.parsed.y)}`,
          },
        },
      },
      scales: {
        ...baseScales(),
        y: {
          ...baseScales().y,
          ticks: {
            ...baseScales().y.ticks,
            callback: (v) => formatLatency(v),
          },
        },
      },
      animation: { duration: 800, easing: 'easeOutQuart' },
    },
    plugins: [engineChangePlugin],
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
        label:           'Avg Download',
        data:            hourlyData,
        backgroundColor: barGrad,
        borderColor:     palette().accent,
        borderWidth:     1,
        borderRadius:    5,
        borderSkipped:   false,
      }],
    },
    options: {
      ...baseLineOptions(),
      plugins: {
        ...baseLineOptions().plugins,
        legend: { display: false },
        tooltip: {
          ...tooltipDefaults(),
          callbacks: {
            label: (item) => ` ${formatSpeedText(item.parsed.y)}`,
          },
        },
      },
      scales: {
        ...baseScales(),
        y: {
          ...baseScales().y,
          ticks: {
            ...baseScales().y.ticks,
            callback: (v) => formatSpeedText(v),
          },
        },
      },
      animation: { duration: 700, easing: 'easeOutQuart' },
    },
  });
}
