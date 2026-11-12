// Tab router: hash URLs, last-tab memory, keyboard shortcuts.
const TABS = ['measure', 'trends', 'outages', 'log', 'settings'];

export function currentTab() {
  const match = (location.hash || '').match(/^#\/([a-z]+)/);
  if (match && TABS.includes(match[1])) return match[1];
  let stored = null;
  try { stored = localStorage.getItem('netpulse-tab'); } catch {}
  return TABS.includes(stored) ? stored : 'measure';
}

export function showTab(tab, { push = true } = {}) {
  const next = TABS.includes(tab) ? tab : 'measure';
  TABS.forEach((name) => {
    const panel = document.getElementById(`tab-${name}`);
    if (panel) panel.hidden = name !== next;
  });
  document.querySelectorAll('[data-tab-btn]').forEach((btn) => {
    const active = btn.dataset.tabBtn === next;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  try { localStorage.setItem('netpulse-tab', next); } catch {}
  if (push && location.hash !== `#/${next}`) {
    history.replaceState(null, '', `#/${next}`);
  }
  window.dispatchEvent(new CustomEvent('netpulse:tab', { detail: next }));
}

export function initTabs(onShow) {
  const nav = document.getElementById('mainTabs');
  if (!nav) return;
  nav.addEventListener('click', (e) => {
    const btn = e.target.closest('[data-tab-btn]');
    if (btn) showTab(btn.dataset.tabBtn);
  });
  window.addEventListener('hashchange', () => showTab(currentTab(), { push: false }));
  // Register the listener BEFORE the first showTab so a remembered tab
  // loads its content on page load.
  if (onShow) {
    window.addEventListener('netpulse:tab', (e) => onShow(e.detail));
  }
  showTab(currentTab(), { push: false });
  document.addEventListener('keydown', (e) => {
    const tag = (e.target.tagName || '').toLowerCase();
    const inField = tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable;
    if (inField || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === ' ') {
      // Let a focused button handle Space itself (native click) — never double-fire.
      if (tag === 'button') return;
      if (currentTab() === 'measure') {
        e.preventDefault();
        document.getElementById('gaugeAction')?.click();
      }
      return;
    }
    const n = Number(e.key);
    if (n >= 1 && n <= TABS.length) {
      e.preventDefault();
      showTab(TABS[n - 1]);
    }
  });
}
