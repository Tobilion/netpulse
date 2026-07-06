/* ══════════════════════════════════════════════════════
   NetPulse — components.js
   All 13 A1 required UI components (vanilla JS + CSS)
   ══════════════════════════════════════════════════════ */

/* ── 1. SPOTLIGHT CARD ──────────────────────────────── */
export function initSpotlightCards() {
  document.querySelectorAll('.spotlight-card').forEach(card => {
    if (card._spotlightBound) return;
    card._spotlightBound = true;

    card.addEventListener('mousemove', e => {
      const r = card.getBoundingClientRect();
      card.style.setProperty('--mx', `${e.clientX - r.left}px`);
      card.style.setProperty('--my', `${e.clientY - r.top}px`);
      card.classList.add('spotlight-active');
    });
    card.addEventListener('mouseleave', () => {
      card.classList.remove('spotlight-active');
    });
  });
}

/* ── 2. TILT CARD ───────────────────────────────────── */
export function initTiltCards() {
  document.querySelectorAll('.tilt-card').forEach(card => {
    if (card._tiltBound) return;
    card._tiltBound = true;

    card.addEventListener('mousemove', e => {
      const r   = card.getBoundingClientRect();
      const cx  = r.left + r.width  / 2;
      const cy  = r.top  + r.height / 2;
      const rx  = ((e.clientY - cy) / (r.height / 2)) * -8;
      const ry  = ((e.clientX - cx) / (r.width  / 2)) *  8;
      card.style.transform =
        `perspective(800px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-3px)`;
    });
    card.addEventListener('mouseleave', () => {
      card.style.transform =
        'perspective(800px) rotateX(0deg) rotateY(0deg) translateY(0px)';
    });
  });
}

/* ── 3. MAGNETIC BUTTON ─────────────────────────────── */
export function initMagneticButtons() {
  document.querySelectorAll('.magnetic-btn').forEach(btn => {
    if (btn._magnetBound) return;
    btn._magnetBound = true;

    btn.addEventListener('mousemove', e => {
      const r  = btn.getBoundingClientRect();
      const dx = (e.clientX - (r.left + r.width  / 2)) * 0.3;
      const dy = (e.clientY - (r.top  + r.height / 2)) * 0.3;
      btn.style.transform = `translate(${dx}px, ${dy}px) translateY(-2px)`;
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.transform = 'translate(0, 0)';
    });
    btn.addEventListener('mousedown', () => {
      btn.style.transform += ' scale(0.97)';
    });
  });
}

/* ── 4. GLOW ORB ────────────────────────────────────── */
// GlowOrbs are purely CSS — .glow-orb.orb-1/2/3 in the HTML

/* ── 5. TUBELIGHT NAV ───────────────────────────────── */
export function initTubelightNav(navEl, onChange) {
  const pill    = navEl.querySelector('.nav-pill');
  const buttons = Array.from(navEl.querySelectorAll('button'));

  function movePill(btn) {
    const navRect = navEl.getBoundingClientRect();
    const btnRect = btn.getBoundingClientRect();
    pill.style.left  = `${btnRect.left - navRect.left}px`;
    pill.style.width = `${btnRect.width}px`;
  }

  function activate(btn) {
    buttons.forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    movePill(btn);
    if (onChange) onChange(btn.dataset.range);
  }

  // Place pill on the active button after first paint
  requestAnimationFrame(() => {
    const active = navEl.querySelector('button.active') || buttons[0];
    movePill(active);
  });

  navEl.addEventListener('click', e => {
    const btn = e.target.closest('button');
    if (btn) activate(btn);
  });
}

/* ── 6. TEXT SCRAMBLE ───────────────────────────────── */
export function textScramble(el, plainText, duration = 850, finalHTML = null) {
  // Skip if reduced motion is preferred
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    el.innerHTML = finalHTML || plainText;
    return;
  }

  const CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789!@#%&?';
  const totalFrames = Math.round(duration / 40);
  let   frame       = 0;

  const tick = () => {
    const progress     = frame / totalFrames;
    const resolvedUpTo = Math.floor(progress * plainText.length);
    let   output       = '';

    for (let i = 0; i < plainText.length; i++) {
      if (plainText[i] === ' ' || plainText[i] === '\n') {
        output += plainText[i];
      } else if (i < resolvedUpTo) {
        output += plainText[i];
      } else {
        output += CHARS[Math.floor(Math.random() * CHARS.length)];
      }
    }

    el.textContent = output;
    frame++;

    if (frame <= totalFrames) {
      setTimeout(tick, 40);
    } else {
      el.innerHTML = finalHTML || plainText;
    }
  };

  tick();
}

