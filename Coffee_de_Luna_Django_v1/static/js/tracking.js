/* Refresh the order when staff confirm payment, progress, or a refund. */
(() => {
  'use strict';
  const root = document.querySelector('[data-order-tracking]');
  if (!root) return;
  const initial = {paid: root.dataset.paid === 'true', status: root.dataset.status,
    refund_due: root.dataset.refundDue === 'true'};
  let timer, controller, inFlight = false, stopped = false;
  const finished = () => initial.status === 'completed' || (initial.status === 'cancelled' && !initial.refund_due);
  function schedule() {
    clearTimeout(timer);
    if (!stopped && !finished()) timer = setTimeout(check, 10000);
  }
  async function check() {
    if (stopped || inFlight || finished()) return;
    if (document.hidden) { schedule(); return; }
    inFlight = true; controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(root.dataset.statusUrl, {credentials: 'same-origin', cache: 'no-store',
        headers: {'Accept': 'application/json'}, signal: controller.signal});
      if (response.status === 404) { stopped = true; return; }
      if (!response.ok) return;
      const state = await response.json();
      if (typeof state.paid !== 'boolean' || typeof state.status !== 'string' || typeof state.refund_due !== 'boolean') return;
      if (state.paid !== initial.paid || state.status !== initial.status || state.refund_due !== initial.refund_due) {
        stopped = true;
        window.location.reload();
      }
    } catch (_) {
      // Transient connection failures keep the order visible and retry later.
    } finally {
      clearTimeout(timeout); inFlight = false; controller = null; schedule();
    }
  }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
  window.addEventListener('pagehide', () => { stopped = true; clearTimeout(timer); controller?.abort(); });
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
  schedule();
})();
