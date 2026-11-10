/* ══════════════════════════════════════════════════════
   NetPulse — settings.js
   Settings tab: advertised plan speed (stored server-side)
   plus the theme toggle.
   ══════════════════════════════════════════════════════ */

import { showToast } from './components.js';
import { applyTheme } from './theme.js';

export class SettingsView {
  constructor(mountId = 'settingsMount') {
    // Resolved in init(): the module loads before the DOM is parsed.
    this._mountId = mountId;
    this._mount = null;
  }

  init() {
    this._mount = document.getElementById(this._mountId);
    if (!this._mount) return;
    this._mount.innerHTML = `
      <div class="settings-row">
        <label class="settings-label" for="planSpeed">Advertised plan speed (Mbps)</label>
        <input id="planSpeed" type="number" min="0.1" step="0.1" placeholder="e.g. 20"
          aria-describedby="planHelp" />
        <p class="settings-help" id="planHelp">
          Used for the % of plan figure, the speed component of the health score and the
          "worse than usual" comparison. Leave empty to compare against your own median.
        </p>
        <div class="settings-actions">
          <button type="button" class="settings-save" data-settings-save>Save plan speed</button>
          <button type="button" class="settings-clear" data-settings-clear>Clear</button>
        </div>
        <p class="settings-status" data-settings-status></p>
      </div>
      <div class="settings-row">
        <span class="settings-label">Theme</span>
        <button type="button" class="theme-toggle" data-theme-btn aria-label="Switch theme">☀ Light</button>
      </div>`;

    const save = this._mount.querySelector('[data-settings-save]');
    const clear = this._mount.querySelector('[data-settings-clear]');
    const input = this._mount.querySelector('#planSpeed');
    const status = this._mount.querySelector('[data-settings-status]');
    if (save) save.addEventListener('click', () => this.save(input.value, status));
    if (clear) clear.addEventListener('click', () => this.save('', status));
    this._mount.querySelectorAll('[data-theme-btn]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const now = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
        applyTheme(now);
        window.dispatchEvent(new Event('netpulse:theme'));
      });
    });
  }

  async load() {
    if (!this._mount) return;
    try {
      const res = await fetch('/api/settings', { cache: 'no-store' });
      if (!res.ok) return;
      const data = await res.json();
      const input = this._mount.querySelector('#planSpeed');
      if (input && data.plan_speed_mbps != null) input.value = data.plan_speed_mbps;
    } catch (err) {
      console.error('[NetPulse] settings load error', err);
    }
  }

  async save(value, statusEl) {
    const body = { plan_speed_mbps: value === '' ? null : Number(value) };
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (statusEl) statusEl.textContent = data.error || 'Could not save.';
        showToast('error', data.error || 'Could not save the plan speed.');
        return;
      }
      if (statusEl) {
        statusEl.textContent = data.plan_speed_mbps
          ? `Plan speed saved: ${data.plan_speed_mbps} Mbps`
          : 'Plan speed cleared.';
      }
      showToast('success', data.plan_speed_mbps
        ? `Plan speed saved (${data.plan_speed_mbps} Mbps).`
        : 'Plan speed cleared.');
      window.dispatchEvent(new CustomEvent('netpulse:settings'));
    } catch (err) {
      console.error('[NetPulse] settings save error', err);
      if (statusEl) statusEl.textContent = 'Server unreachable — not saved.';
      showToast('error', 'Server unreachable — plan speed not saved.');
    }
  }
}
