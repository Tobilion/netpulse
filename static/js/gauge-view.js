/* ══════════════════════════════════════════════════════
   NetPulse — gauge-view.js
   Pure rendering for the needle gauge. No network, no state
   machine: SpeedTestGauge (speedtest.js) owns fetching and
   calls these methods.
   ══════════════════════════════════════════════════════ */

import { formatLatency, formatLatencyValue, formatSpeed } from './format.js';
import { CX, CY, arcPath, mbpsToAngle, tickMarkup } from './gauge-scale.js';

const ICONS = {
  play:   `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.53.85l10.2-6.5a1 1 0 0 0 0-1.7L9.53 4.65A1 1 0 0 0 8 5.5z"/></svg>`,
  stop:   `<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>`,
  retest: `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>`,
};

export class GaugeView {
  constructor(mountEl, { onAction, onReset } = {}) {
    this._mount = mountEl;
    this._onAction = onAction;
    this._onReset = onReset;
    this._state = 'idle';
    this._shownMbps = 0;
    this._livePing = null;
    this._loaded = null;
    this._phase = 'idle';
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
      if (this._onAction) this._onAction();
    });
    if (this._resetBtn && this._onReset) {
      this._resetBtn.addEventListener('click', () => this._onReset());
    }
    this.setNeedle(0);
  }

  /* ── Rendering primitives ──────────────────────────── */

  setNeedle(mbps) {
    const angle = mbpsToAngle(mbps);
    if (this._needleEl) {
      // Explicit SVG pivot at the hub. Never CSS transform-origin.
      this._needleEl.setAttribute('transform', `rotate(${angle} ${CX} ${CY})`);
    }
    if (this._fillEl) {
      const show = mbps != null && Number(mbps) >= 0.5;
      this._fillEl.style.display = show ? '' : 'none';
      if (show) {
        this._fillEl.setAttribute('stroke-linecap', Number(mbps) < 50 ? 'butt' : 'round');
        this._fillEl.setAttribute('d', arcPath(angle));
      }
    }
  }

  showValue(mbps) {
    const parts = formatSpeed(mbps);
    this._valueEl.textContent = parts.value;
    this._unitEl.textContent = parts.unit;
    this.setNeedle(mbps);
  }

  showLatency(ms) {
    this._valueEl.textContent = formatLatencyValue(ms);
    this._unitEl.textContent = 'ms';
    this.updateLivePing();
  }

  setLiveLatency({ livePing = this._livePing, loaded = this._loaded, phase = this._phase } = {}) {
    this._livePing = livePing;
    this._loaded = loaded;
    this._phase = phase;
    this.updateLivePing();
  }

  updateLivePing() {
    if (!this._livePingEl) return;
    if (this._phase === 'latency') {
      this._livePingEl.textContent = '';
      return;
    }
    const liveText = this._livePing != null
      ? `Idle (1.1.1.1) ${formatLatency(this._livePing)}`
      : 'Idle (1.1.1.1) –';
    const loadedText = this._loaded != null
      ? `Loaded (1.1.1.1) ${formatLatency(this._loaded)}`
      : 'Loaded (1.1.1.1) –';
    this._livePingEl.textContent = `${liveText} · ${loadedText}`;
  }

  setStatus(text) { this._statusEl.textContent = text; }
  setPhase(text) { this._phaseEl.textContent = text; }
  warn(msg) {
    if (this._warnEl) {
      this._warnEl.hidden = false;
      this._warnEl.textContent = msg;
    }
  }

  /* ── State → DOM ───────────────────────────────────── */

  setState(state, { shownMbps = this._shownMbps } = {}) {
    this._state = state;
    if (state === 'idle') this._shownMbps = 0;
    else this._shownMbps = shownMbps;
    this._card.classList.remove('gauge-done', 'gauge-error');
    if (state === 'idle') {
      this._phase = 'idle';
      this.setPhase('READY');
      this._valueEl.textContent = '0';
      this._unitEl.textContent = 'Mbps';
      this._livePingEl.textContent = '';
      this.setStatus('Ready to test your connection');
      this._actionBtn.innerHTML = `${ICONS.play}<span>Start Test</span>`;
      this._actionBtn.setAttribute('aria-label', 'Start speed test');
      this._resetBtn.hidden = true;
      this._resultsEl.hidden = true;
      this._resultsEl.classList.remove('results-reveal');
      this.setNeedle(0);
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
      this.setStatus('Your internet speed is');
      this.setPhase('DOWNLOAD');
      this._actionBtn.innerHTML = `${ICONS.retest}<span>Re-test</span>`;
      this._actionBtn.setAttribute('aria-label', 'Run speed test again');
      this._resetBtn.hidden = false;
      this._card.classList.add('gauge-done');
      this.showValue(this._shownMbps);
      this.updateLivePing();
    } else if (state === 'failed') {
      this.setPhase('FAILED TEST');
      this._actionBtn.innerHTML = `${ICONS.retest}<span>Retry Test</span>`;
      this._actionBtn.setAttribute('aria-label', 'Retry speed test');
      this._resetBtn.hidden = false;
      if (this._shownMbps > 0) this.showValue(this._shownMbps);
    } else if (state === 'error') {
      this._resetBtn.hidden = false;
      this.setPhase('ERROR');
      this._valueEl.textContent = '–';
      this._unitEl.textContent = '';
      this._livePingEl.textContent = '';
      this._actionBtn.innerHTML = `${ICONS.play}<span>Try Again</span>`;
      this._actionBtn.setAttribute('aria-label', 'Try speed test again');
      this._card.classList.add('gauge-error');
      this.setNeedle(0);
    }
  }

  /* ── Results grid ──────────────────────────────────── */

  renderResults(data, { unloaded, loaded } = {}) {
    const dl = formatSpeed(data.download_mbps);
    const ul = formatSpeed(data.upload_mbps);
    const idle = unloaded != null ? unloaded : data.unloaded_ms;
    const loadedVal = loaded != null ? loaded : data.loaded_ms;
    const jitter = data.jitter_ms;
    const maskIp = (s) => (s || '–').replace(/(\d{1,3}\.\d{1,3}\.\d{1,3}\.)\d{1,3}/g, '$1•••');
    const rows = [
      { label: 'Idle Latency (1.1.1.1)', value: formatLatency(idle) },
      { label: 'Loaded Latency (1.1.1.1)', value: formatLatency(loadedVal) },
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
