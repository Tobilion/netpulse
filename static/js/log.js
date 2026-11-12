/* ══════════════════════════════════════════════════════
   NetPulse — log.js
   Log tab: unified history (measurements, failed tests,
   outages) with filters, detail modal and filtered CSV export.
   ══════════════════════════════════════════════════════ */

import { openModal, showToast } from './components.js';
import { formatLatency, formatSpeedText } from './format.js';

const TYPE_LABEL = {
  measurement: 'MEASUREMENT',
  failed_test: 'FAILED TEST',
  outage: 'OUTAGE',
};

export class LogView {
  constructor(mountId = 'logMount') {
    // Resolved in init(): the module loads before the DOM is parsed.
    this._mountId = mountId;
    this._mount = null;
    this._entries = [];
    this._medians = {};
    this._filters = {
      range: '7d', type: 'all', engine: 'all', sort: 'newest',
      min_speed: '', max_speed: '', from: '', to: '', include_flagged: false,
    };
    this._onNewEntries = null;
  }

  init() {
    this._mount = document.getElementById(this._mountId);
    if (!this._mount) return;
    this._mount.innerHTML = `
      <div class="log-filters">
        <label>Period
          <select data-log-filter="range">
            <option value="24h">Last 24h</option>
            <option value="7d" selected>Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="all">All time</option>
            <option value="custom">Custom range</option>
          </select>
        </label>
        <label class="log-custom" hidden>From
          <input type="date" data-log-filter="from" />
          <span>to</span>
          <input type="date" data-log-filter="to" />
        </label>
        <label>Type
          <select data-log-filter="type">
            <option value="all">All</option>
            <option value="measurement">Measurements</option>
            <option value="failed_test">Failed tests</option>
            <option value="outage">Outages</option>
          </select>
        </label>
        <label>Engine
          <select data-log-filter="engine">
            <option value="all">All</option>
            <option value="ookla">Ookla</option>
            <option value="python">speedtest-cli</option>
          </select>
        </label>
        <label>Min Mbps
          <input type="number" step="0.1" min="0" data-log-filter="min_speed" placeholder="0" />
        </label>
        <label>Max Mbps
          <input type="number" step="0.1" min="0" data-log-filter="max_speed" placeholder="∞" />
        </label>
        <label>Sort
          <select data-log-filter="sort">
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="fastest">Fastest first</option>
            <option value="slowest">Slowest first</option>
          </select>
        </label>
        <button type="button" class="log-export" data-log-export>Export CSV</button>
      </div>
      <div class="log-summary" data-log-summary></div>
      <div class="log-list" data-log-list></div>`;

    this._mount.querySelectorAll('[data-log-filter]').forEach((el) => {
      const key = el.dataset.logFilter;
      const handler = () => {
        this._filters[key] = el.value;
        if (key === 'range') {
          const custom = this._mount.querySelector('.log-custom');
          if (custom) custom.hidden = el.value !== 'custom';
        }
        this.load();
      };
      el.addEventListener(el.tagName === 'SELECT' ? 'change' : 'input', handler);
    });
    const exportBtn = this._mount.querySelector('[data-log-export]');
    if (exportBtn) {
      exportBtn.addEventListener('click', () => this.exportCsv());
    }
  }

  setFilters(filters) {
    Object.assign(this._filters, filters || {});
    this.load();
  }

  queryString() {
    const params = new URLSearchParams();
    const f = this._filters;
    params.set('range', f.range);
    if (f.type !== 'all') params.set('type', f.type);
    if (f.engine !== 'all') params.set('engine', f.engine);
    params.set('sort', f.sort);
    if (f.min_speed !== '') params.set('min_speed', f.min_speed);
    if (f.max_speed !== '') params.set('max_speed', f.max_speed);
    if (f.range === 'custom' && f.from) params.set('from', f.from);
    if (f.range === 'custom' && f.to) params.set('to', f.to);
    if (f.include_flagged) params.set('include_flagged', '1');
    return params.toString();
  }

  async load() {
    if (!this._mount) return;
    const list = this._mount.querySelector('[data-log-list]');
    if (list) list.innerHTML = '<p class="muted">Loading…</p>';
    try {
      const res = await fetch(`/api/log?${this.queryString()}`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`Server responded with ${res.status}`);
      const data = await res.json();
      this._entries = data.entries || [];
      this._medians = data.medians || {};
      this.render();
    } catch (err) {
      console.error('[NetPulse] log load error', err);
      if (list) list.innerHTML = '<p class="muted">Could not load the log.</p>';
      showToast('error', err.message || 'Failed to load the log.');
    }
  }