/* ── 7. SCROLL PROGRESS BAR ─────────────────────────── */
export function initScrollProgress(barEl) {
  if (!barEl) return;
  const update = () => {
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    const pct = scrollable > 0 ? (window.scrollY / scrollable) * 100 : 0;
    barEl.style.width = `${Math.min(pct, 100)}%`;
  };
  window.addEventListener('scroll', update, { passive: true });
  update();
}

/* ── 8. ANIMATED COUNTER ────────────────────────────── */
export function animatedCounter(el, target, suffix = '', duration = 1000) {
  if (target === null || target === undefined || isNaN(parseFloat(target))) {
    el.textContent = '–';
    return;
  }
  const numTarget = parseFloat(target);
  const isInt     = Number.isInteger(numTarget);
  const start     = performance.now();

  const tick = (now) => {
    const elapsed  = now - start;
    const progress = Math.min(elapsed / duration, 1);
    const eased    = 1 - Math.pow(1 - progress, 3); // easeOutCubic
    const current  = numTarget * eased;
    el.textContent = (isInt ? Math.round(current) : current.toFixed(1)) + suffix;
    if (progress < 1) requestAnimationFrame(tick);
    else el.textContent = (isInt ? numTarget : numTarget.toFixed(1)) + suffix;
  };
  requestAnimationFrame(tick);
}

export function observeAndCount(el, target, suffix, duration = 1000) {
  const io = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        animatedCounter(el, target, suffix, duration);
        io.disconnect();
      }
    });
  }, { threshold: 0.25 });
  io.observe(el);
}

/* ── 9. PROGRESS RING ───────────────────────────────── */
export function createProgressRing(container, pct) {
  const R            = 28;
  const circumference = 2 * Math.PI * R;
  const safePct      = pct !== null && pct !== undefined ? Math.min(Math.max(pct, 0), 100) : 0;
  const dashOffset   = circumference * (1 - safePct / 100);

  container.innerHTML = `
    <svg class="progress-ring-svg" viewBox="0 0 72 72" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <defs>
        <linearGradient id="ringGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%"   stop-color="#38bdf8"/>
          <stop offset="100%" stop-color="#818cf8"/>
        </linearGradient>
      </defs>
      <circle class="progress-ring-track" cx="36" cy="36" r="${R}"/>
      <circle
        class="progress-ring-fill"
        cx="36" cy="36" r="${R}"
        stroke="url(#ringGrad)"
        stroke-dasharray="${circumference.toFixed(2)}"
        stroke-dashoffset="${circumference.toFixed(2)}"
      />
    </svg>
    <div class="progress-ring-label">${pct !== null ? Math.round(pct) + '%' : '–'}</div>
  `;

  // Animate after next paint
  requestAnimationFrame(() => {
    setTimeout(() => {
      const fill = container.querySelector('.progress-ring-fill');
      if (fill) fill.style.strokeDashoffset = dashOffset.toFixed(2);
    }, 80);
  });
}

/* ── 10. SKELETON LOADER ─────────────────────────────── */
export function showStatSkeletons(gridEl, count = 5) {
  if (!gridEl) return;
  gridEl.innerHTML = '';
  for (let i = 0; i < count; i++) {
    const card  = document.createElement('div');
    card.className = 'skeleton-card';
    card.innerHTML = `
      <div class="skeleton skeleton-label"></div>
      <div class="skeleton skeleton-value"></div>
    `;
    gridEl.appendChild(card);
  }
}

export function showChartSkeleton(wrapEl) {
  if (!wrapEl) return;
  const sk = document.createElement('div');
  sk.className = 'skeleton skeleton-chart';
  wrapEl.appendChild(sk);
}

/* ── 11. TOAST SYSTEM ───────────────────────────────── */
const ICONS = {
  success: `<svg fill="none" viewBox="0 0 20 20" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
  error:   `<svg fill="none" viewBox="0 0 20 20" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
  info:    `<svg fill="none" viewBox="0 0 20 20" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>`,
};
const TITLES = { success: 'Success', error: 'Error', info: 'Info' };
let _toastQueue = [];

