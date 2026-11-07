/* ══════════════════════════════════════════════════════
   NetPulse — format.js
   Single source of truth for all measurement units.
   Speeds (Mbps input): kbps < 1, Mbps 1-999, Gbps >= 1000.
   Latency/jitter: ms. Loss: %. Never show Mbps for latency.
   ══════════════════════════════════════════════════════ */

function isMissing(v) {
  return v === null || v === undefined || (typeof v === 'number' && !isFinite(v));
}

function trimNum(n, decimals) {
  if (decimals === 0) return String(Math.round(n));
  const s = n.toFixed(decimals);
  // 12.0 -> "12", 12.50 -> "12.5"
  return s.includes('.') ? s.replace(/\.?0+$/, '') : s;
}

/** Speed in Mbps -> { value, unit, text }. Null-safe: returns '–'. */
export function formatSpeed(mbps) {
  if (isMissing(mbps)) return { value: '–', unit: '', text: '–' };
  const v = Number(mbps);
  if (v < 1) {
    const kbps = Math.max(0, v * 1000);
    const value = kbps < 10 ? trimNum(kbps, 1) : trimNum(kbps, 0);
    return { value, unit: 'kbps', text: `${value} kbps` };
  }
  if (v < 1000) {
    const value = v < 10 ? trimNum(v, 2) : trimNum(v, 1);
    return { value, unit: 'Mbps', text: `${value} Mbps` };
  }
  const gbps = v / 1000;
  const value = gbps < 10 ? trimNum(gbps, 2) : trimNum(gbps, 1);
  return { value, unit: 'Gbps', text: `${value} Gbps` };
}

export function formatSpeedText(mbps) {
  return formatSpeed(mbps).text;
}

export function formatSpeedValue(mbps) {
  return formatSpeed(mbps).value;
}

export function formatSpeedUnit(mbps) {
  return formatSpeed(mbps).unit;
}

/** Latency/jitter in ms. */
export function formatLatency(ms) {
  if (isMissing(ms)) return '–';
  const v = Number(ms);
  const value = v < 10 ? trimNum(v, 1) : trimNum(v, 0);
  return `${value} ms`;
}

export function formatLatencyValue(ms) {
  if (isMissing(ms)) return '–';
  const v = Number(ms);
  return v < 10 ? trimNum(v, 1) : trimNum(v, 0);
}

/** Packet loss in percent. */
export function formatLoss(pct) {
  if (isMissing(pct)) return '–';
  return `${trimNum(Number(pct), 1)}%`;
}

/** Generic percent (uptime, % of plan). */
export function formatPercent(pct, decimals = 1) {
  if (isMissing(pct)) return '–';
  return `${trimNum(Number(pct), decimals)}%`;
}

/** For chart axis ticks: keep labels compact (e.g. 400 kbps, 1.2 Gbps). */
export function formatSpeedTick(mbps) {
  if (isMissing(mbps)) return '–';
  return formatSpeed(mbps).text;
}

export function formatLatencyTick(ms) {
  return formatLatency(ms);
}
