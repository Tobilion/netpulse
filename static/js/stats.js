// Stat cards rendering (engine-aware, format.js units).
import {
  initSpotlightCards, initTiltCards, observeAndCount,
} from './components.js';
import { formatLatency, formatPercent, formatSpeedText } from './format.js';

export function renderStatCards(stats, currentEngine) {
  const grid = document.getElementById('statsGrid');
  if (!grid) return;
  const meta = document.getElementById('engineMeta');
  if (meta) {
    const n = stats.sample_count ?? '–';
    const sel = currentEngine;
    const eng = stats.engine || '–';
    meta.textContent = sel === 'all'
      ? `All engines · ${n} samples (latest engine ${eng})`
      : `Filter ${sel === 'ookla' ? 'Ookla' : 'speedtest-cli'} · ${n} samples`;
  }
  grid.innerHTML = '';
  const CARDS = [
    { label: 'UPTIME', value: stats.uptime_pct,
      format: (v) => formatPercent(v, 1),
      cls: stats.uptime_pct === null ? '' : stats.uptime_pct >= 99 ? 'good' : stats.uptime_pct < 95 ? 'bad' : 'accent' },
    { label: 'AVG DOWNLOAD', value: stats.avg_download_mbps, format: (v) => formatSpeedText(v), cls: 'accent' },
    { label: 'AVG UPLOAD', value: stats.avg_upload_mbps, format: (v) => formatSpeedText(v), cls: '' },
    { label: 'AVG IDLE LATENCY (1.1.1.1)', value: stats.avg_ping_ms, format: (v) => formatLatency(v), cls: '' },
    { label: 'OUTAGES', value: stats.outage_count, format: (v) => String(Math.round(v)), cls: stats.outage_count > 0 ? 'bad' : 'good' },
  ];
  const formatters = new Map();
  CARDS.forEach((c, i) => {
    const div = document.createElement('div');
    div.className = 'stat-card spotlight-card tilt-card fade-up';
    div.style.animationDelay = `${i * 80}ms`;
    const hasValue = c.value !== null && c.value !== undefined;
    div.innerHTML = `
      <div class="card-label">${c.label}</div>
      <div class="card-value ${c.cls}" data-target="${hasValue ? c.value : ''}">
        ${hasValue ? c.format(0) : '–'}
      </div>`;
    grid.appendChild(div);
    formatters.set(div.querySelector('.card-value'), c.format);
  });
  grid.querySelectorAll('.card-value[data-target]').forEach((el) => {
    const t = parseFloat(el.dataset.target);
    if (!isNaN(t)) observeAndCount(el, t, '', 1000, formatters.get(el) || null);
  });
  initSpotlightCards();
  initTiltCards();
}