export function showToast(type = 'info', message, duration = 3500) {
  const container = document.getElementById('toastContainer');
  if (!container) return;

  // Enforce max 3 toasts
  if (_toastQueue.length >= 3) _dismissToast(_toastQueue[0]);

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.setAttribute('role', 'status');
  toast.innerHTML = `
    <div class="toast-icon">${ICONS[type] || ICONS.info}</div>
    <div class="toast-body">
      <div class="toast-title">${TITLES[type] || type}</div>
      <div class="toast-msg">${message}</div>
    </div>
    <div class="toast-progress"><div class="toast-progress-bar"></div></div>
  `;

  container.appendChild(toast);
  _toastQueue.push(toast);

  // Animate the countdown bar
  const bar = toast.querySelector('.toast-progress-bar');
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      bar.style.transition = `width ${duration}ms linear`;
      bar.style.width = '0%';
    });
  });

  const timer = setTimeout(() => _dismissToast(toast), duration);
  toast.addEventListener('click', () => { clearTimeout(timer); _dismissToast(toast); });
}

function _dismissToast(toast) {
  if (!toast || !toast.parentNode) return;
  toast.classList.add('leaving');
  _toastQueue = _toastQueue.filter(t => t !== toast);
  setTimeout(() => toast.remove(), 320);
}

/* ── 12. EMPTY STATE ────────────────────────────────── */
export function renderEmptyState(container) {
  if (!container) return;
  container.innerHTML = `
    <div class="empty-state fade-up">
      <div class="empty-state-icon">
        <svg width="120" height="80" viewBox="0 0 120 80" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
          <rect width="120" height="80" rx="12" fill="rgba(56,189,248,0.04)"/>
          <path d="M15 58 L30 35 L45 48 L62 18 L78 36 L94 24 L108 58"
            stroke="rgba(56,189,248,0.2)" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round" fill="none"/>
          <path d="M15 58 L30 35 L45 48 L62 18 L78 36 L94 24 L108 58"
            stroke="url(#emptyGrad)" stroke-width="2.5"
            stroke-linecap="round" stroke-linejoin="round" fill="none" opacity="0.8"/>
          <circle cx="62" cy="18" r="4.5" fill="#38bdf8" opacity="0.55"/>
          <circle cx="45" cy="48" r="3"   fill="#818cf8" opacity="0.4"/>
          <circle cx="78" cy="36" r="3"   fill="#38bdf8" opacity="0.35"/>
          <defs>
            <linearGradient id="emptyGrad" x1="15" y1="58" x2="108" y2="18" gradientUnits="userSpaceOnUse">
              <stop stop-color="#38bdf8"/>
              <stop offset="1" stop-color="#818cf8"/>
            </linearGradient>
          </defs>
        </svg>
      </div>
      <h3>No data yet</h3>
      <p>NetPulse hasn't recorded any measurements. Seed 14 days of realistic demo data with one command, then refresh.</p>
      <div class="code-chip" id="copyCmd" role="button" tabindex="0" aria-label="Copy demo command">
        <svg class="copy-icon" width="15" height="15" viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="9" y="9" width="13" height="13" rx="2"/>
          <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
        </svg>
        python main.py demo
      </div>
      <p class="empty-note">Or start real measurements: <code>python main.py watch --interval 30</code></p>
    </div>
  `;

  const chip = container.querySelector('#copyCmd');
  const copy = () => {
    navigator.clipboard.writeText('python main.py demo').then(() => {
      showToast('success', 'Command copied to clipboard!');
    }).catch(() => showToast('error', 'Copy failed — check clipboard permissions.'));
  };
  chip?.addEventListener('click', copy);
  chip?.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') copy(); });
}

/* ── 13. MODAL / DRAWER ─────────────────────────────── */
export function openModal(contentHTML) {
  const modal = document.getElementById('outageModal');
  const body  = document.getElementById('modalContent');
  if (!modal || !body) return;
  body.innerHTML = contentHTML;
  modal.removeAttribute('hidden');
  document.body.style.overflow = 'hidden';
  // Focus the close button for accessibility
  setTimeout(() => document.getElementById('modalClose')?.focus(), 60);
}

export function closeModal() {
  const modal = document.getElementById('outageModal');
  if (!modal) return;
  modal.setAttribute('hidden', '');
  document.body.style.overflow = '';
}

export function initModal() {
  document.getElementById('modalClose')?.addEventListener('click', closeModal);
  document.getElementById('outageModal')?.addEventListener('click', e => {
    if (e.target.id === 'outageModal') closeModal();
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });
}

/* ── UTILITY: STAGGER FADE-UP ────────────────────────── */
export function staggerFadeUp(elements, baseDelay = 0, step = 80) {
  elements.forEach((el, i) => {
    el.style.animationDelay = `${baseDelay + i * step}ms`;
    el.classList.add('fade-up');
  });
}
