/* ══════════════════════════════════════════════════════
   NetPulse — speedtest.js
   SpeedTestGauge: needle gauge driven only by real SSE samples.
   Live samples drive the needle (lightly smoothed); the final
   stored value is what is shown once the test completes.
   ══════════════════════════════════════════════════════ */

import { showToast } from './components.js';
import {
  formatLatency,
  formatLatencyValue,
  formatSpeed,
} from './format.js';

import { CX, CY, arcPath, mbpsToAngle, tickMarkup } from './gauge-scale.js';

const ICONS = {
  play:   `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.53.85l10.2-6.5a1 1 0 0 0 0-1.7L9.53 4.65A1 1 0 0 0 8 5.5z"/></svg>`,
  stop:   `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>`,
  retest: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>`,
};

export class SpeedTestGauge {
  constructor(mountEl, { onComplete } = {}) {
    this._mount = mountEl;
    this._onComplete = onComplete;
    this._state = 'idle';
    this._phase = 'idle';
    this._shownMbps = 0;
    this._targetMbps = 0;
    this._livePing = null;
    this._unloaded = null;
    this._loaded = null;
    this._rafId = null;
    this._source = null; // EventSource or null when polling
    this._pollTimer = null;
    this._pollFails = 0;
    this._stopPolling = true;
    this._starting = false;
  }

  render() {
    if (!this._mount) return;
    this._mount.innerHTML = `
      <article class="live-test-card spotlight-card" role="region" aria-label="On-demand internet speed test">
        <div class="gauge">
          <svg class="gauge-svg" viewBox="0 0 360 190" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <defs>
              <linearGradient id="gaugeGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                <stop offset="0%" stop-color="#38bdf8"/>
                <stop offset="100%" stop-color="#34d399"/>
              </linearGradient>
            </defs>
            <path class="gauge-arc-track" d="${arcPath(90)}" />
            <path class="gauge-arc-fill" id="gaugeFill" d="${arcPath(-90)}" />
            ${tickMarkup()}
            <line class="gauge-needle" id="gaugeNeedle" x1="${CX}" y1="${CY}" x2="${CX}" y2="${CY - 118}" />
            <circle class="gauge-hub" cx="${CX}" cy="${CY}" r="10" />
          </svg>
          <div class="gauge-center">
            <div class="gauge-phase" id="gaugePhase">READY</div>
            <div class="gauge-value" id="gaugeValue">0</div>
            <div class="gauge-unit" id="gaugeUnit">Mbps</div>
            <div class="gauge-live-ping" id="gaugeLivePing"></div>
            <div class="gauge-status" id="gaugeStatus" aria-live="polite">Ready to test your connection</div>
            <div class="gauge-warn" id="gaugeWarn" hidden></div>
            <div class="gauge-btn-row">
              <button class="gauge-action magnetic-btn" id="gaugeAction" type="button" aria-label="Start speed test">
                ${ICONS.play}<span>Start Test</span>
              </button>
              <button class="gauge-reset" id="gaugeReset" type="button" hidden>Reset</button>
            </div>
          </div>
        </div>
        <div class="results-grid" id="gaugeResults" hidden></div>
      </article>
    `;

    this._card = this._mount.querySelector('.live-test-card');
    this._valueEl = this._mount.querySelector('#gaugeValue');
    this._unitEl = this._mount.querySelector('#gaugeUnit');
    this._phaseEl = this._mount.querySelector('#gaugePhase');
    this._livePingEl = this._mount.querySelector('#gaugeLivePing');
    this._statusEl = this._mount.querySelector('#gaugeStatus');
    this._actionBtn = this._mount.querySelector('#gaugeAction');
    this._needleEl = this._mount.querySelector('#gaugeNeedle');
    this._fillEl = this._mount.querySelector('#gaugeFill');
    this._resultsEl = this._mount.querySelector('#gaugeResults');
    this._resetBtn = this._mount.querySelector('#gaugeReset');
    this._warnEl = this._mount.querySelector('#gaugeWarn');

    this._actionBtn.addEventListener('click', () => {
      if (this._state === 'testing') this.stop();
      else this.start();
    });
    if (this._resetBtn) {
      this._resetBtn.addEventListener('click', () => this.reset());
    }
    this.#setNeedle(0);
    this.#syncOnLoad();
    this.#demoIfRequested();
  }

  /* Dev-only: ?gaugeDemo=1 drives the gauge from a slider, no real test. */
  #demoIfRequested() {
    if (!new URLSearchParams(window.location.search).has('gaugeDemo')) return;
    const demo = document.createElement('div');
    demo.className = 'gauge-warn';
    demo.style.marginTop = '10px';
    demo.innerHTML = '<label for="gaugeDemoRange">Gauge demo (dev)</label> ';
    const range = document.createElement('input');
    range.type = 'range';
    range.id = 'gaugeDemoRange';
    range.min = '0';
    range.max = '1000';
    range.step = '0.1';
    range.value = '0';
    range.addEventListener('input', () => {
      const mbps = Number(range.value) / 1; // 0-1000 Mbps
      this.#setState('testing');
      this._phase = 'download';
      this._targetMbps = mbps;
      this._shownMbps = mbps;
      const parts = formatSpeed(mbps);
      this._valueEl.textContent = parts.value;
      this._unitEl.textContent = parts.unit;
      this._phaseEl.textContent = 'DEMO';
      this._statusEl.textContent = `${formatSpeed(mbps).text} (demo — not a measurement)`;
      this.#setNeedle(mbps);
    });
    demo.appendChild(range);
    this._mount.appendChild(demo);
  }

  reset() {
    fetch('/api/speedtest/reset', { method: 'POST' }).catch(() => {});
    this.#stopPolling();
    this.#resetToIdle();
  }

  /* On load, attach to a running job instead of showing stale READY. */
  #syncOnLoad() {
    this.#syncToBackend();
  }

  async start() {
    if (this._state === 'testing' || this._starting) return;
    this._starting = true;
    this._statusEl.textContent = 'Starting…';
    let res;
    // Step 1: network. Failures here are server-unreachable.
    try {
      res = await fetch('/api/speedtest/start', { method: 'POST' });
    } catch (err) {
      console.error('[NetPulse] start network failure', err);
      showToast('error', 'Server unreachable — could not start the test. Is serve running?');
      this.#syncToBackend();
      this._starting = false;
      return;
    }
    let body = null;
    try { body = await res.json().catch(() => null); } catch (err) {
      console.error('[NetPulse] start response parse error', err);
      showToast('error', 'Unexpected UI error starting the test. State synced to server.');
      this.#syncToBackend();
      this._starting = false;
      return;
    }
    // Step 2: state. 409 means a job is already running — attach, never reset.
    try {
      if (res.status === 409) {
        showToast('info', 'A test is already running — attached to it.');
      } else if (!res.ok) {
        showToast('error', (body && body.error) || `Server error ${res.status} starting the test.`);
        this.#syncToBackend();
        this._starting = false;
        return;
      }
      this.#setState('testing');
      this._phase = 'latency';
      this.#openStream();
    } catch (err) {
      console.error('[NetPulse] unexpected UI error after start', err);
      showToast('error', 'Unexpected UI error after start. State synced to server.');
      this.#syncToBackend();
    } finally {
      this._starting = false;
    }
  }

  /* Fetch backend truth and mirror it — used after any start confusion. */
  #syncToBackend() {
    fetch('/api/speedtest/status')
      .then((r) => (r.ok ? r.json() : null))
      .then((job) => {
        if (!job) { this.#resetToIdle(); return; }
        if (job.running) {
          this.#setState('testing');
          this.#openStream();
        } else if (job.phase === 'done') {
          this.complete(job);
        } else if (job.phase === 'failed') {
          this.#fail(job);
        } else if (job.phase === 'error') {
          this.#fail(job);
        } else {
          this.#resetToIdle();
          this._resetBtn.hidden = false;
        }
      })
      .catch((err) => {
        console.error('[NetPulse] sync failed', err);
        this.#resetToIdle();
      });
  }

  stop() {
    fetch('/api/speedtest/cancel', { method: 'POST' }).catch(() => {});
    if (this._source) { this._source.close(); this._source = null; }
    if (this._pollTimer) { clearTimeout(this._pollTimer); this._pollTimer = null; }
    showToast('info', 'Cancelling… waiting for server to finish…');
    this._stopPolling = false;
    this.#pollOnce();
  }

  updateDownload(speed) { this._targetMbps = speed; }
  updateUpload(speed) { this._targetMbps = speed; }
  updateLatency(unloaded, loaded) {
    this._unloaded = unloaded;
    this._loaded = loaded;
  }

  complete(data) {
    this.#stopPolling();
    const final = (data.download_mbps != null) ? data.download_mbps : 0;
    this._targetMbps = final;
    this._shownMbps = final;
    this.updateLatency(data.unloaded_ms, data.loaded_ms);
    this.#setState('done');
    this.#renderResults(data);
    if (this._onComplete) this._onComplete(data);
  }

  /* ── Internals ────────────────────────────────────────── */

  #openStream() {
    this._stopPolling = false;
    if (typeof EventSource !== 'undefined') {
      try {
        const source = new EventSource('/api/speedtest/stream');
        this._source = source;
        source.onmessage = (ev) => {
          let job = null;
          try { job = JSON.parse(ev.data); } catch (err) {
            console.error('[NetPulse] stream parse error', err);
            return;
          }
          try {
            this.#handleStatus(job);
          } catch (err) {
            console.error('[NetPulse] stream handler error', err);
            this.#warn('Unexpected UI error while updating — showing last known values.');
          }
        };
        source.onerror = () => {
          // Fall back to polling so a dropped stream never freezes on
          // invented values. Persistent poll failure shows an error.
          source.close();
          this._source = null;
          this.#startPolling();
        };
        return;
      } catch (err) {
        console.error('[NetPulse] EventSource open failed', err);
        this._source = null;
      }
    }
    this.#startPolling();
  }

  #startPolling() {
    this._stopPolling = false;
    this.#pollOnce();
  }

  #pollOnce() {
    if (this._stopPolling) return;
    fetch('/api/speedtest/status')
      .then(async (res) => {
        if (!res.ok) throw new Error(String(res.status));
        return res.json();
      })
      .then((job) => { this._pollFails = 0; this.#handleStatus(job); })
      .catch(() => {
        this._pollFails += 1;
        if (this._pollFails >= 3) {
          this.#stopPolling();
          this.#setState('error');
          this._statusEl.textContent = 'Live stream dropped — test not counted. Please re-test.';
          showToast('error', 'Live stream dropped — test not counted. Please re-test.');
        }
      })
      .finally(() => {
        if (!this._stopPolling) this._pollTimer = setTimeout(() => this.#pollOnce(), 500);
      });
  }

  #stopPolling() {
    this._stopPolling = true;
    if (this._pollTimer) { clearTimeout(this._pollTimer); this._pollTimer = null; }
    if (this._source) { this._source.close(); this._source = null; }
  }

  #handleStatus(job) {
    if (!job) return;
    if (job.running) {
      const phase = job.phase || 'latency';
      this._phase = phase;
      if (phase === 'latency') {
        this._phaseEl.textContent = 'PING';
        this._statusEl.textContent = 'Measuring latency…';
        if (job.ping_live_ms != null) {
          this._livePing = job.ping_live_ms;
          this.#renderLatency(job.ping_live_ms);
        }
        this._targetMbps = 0;
        this.#setNeedle(0);
        this.#beginCounting();
      } else if (phase === 'download') {
        this._phaseEl.textContent = 'DOWNLOAD';
        this._statusEl.textContent = 'Testing download…';
        if (job.download_live_mbps != null) this._targetMbps = job.download_live_mbps;
        if (job.ping_live_ms != null) this._livePing = job.ping_live_ms;
        this.#beginCounting();
        this.#updateLivePing();
      } else if (phase === 'upload') {
        this._phaseEl.textContent = 'UPLOAD';
        this._statusEl.textContent = 'Testing upload…';
        if (job.upload_live_mbps != null) this._targetMbps = job.upload_live_mbps;
        if (job.ping_live_ms != null) this._livePing = job.ping_live_ms;
        this.#beginCounting();
        this.#updateLivePing();
      }
      if (job.unloaded_ms != null || job.loaded_ms != null) {
        this.updateLatency(job.unloaded_ms, job.loaded_ms);
        this.#updateLivePing();
      }
      return;
    }
    if (job.phase === 'done') {
      this.complete(job);
    } else if (job.phase === 'failed') {
      this.#fail(job, true);
    } else if (job.phase === 'error') {
      this.#fail(job, false);
    } else {
      this.#stopPolling();
      this.#resetToIdle();
      this._resetBtn.hidden = false;
    }
  }

  /* Failed/partial (download kept, upload failed) or hard error. */
  #fail(job, isPartial) {
    this.#stopPolling();
    const dl = job.download_mbps;
    const failedIsTest = isPartial || (job.error && String(job.error).includes('Ookla'));
    const phase = failedIsTest ? 'failed' : 'error';
    if (dl != null) {
      this._targetMbps = dl;
      this._shownMbps = dl;
    }
    if (isPartial) {
      this.#setState('failed');
      const upFailed = job.upload_mbps == null;
      this._statusEl.textContent =
        (job.error || 'Test failed.') +
        (upFailed ? ' Download measured; upload failed.' : '');
      showToast('error', this._statusEl.textContent);
      this.#renderResults(job);
    } else {
      this.#setState('error');
      this._statusEl.textContent = job.error || 'Speed test failed.';
      this._phaseEl.textContent = 'ERROR';
      showToast('error', job.error || 'Speed test failed.');
    }
    if (this._onComplete) this._onComplete(job);
  }

  #renderLatency(ms) {
    this._valueEl.textContent = formatLatencyValue(ms);
    this._unitEl.textContent = 'ms';
    this.#updateLivePing();
  }

  #updateLivePing() {
    if (!this._livePingEl) return;
    if (this._phase === 'latency') {
      this._livePingEl.textContent = '';
      return;
    }
    // Single source: latest 1.1.1.1 single ping (loaded during transfer).
    // Unloaded (mean of 5 pre-test pings) lives in the results grid.
    const liveText = this._livePing != null
      ? `Idle (1.1.1.1) ${formatLatency(this._livePing)}`
      : 'Idle (1.1.1.1) –';
    const loadedText = this._loaded != null
      ? `Loaded (1.1.1.1) ${formatLatency(this._loaded)}`
      : 'Loaded (1.1.1.1) –';
    this._livePingEl.textContent = `${liveText} · ${loadedText}`;
  }

  #tick = () => {
    const delta = this._targetMbps - this._shownMbps;
    this._shownMbps += delta * 0.2;
    if (Math.abs(delta) < 0.05) this._shownMbps = this._targetMbps;
    if (this._phase === 'download' || this._phase === 'upload') {
      const parts = formatSpeed(this._shownMbps);
      this._valueEl.textContent = parts.value;
      this._unitEl.textContent = parts.unit;
      this.#setNeedle(this._shownMbps);
    } else if (this._state === 'done') {
      const parts = formatSpeed(this._shownMbps);
      this._valueEl.textContent = parts.value;
      this._unitEl.textContent = parts.unit;
      this.#setNeedle(this._shownMbps);
    }
    if (this._state !== 'testing' && this._state !== 'done') { this._rafId = null; return; }
    if (this._state === 'done' && this._shownMbps === this._targetMbps) { this._rafId = null; return; }
    this._rafId = requestAnimationFrame(this.#tick);
  };

  #beginCounting() {
    if (this._rafId !== null) return;
    this._rafId = requestAnimationFrame(this.#tick);
  }

  #setNeedle(mbps) {
    const angle = mbpsToAngle(mbps);
    if (this._needleEl) {
      // Explicit SVG pivot at the hub. Never CSS transform-origin.
      this._needleEl.setAttribute('transform', `rotate(${angle} ${CX} ${CY})`);
    }
    if (this._fillEl) {
      // Hide the stubby pill below a small threshold; butt caps below 50 Mbps.
      const show = mbps != null && Number(mbps) >= 0.5;
      this._fillEl.style.display = show ? '' : 'none';
      if (show) {
        this._fillEl.setAttribute('stroke-linecap', Number(mbps) < 50 ? 'butt' : 'round');
        this._fillEl.setAttribute('d', arcPath(angle));
      }
    }
  }

  /* Small visible warning for unexpected UI errors (never a half-render). */
  #warn(msg) {
    if (this._warnEl) {
      this._warnEl.hidden = false;
      this._warnEl.textContent = msg;
    }
    showToast('info', msg);
  }

  #setState(state) {
    this._state = state;
    this._card.classList.remove('gauge-done', 'gauge-error');
    if (state === 'idle') {
      this._shownMbps = 0;
      this._targetMbps = 0;
      this._phase = 'idle';
      this._phaseEl.textContent = 'READY';
      this._valueEl.textContent = '0';
      this._unitEl.textContent = 'Mbps';
      this._livePingEl.textContent = '';
      this._statusEl.textContent = 'Ready to test your connection';
      this._actionBtn.innerHTML = `${ICONS.play}<span>Start Test</span>`;
      this._actionBtn.setAttribute('aria-label', 'Start speed test');
      this._resetBtn.hidden = true;
      this._resultsEl.hidden = true;
      this._resultsEl.classList.remove('results-reveal');
      this.#setNeedle(0);
    } else if (state === 'testing') {
      this._valueEl.textContent = '0';
      this._unitEl.textContent = 'ms';
      this._livePingEl.textContent = '';
      this._actionBtn.innerHTML = `${ICONS.stop}<span>Cancel</span>`;
      this._actionBtn.setAttribute('aria-label', 'Cancel speed test');
      this._resetBtn.hidden = true;
      this._resultsEl.hidden = true;
      this._card.classList.remove('gauge-done');
    } else if (state === 'done') {
      this._statusEl.textContent = 'Your internet speed is';
      this._phaseEl.textContent = 'DOWNLOAD';
      this._actionBtn.innerHTML = `${ICONS.retest}<span>Re-test</span>`;
      this._actionBtn.setAttribute('aria-label', 'Run speed test again');
      this._resetBtn.hidden = false;
      this._card.classList.add('gauge-done');
      const parts = formatSpeed(this._shownMbps);
      this._valueEl.textContent = parts.value;
      this._unitEl.textContent = parts.unit;
      this.#setNeedle(this._shownMbps);
      this.#updateLivePing();
    } else if (state === 'failed') {
      this._phaseEl.textContent = 'FAILED TEST';
      this._actionBtn.innerHTML = `${ICONS.retest}<span>Retry Test</span>`;
      this._actionBtn.setAttribute('aria-label', 'Retry speed test');
      this._resetBtn.hidden = false;
      const parts = formatSpeed(this._shownMbps);
      if (this._shownMbps > 0) {
        this._valueEl.textContent = parts.value;
        this._unitEl.textContent = parts.unit;
        this.#setNeedle(this._shownMbps);
      }
    } else if (state === 'error') {
      this._resetBtn.hidden = false;
      this._phaseEl.textContent = 'ERROR';
      this._valueEl.textContent = '–';
      this._unitEl.textContent = '';
      this._livePingEl.textContent = '';
      this._actionBtn.innerHTML = `${ICONS.play}<span>Try Again</span>`;
      this._actionBtn.setAttribute('aria-label', 'Try speed test again');
      this._card.classList.add('gauge-error');
      this.#setNeedle(0);
    }
  }

  #resetToIdle() {
    this._shownMbps = 0;
    this._targetMbps = 0;
    this.#setState('idle');
  }

  #renderResults(data) {
    const dl = formatSpeed(data.download_mbps);
    const ul = formatSpeed(data.upload_mbps);
    const unloaded = data.unloaded_ms ?? this._unloaded;
    const loaded = data.loaded_ms ?? this._loaded;
    const jitter = data.jitter_ms;
    const maskIp = (s) => (s || '–').replace(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}/g, '$1•••');
    const rows = [
      { label: 'Idle Latency (1.1.1.1)', value: formatLatency(unloaded) },
      { label: 'Loaded Latency (1.1.1.1)', value: formatLatency(loaded) },
      { label: 'Jitter (1.1.1.1)', value: formatLatency(jitter) },
      { label: 'Download Speed', value: dl.text },
      { label: 'Upload Speed', value: ul.text },
      { label: 'Engine', value: data.engine || '–' },
      { label: 'Client', value: maskIp(data.client), full: true },
      { label: 'Server', value: data.server || '–', full: true },
    ];
    this._resultsEl.innerHTML = rows.map((r) => `
      <div class="result-item${r.full ? ' result-item-full' : ''}">
        <div class="result-label">${r.label.toUpperCase()}</div>
        <div class="result-value">${r.value}</div>
      </div>
    `).join('');
    this._resultsEl.hidden = false;
    this._resultsEl.classList.remove('results-reveal');
    void this._resultsEl.offsetWidth;
    this._resultsEl.classList.add('results-reveal');
  }
}
