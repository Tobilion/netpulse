/* ══════════════════════════════════════════════════════
   NetPulse — insights.js
   Health score, compatibility dots, % of plan, worse-than-usual
   chip and the uptime heatmap (Trends tab).
   ══════════════════════════════════════════════════════ */

import { formatLatency, formatPercent, formatSpeedText } from './format.js';

const HEALTH_FORMULA = [
  'Reliability (35%): 60% uptime in the window + 40% of a lightly-penalised failed-test rate.',
  'Speed (30%): download speed against your plan speed, or against your own same-engine median when no plan is set.',
  'Idle latency (20%): scaled against NetPulse latency bands (excellent ≤30 ms, good ≤50 ms, fair ≤100 ms).',
  'Loss & jitter (15%): mean of scaled packet loss and scaled jitter.',
  'Components with no data are skipped and the remaining weights are re-normalised.',
].join(' ');

export function renderHealth(container, health) {
  if (!container) return;
  if (!health) { container.innerHTML = ''; return; }
  const band = health.verdict || 'poor';
  const components = health.components || {};
  const row = (label, key) => {
    const v = components[key];
    return `<div class="health-row">
      <span class="health-row-label">${label}</span>
      <span class="health-row-value">${v === null || v === undefined ? '–' : Math.round(v)}</span>
    </div>`;
  };
  container.innerHTML = `
    <div class="health-head">
      <div class="health-score health-${band}">
        <span class="health-score-value">${Math.round(health.score ?? 0)}</span>
        <span class="health-score-unit">/100</span>
      </div>
      <div class="health-verdict">
        <div class="health-verdict-label">${health.label || '—'}</div>
        <div class="health-weights">${(health.missing || []).length
          ? `Missing: ${health.missing.join(', ')}`
          : 'All components available'}</div>
      </div>
      <button type="button" class="health-info" title="How this is calculated"
        aria-label="How this is calculated" data-health-info>ⓘ</button>
    </div>
    <div class="health-rows">
      ${row('Reliability', 'reliability')}
      ${row('Speed', 'speed')}
      ${row('Idle latency', 'latency')}
      ${row('Loss & jitter', 'stability')}
    </div>
    <p class="health-formula" hidden>${HEALTH_FORMULA}</p>
  `;
  const info = container.querySelector('[data-health-info]');
  const formula = container.querySelector('.health-formula');
  if (info && formula) {
    info.addEventListener('click', () => { formula.hidden = !formula.hidden; });
  }
}

export function renderCompatibility(container, items) {
  if (!container) return;
  if (!items || !items.length) { container.innerHTML = ''; return; }
  container.innerHTML = items.map((item) => `
    <div class="compat-item compat-${item.status}" title="${item.detail || ''} — source: ${item.source}">
      <span class="compat-dot" aria-hidden="true"></span>
      <span class="compat-label">${item.label}</span>
      <span class="compat-status">${item.status}</span>
    </div>
  `).join('');
}

export function renderPlanInfo(container, plan) {
  if (!container) return;
  if (!plan || !plan.plan_speed_mbps) {
    container.innerHTML = '<span class="muted">No plan speed set — add it in Settings to see % of plan.</span>';
    return;
  }
  const pct = plan.pct_of_plan;
  container.innerHTML = `
    <span class="plan-line">
      <span class="plan-label">% of plan</span>
      <span class="plan-value">${pct === null || pct === undefined ? '–' : formatPercent(pct, 0)}</span>
      <span class="plan-detail">of ${formatSpeedText(plan.plan_speed_mbps)}</span>
    </span>`;
}

export function renderWorseChip(container, worse) {
  if (!container) return;
  if (!worse || !worse.is_worse) { container.hidden = true; container.innerHTML = ''; return; }
  container.hidden = false;
  container.innerHTML = `Worse than usual — ${formatSpeedText(worse.download_mbps)} is under
    ${Math.round((worse.ratio ?? 0.5) * 100)}% of your ${worse.window_days}-day median
    (${formatSpeedText(worse.median_mbps)})`;
}

export function renderHeatmap(container, days) {
  if (!container) return;
  if (!days || !days.length) { container.innerHTML = '<p class="muted">No data yet.</p>'; return; }
  const cells = days.map((d) => {
    const title = d.status === 'no_data'
      ? `${d.date} — no data`
      : `${d.date} — ${d.uptime_pct}% uptime (${d.measurements} measurements, ${d.outages} outages)`;
    return `<div class="heat-cell heat-${d.status}" title="${title}" data-date="${d.date}"
      aria-label="${title}"></div>`;
  }).join('');
  container.innerHTML = `
    <div class="heat-grid">${cells}</div>
    <div class="heat-legend">
      <span><i class="heat-cell heat-excellent"></i>100%</span>
      <span><i class="heat-cell heat-good"></i>95–99%</span>
      <span><i class="heat-cell heat-fair"></i>80–95%</span>
      <span><i class="heat-cell heat-poor"></i>&lt;80%</span>
      <span><i class="heat-cell heat-no_data"></i>no data</span>
    </div>`;
}

export function formatLossCell(pct) {
  return pct === null || pct === undefined ? '–' : formatPercent(pct, 1);
}

export { HEALTH_FORMULA };
