/* ══════════════════════════════════════════════════════
   NetPulse — speedtest.js
   Test client/state machine for the needle gauge. Rendering
   lives in gauge-view.js; scale math in gauge-scale.js.
   Live samples drive the needle; the final stored value is
   what is shown once the test completes.
   ══════════════════════════════════════════════════════ */

import { showToast } from './components.js';
import { GaugeView } from './gauge-view.js';

export class SpeedTestGauge {
  constructor(mountEl, { onComplete } = {}) {
    this._view = new GaugeView(mountEl, {
      onAction: () => {
        if (this._view._state === 'testing') this.stop();
        else this.start();
      },
      onReset: () => this.reset(),
    });
    this._onComplete = onComplete;
    this._state = 'idle';
    this._phase = 'idle';
    this._shownMbps = 0;
    this._targetMbps = 0;
    this._livePing = null;
    this._unloaded = null;
    this._loaded = null;
    this._rafId = null;
    this._source = null;
    this._pollTimer = null;
    this._pollFails = 0;
    this._stopPolling = true;
    this._starting = false;
  }

  render() {
    this._view.render();
    this.#syncOnLoad();
    this.#demoIfRequested();
  }

  reset() {
    fetch('/api/speedtest/reset', { method: 'POST' }).catch(() => {});
    this.#stopPolling();
    this.#resetToIdle();
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
      const mbps = Number(range.value);
      this._state = 'testing';
      this._phase = 'download';
      this._targetMbps = mbps;
      this._shownMbps = mbps;
      this._view.setState('testing');
      this._view.showValue(mbps);
      this._view.setPhase('DEMO');
      this._view.setStatus(`${mbps} Mbps (demo — not a measurement)`);
    });
    demo.appendChild(range);
    this._view._mount.appendChild(demo);
  }

  async start() {
    if (this._view._state === 'testing' || this._starting) return;
    this._starting = true;
    this._view.setStatus('Starting…');
    let res;
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
    this._view.setLiveLatency({ livePing: this._livePing, loaded: this._loaded, phase: this._phase });
  }

  complete(data) {
    this.#stopPolling();
    const final = (data.download_mbps != null) ? data.download_mbps : 0;
    this._targetMbps = final;
    this._shownMbps = final;
    this.updateLatency(data.unloaded_ms, data.loaded_ms);
    this.#setState('done', { shownMbps: final });
    this._view.renderResults(data, { unloaded: this._unloaded, loaded: this._loaded });
    if (this._onComplete) this._onComplete(data);
  }

  /* ── Internals ─────────────────────────────────────── */

  #syncOnLoad() { this.#syncToBackend(); }

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
          this.#fail(job, true);
        } else if (job.phase === 'error') {
          this.#fail(job, false);
        } else {
          this.#resetToIdle();
          this._view._resetBtn.hidden = false;
        }
      })
      .catch((err) => {
        console.error('[NetPulse] sync failed', err);
        this.#resetToIdle();
      });
  }

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
            this._view.warn('Unexpected UI error while updating — showing last known values.');
          }
        };
        source.onerror = () => {
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
          this._view.setStatus('Live stream dropped — test not counted. Please re-test.');
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
        this._view.setPhase('PING');
        this._view.setStatus('Measuring latency…');
        if (job.ping_live_ms != null) {
          this._livePing = job.ping_live_ms;
          this._view.showLatency(job.ping_live_ms);
        }
        this._targetMbps = 0;
        this._view.setNeedle(0);
        this.#beginCounting();
      } else if (phase === 'download') {
        this._view.setPhase('DOWNLOAD');
        this._view.setStatus('Testing download…');
        if (job.download_live_mbps != null) this._targetMbps = job.download_live_mbps;
        if (job.ping_live_ms != null) this._livePing = job.ping_live_ms;
        this.#beginCounting();
        this._view.setLiveLatency({ livePing: this._livePing, loaded: this._loaded, phase: this._phase });
      } else if (phase === 'upload') {
        this._view.setPhase('UPLOAD');
        this._view.setStatus('Testing upload…');
        if (job.upload_live_mbps != null) this._targetMbps = job.upload_live_mbps;
        if (job.ping_live_ms != null) this._livePing = job.ping_live_ms;
        this.#beginCounting();
        this._view.setLiveLatency({ livePing: this._livePing, loaded: this._loaded, phase: this._phase });
      }
      if (job.unloaded_ms != null || job.loaded_ms != null) {
        this.updateLatency(job.unloaded_ms, job.loaded_ms);
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
      this._view._resetBtn.hidden = false;
    }
  }

  #fail(job, isPartial) {
    this.#stopPolling();
    const dl = job.download_mbps;
    if (dl != null) {
      this._targetMbps = dl;
      this._shownMbps = dl;
    }
    if (isPartial) {
      this.#setState('failed', { shownMbps: this._shownMbps });
      const upFailed = job.upload_mbps == null;
      this._view.setStatus(
        (job.error || 'Test failed.') + (upFailed ? ' Download measured; upload failed.' : '')
      );
      showToast('error', this._view._statusEl.textContent);
      this._view.renderResults(job, { unloaded: this._unloaded, loaded: this._loaded });
    } else {
      this.#setState('error');
      this._view.setStatus(job.error || 'Speed test failed.');
      this._view.setPhase('ERROR');
      showToast('error', job.error || 'Speed test failed.');
    }
    if (this._onComplete) this._onComplete(job);
  }

  #tick = () => {
    const delta = this._targetMbps - this._shownMbps;
    this._shownMbps += delta * 0.2;
    if (Math.abs(delta) < 0.05) this._shownMbps = this._targetMbps;
    if (this._phase === 'download' || this._phase === 'upload' || this._state === 'done') {
      this._view.showValue(this._shownMbps);
    }
    if (this._state !== 'testing' && this._state !== 'done') { this._rafId = null; return; }
    if (this._state === 'done' && this._shownMbps === this._targetMbps) { this._rafId = null; return; }
    this._rafId = requestAnimationFrame(this.#tick);
  };

  #beginCounting() {
    if (this._rafId !== null) return;
    this._rafId = requestAnimationFrame(this.#tick);
  }

  #setState(state, { shownMbps } = {}) {
    this._state = state;
    if (shownMbps !== undefined) this._shownMbps = shownMbps;
    this._view.setState(state, { shownMbps: this._shownMbps });
  }

  #resetToIdle() {
    this._shownMbps = 0;
    this._targetMbps = 0;
    this._phase = 'idle';
    this.#setState('idle');
  }
}
