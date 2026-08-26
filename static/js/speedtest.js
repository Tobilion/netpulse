/* ══════════════════════════════════════════════════════
   NetPulse — speedtest.js
   SpeedTestGauge: Fast.com-style live speed test widget
   ══════════════════════════════════════════════════════ */

import { showToast } from './components.js';

const R       = 104;
const CIRCUMF = 2 * Math.PI * R;
const POLL_MS = 500;

const ICONS = {
  play:   `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.53.85l10.2-6.5a1 1 0 0 0 0-1.7L9.53 4.65A1 1 0 0 0 8 5.5z"/></svg>`,
  stop:   `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>`,
  retest: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>`,
};

function fmtVal(v, suffix) {
  if (v === null || v === undefined) return '–';
  const n = Math.round(v * 10) / 10;
  return `${n}${suffix}`;
}

export class SpeedTestGauge {
  constructor(mountEl, { onComplete } = {}) {
    this._mount       = mountEl;
    this._onComplete  = onComplete;
    this._state       = 'idle';
    this._shown       = 0;
    this._target      = 0;
    this._unloaded    = null;
    this._loaded      = null;
    this._rafId       = null;
    this._pollTimer   = null;
    this._stopPolling = true;
    this._starting    = false;
  }

  render() {
    if (!this._mount) return;
    this._mount.innerHTML = `
      <article class="live-test-card spotlight-card" role="region" aria-label="On-demand internet speed test">
        <div class="gauge">
          <svg class="gauge-svg" viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <defs>
              <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%"   stop-color="#38bdf8"/>
                <stop offset="100%" stop-color="#818cf8"/>
              </linearGradient>
              <filter id="gaugeGlow" x="-40%" y="-40%" width="180%" height="180%">
                <feGaussianBlur stdDeviation="5" result="blur"/>
                <feMerge>
                  <feMergeNode in="blur"/>
                  <feMergeNode in="SourceGraphic"/>
                </feMerge>
              </filter>
            </defs>
            <circle class="gauge-track" cx="120" cy="120" r="${R}"/>
            <circle class="gauge-fill" cx="120" cy="120" r="${R}"
              stroke="url(#gaugeGrad)" filter="url(#gaugeGlow)"
              stroke-dasharray="${CIRCUMF.toFixed(2)}"
              stroke-dashoffset="${CIRCUMF.toFixed(2)}"/>
          </svg>
          <div class="gauge-center">
            <div class="gauge-value" id="gaugeValue">0</div>
            <div class="gauge-unit">Mbps</div>
            <div class="gauge-status" id="gaugeStatus" aria-live="polite">Ready to test your connection</div>
            <button class="gauge-action magnetic-btn" id="gaugeAction" type="button" aria-label="Start speed test">
              ${ICONS.play}<span>Start Test</span>
            </button>
          </div>
        </div>
        <div class="results-grid" id="gaugeResults" hidden></div>
      </article>
    `;

    this._card       = this._mount.querySelector('.live-test-card');
    this._valueEl    = this._mount.querySelector('#gaugeValue');
    this._statusEl   = this._mount.querySelector('#gaugeStatus');
    this._actionBtn  = this._mount.querySelector('#gaugeAction');
    this._fillEl     = this._mount.querySelector('.gauge-fill');
    this._resultsEl  = this._mount.querySelector('#gaugeResults');

    this._actionBtn.addEventListener('click', () => {
      if (this._state === 'testing') this.stop();
      else this.start();
    });
  }

  /* Public helpers (used by the internal poll loop) ── */

  start() {
    if (this._state === 'testing' || this._starting) return;
    this._starting = true;
    this._statusEl.textContent = 'Starting…';

    fetch('/api/speedtest/start', { method: 'POST' })
      .then(async res => {
        const body = await res.json().catch(() => null);
        if (!res.ok) {
          showToast('error', (body && body.error) || `Server responded with ${res.status}`);
          this.#resetToIdle();
          return;
        }
        this.#setState('testing');
        this._stopPolling = false;
        this.#beginCounting();
        this.#pollOnce();
      })
      .catch(() => {
        showToast('error', 'Could not start the test — is the server running?');
        this.#resetToIdle();
      })
      .finally(() => { this._starting = false; });
  }

  stop() {
    this.#stopPolling();
    fetch('/api/speedtest/cancel', { method: 'POST' }).catch(() => {});
    showToast('info', 'Speed test cancelled.');
    this.#resetToIdle();
  }

  updateDownload(speed) {
    this._target = speed;
  }

  updateUpload(speed) {
    this._target = speed;
  }

  updateLatency(unloaded, loaded) {
    this._unloaded = unloaded;
    this._loaded = loaded;
  }

  complete(data) {
    this.#stopPolling();
    this._target = (data.download_mbps != null) ? data.download_mbps : 0;
    this.updateLatency(data.unloaded_ms, data.loaded_ms);
    this.#setState('done');
    this.#beginCounting();
    this.#renderResults(data);
    if (this._onComplete) this._onComplete(data);
  }

  /* Internals ────────────────────────────────────────── */

  #tick = () => {
    this._shown += (this._target - this._shown) * 0.16;
    if (Math.abs(this._target - this._shown) < 0.05) this._shown = this._target;
    this._valueEl.textContent = Math.round(this._shown).toLocaleString('en-US');
    if (this._state !== 'testing' && this._state !== 'done') { this._rafId = null; return; }
    if (this._state === 'done' && this._shown === this._target) { this._rafId = null; return; }
    this._rafId = requestAnimationFrame(this.#tick);
  };

  #beginCounting() {
    if (this._rafId !== null) return;
    this._rafId = requestAnimationFrame(this.#tick);
  }

  #setState(state) {
    this._state = state;
    this._fillEl.classList.remove('gauge-pulsing');

    if (state === 'idle') {
      this._fillEl.style.strokeDashoffset = CIRCUMF.toFixed(2);
      this._valueEl.textContent = '0';
      this._statusEl.textContent = 'Ready to test your connection';
      this._actionBtn.innerHTML = `${ICONS.play}<span>Start Test</span>`;
      this._actionBtn.setAttribute('aria-label', 'Start speed test');
      this._resultsEl.hidden = true;
      this._resultsEl.classList.remove('results-reveal');
      this._card.classList.remove('gauge-done');
    } else if (state === 'testing') {
      this._fillEl.classList.add('gauge-pulsing');
      this._statusEl.textContent = 'Testing download…';
      this._actionBtn.innerHTML = `${ICONS.stop}<span>Stop</span>`;
      this._actionBtn.setAttribute('aria-label', 'Stop speed test');
      this._resultsEl.hidden = true;
      this._card.classList.remove('gauge-done');
    } else if (state === 'done') {
      this._fillEl.style.strokeDashoffset = '0';
      this._statusEl.textContent = 'Your internet speed is';
      this._actionBtn.innerHTML = `${ICONS.retest}<span>Re-test</span>`;
      this._actionBtn.setAttribute('aria-label', 'Run speed test again');
      this._card.classList.add('gauge-done');
    }
  }

  #resetToIdle() {
    this._shown = 0;
    this._target = 0;
    this.#setState('idle');
  }

  #simulate(current, kind) {
    const spread = kind === 'download' ? 14 : 3.5;
    const min    = kind === 'download' ? 5 : 1;
    const max    = kind === 'download' ? 500 : 90;
    const next   = current + (Math.random() - 0.45) * spread;
    return Math.max(min, Math.min(max, next));
  }

  #pollOnce() {
    if (this._stopPolling) return;
    fetch('/api/speedtest/status')
      .then(async res => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json();
      })
      .then(job => this.#handleStatus(job))
      .catch(() => { /* transient fetch error — keep polling */ })
      .finally(() => {
        if (!this._stopPolling) this._pollTimer = setTimeout(() => this.#pollOnce(), POLL_MS);
      });
  }

  #stopPolling() {
    this._stopPolling = true;
    if (this._pollTimer) { clearTimeout(this._pollTimer); this._pollTimer = null; }
  }

  #handleStatus(job) {
    if (job.running) {
      if (job.phase === 'latency') {
        this._statusEl.textContent = 'Measuring latency…';
      } else if (job.phase === 'download') {
        this._statusEl.textContent = 'Testing download…';
        this.updateDownload(this.#simulate(this._target, 'download'));
      } else if (job.phase === 'upload') {
        this._statusEl.textContent = 'Testing upload…';
        this.updateUpload(this.#simulate(this._target, 'upload'));
      }
      if (job.unloaded_ms != null || job.loaded_ms != null) {
        this.updateLatency(job.unloaded_ms, job.loaded_ms);
      }
      return;
    }

    if (job.phase === 'done') {
      this.complete(job);
    } else if (job.phase === 'error') {
      this.#stopPolling();
      showToast('error', job.error || 'Speed test failed.');
      this.#resetToIdle();
    } else {
      // idle / cancelled without a result
      this.#stopPolling();
      this.#resetToIdle();
    }
  }

  #renderResults(data) {
    const rows = [
      { label: 'Unloaded Latency', value: fmtVal(this._unloaded, ' ms') },
      { label: 'Loaded Latency',   value: fmtVal(this._loaded, ' ms') },
      { label: 'Upload Speed',     value: fmtVal(data.upload_mbps, ' Mbps') },
      { label: 'Client',           value: data.client || '–', full: true },
      { label: 'Server',           value: data.server || '–', full: true },
    ];
    this._resultsEl.innerHTML = rows.map(r => `
      <div class="result-item${r.full ? ' result-item-full' : ''}">
        <div class="result-label">${r.label.toUpperCase()}</div>
        <div class="result-value">${r.value}</div>
      </div>
    `).join('');
    this._resultsEl.hidden = false;
    this._resultsEl.classList.remove('results-reveal');
    void this._resultsEl.offsetWidth; // restart the slide-down animation
    this._resultsEl.classList.add('results-reveal');
  }
}