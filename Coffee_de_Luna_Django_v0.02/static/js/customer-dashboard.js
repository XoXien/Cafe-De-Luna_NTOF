/* Refresh only when an order's actual status changes. No fake progress timers. */
(() => {
  'use strict';
  const orders = [...document.querySelectorAll('[data-live-order]')];
  if (!orders.length) return;
  let running = false;
  async function updateOrders() {
    if (document.hidden || running) return;
    running = true;
    try {
      for (const card of orders) {
        const response = await fetch(card.dataset.statusUrl, {credentials: 'same-origin', cache: 'no-store'});
        if (!response.ok) continue;
        const data = await response.json();
        if (data.status !== card.dataset.orderStatus || String(data.paid) !== card.dataset.orderPaid || String(data.refund_due) !== card.dataset.refundDue) {
          window.location.reload(); return;
        }
      }
    } catch (_) { /* The visible tracking links and Refresh now remain available. */ }
    finally { running = false; }
  }
  const timer = window.setInterval(updateOrders, 15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) updateOrders(); });
  window.addEventListener('pagehide', () => window.clearInterval(timer), {once: true});
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
})();