  render() {
    if (!this._mount) return;
    const list = this._mount.querySelector('[data-log-list]');
    const summary = this._mount.querySelector('[data-log-summary]');
    if (summary) {
      summary.textContent = `${this._entries.length} entr${this._entries.length === 1 ? 'y' : 'ies'}`;
    }
    if (!list) return;
    if (!this._entries.length) {
      list.innerHTML = '<p class="muted">Nothing matches these filters.</p>';
      return;
    }
    list.innerHTML = this._entries.map((e) => {
      const speed = e.download_mbps === null || e.download_mbps === undefined
        ? '–' : formatSpeedText(e.download_mbps);
      const latency = e.ping_cloudflare_ms === null || e.ping_cloudflare_ms === undefined
        ? '–' : formatLatency(e.ping_cloudflare_ms);
      return `<button type="button" class="log-row log-${e.kind}${e.flagged ? ' log-flagged' : ''}"
        data-log-id="${e.id}">
        <span class="log-type">${TYPE_LABEL[e.kind] || e.kind}${e.flagged ? ' · FLAGGED' : ''}</span>
        <span class="log-time">${e.timestamp}</span>
        <span class="log-speed">${speed}</span>
        <span class="log-latency">${latency}</span>
        <span class="log-engine">${e.engine || '–'}</span>
      </button>`;
    }).join('');
    list.querySelectorAll('[data-log-id]').forEach((row) => {
      row.addEventListener('click', () => {
        const entry = this._entries.find((e) => String(e.id) === row.dataset.logId
          && e.kind === row.className.match(/log-(measurement|failed_test|outage)/)[1]);
        if (entry) this.openDetail(entry);
      });
    });
  }

  openDetail(entry) {
    const median = entry.engine ? this._medians[entry.engine] : null;
    const comparison = (value) => {
      if (value === null || value === undefined) return '–';
      if (median === null || median === undefined) return '–';
      const diff = value - median;
      const sign = diff >= 0 ? '+' : '';
      return `${sign}${Math.round(diff * 100) / 100} vs median ${formatSpeedText(median)}`;
    };
    const maskIp = (s) => (s || '–').replace(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}/g, '$1•••');
    const field = (label, value) => `
      <div class="modal-field">
        <div class="field-label">${label}</div>
        <div class="field-value">${value}</div>
      </div>`;
    const serverTarget = entry.server_target || entry.server || '–';
    openModal(`
      <div class="modal-header">
        <p class="section-label">${TYPE_LABEL[entry.kind] || entry.kind}</p>
        <h3>${entry.timestamp}</h3>
      </div>
      ${field('Download', entry.download_mbps == null ? '–' : formatSpeedText(entry.download_mbps))}
      ${field('Download vs same-engine median', comparison(entry.download_mbps))}
      ${field('Upload', entry.upload_mbps == null ? '–' : formatSpeedText(entry.upload_mbps))}
      ${field('Measured to', entry.measured_to || '–')}
      ${field('Idle latency — 1.1.1.1', entry.ping_cloudflare_ms == null ? '–' : formatLatency(entry.ping_cloudflare_ms))}
      ${field('Loaded latency — 1.1.1.1', entry.loaded_ms == null ? '–' : formatLatency(entry.loaded_ms))}
      ${field('Jitter — 1.1.1.1', entry.jitter_ms == null ? '–' : formatLatency(entry.jitter_ms))}
      ${field('Packet loss — 1.1.1.1', entry.loss_cloudflare_pct == null ? '–' : `${entry.loss_cloudflare_pct}%`)}
      ${field('Idle latency — test server', entry.server_idle_ms == null ? '–' : formatLatency(entry.server_idle_ms))}
      ${field('Loaded latency — test server', entry.server_loaded_ms == null ? '–' : formatLatency(entry.server_loaded_ms))}
      ${field('Jitter — test server', entry.server_jitter_ms == null ? '–' : formatLatency(entry.server_jitter_ms))}
      ${field('Latency target (server)', serverTarget)}
      ${field('Engine', entry.engine || '–')}
      ${field('Server', entry.server || '–')}
      ${field('Client', maskIp(entry.client))}
      ${entry.flagged ? field('Flagged', entry.flag_reason || 'flagged') : ''}
      ${entry.fallback_reason ? field('Fallback reason', entry.fallback_reason) : ''}
      ${entry.reason ? field('Reason', entry.reason) : ''}
      ${field('Record ID', `#${entry.id}`)}
    `);
  }

  exportCsv() {
    const url = `/api/log.csv?${this.queryString()}`;
    const a = document.createElement('a');
    a.href = url;
    a.download = 'netpulse-log.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast('info', 'Exporting the filtered view.');
  }

  /* Prepend new entries that arrived while the tab was open. */
  prependEntries(newEntries) {
    if (!newEntries || !newEntries.length) return;
    const known = new Set(this._entries.map((e) => `${e.kind}:${e.id}`));
    const fresh = newEntries.filter((e) => !known.has(`${e.kind}:${e.id}`));
    if (!fresh.length) return;
    this._entries = [...fresh, ...this._entries];
    this.render();
  }
}
