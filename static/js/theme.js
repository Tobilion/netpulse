// Theme toggle (dark default, warm cream light) with persistence.
export function getStoredTheme() {
  try {
    return localStorage.getItem('netpulse-theme');
  } catch { return null; }
}

export function applyTheme(theme) {
  const next = theme === 'light' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('netpulse-theme', next); } catch {}
  document.querySelectorAll('[data-theme-btn]').forEach((btn) => {
    const isLight = next === 'light';
    btn.textContent = isLight ? '☾ Dark' : '☀ Light';
    btn.setAttribute('aria-label', isLight ? 'Switch to dark mode' : 'Switch to light mode');
  });
  return next;
}

export function initTheme() {
  const stored = getStoredTheme();
  const initial = stored === 'light' ? 'light' : 'dark';
  applyTheme(initial);
  document.querySelectorAll('[data-theme-btn]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const now = document.documentElement.getAttribute('data-theme') === 'light' ? 'dark' : 'light';
      applyTheme(now);
      // Charts read the theme at build time; rebuild on next render.
      window.dispatchEvent(new Event('netpulse:theme'));
    });
  });
  return initial;
}
