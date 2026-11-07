// Outage + failed-test list rendering (split from app.js).
import { openModal } from './components.js';

export function renderOutages(outages, failedTests = []) {
  const list = document.getElementById('outagesList');
  if (!list) return;
  if (!outages.length && !failedTests.length) {
    list.innerHTML = `<p style="color:var(--muted);font-size:0.875rem;padding:6px 0;">No outages in this period. 🎉</p>`;
    return;
  }
  const combined = [
    ...outages.map((o) => ({ ...o, _isFailed: o.type === 'failed_test' })),
    ...failedTests.map((f) => ({ ...f, _isFailed: true })),
  ];
  combined.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  list.innerHTML = '';
  combined.slice(0, 30).forEach((o, i) => {
    const card = document.createElement('div');
    card.className = 'outage-card fade-up';
    card.style.animationDelay = `${i * 55}ms`;
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    card.setAttribute('aria-label', `${o._isFailed ? 'Failed test' : 'Outage'} detail — ${o.timestamp}`);
    card.innerHTML = `
      <div>
        <div class="outage-reason">${o.reason || (o._isFailed ? 'Test failed (partial)' : 'Connection lost')}</div>
        <div class="outage-time">${o.timestamp}</div>
      </div>
      <span class="outage-chip">${o._isFailed ? 'FAILED TEST' : 'OUTAGE'}</span>`;
    const openDetail = () => openModal(`
      <div class="modal-header">
        <p class="section-label">INCIDENT DETAIL</p>
        <h3>${o._isFailed ? 'Failed test' : 'Outage'} #${o.id}</h3>
      </div>
      <div class="modal-field">
        <div class="field-label">Timestamp</div>
        <div class="field-value">${o.timestamp}</div>
      </div>
      <div class="modal-field">
        <div class="field-label">Reason</div>
        <div class="field-value">${o.reason || 'Unknown — connectivity check failed'}</div>
      </div>
      <div class="modal-field">
        <div class="field-label">Record ID</div>
        <div class="field-value" style="color:var(--muted)">#${o.id}</div>
      </div>`);
    card.addEventListener('click', openDetail);
    card.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDetail(); }
    });
    list.appendChild(card);
  });
}
