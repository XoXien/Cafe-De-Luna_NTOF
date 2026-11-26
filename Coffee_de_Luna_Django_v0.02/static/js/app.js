/* Shared controls. Forms and server-side validation remain usable independently. */
(() => {
  'use strict';
  const body = document.body, html = document.documentElement;
  const mobileNav = window.matchMedia('(max-width: 1000px)');
  const sidebar = document.getElementById('sidebar');
  const workspace = document.querySelector('.workspace-main');
  let navOpener;
  function closeSidebar() {
    body.classList.remove('sidebar-open');
    if (workspace) workspace.inert = false;
    if (sidebar) sidebar.inert = mobileNav.matches;
    sidebar?.removeAttribute('aria-modal'); sidebar?.removeAttribute('role');
    document.querySelectorAll('[data-sidebar-toggle]').forEach(b => b.setAttribute('aria-expanded', 'false'));
  }
  document.querySelectorAll('[data-sidebar-toggle]').forEach(button => button.addEventListener('click', () => {
    if (body.classList.contains('sidebar-open')) { closeSidebar(); return; }
    navOpener = button; body.classList.add('sidebar-open');
    if (sidebar) sidebar.inert = false;
    if (workspace) workspace.inert = true;
    sidebar?.setAttribute('aria-modal', 'true'); sidebar?.setAttribute('role', 'dialog');
    sidebar?.setAttribute('aria-label', 'Staff navigation');
    button.setAttribute('aria-expanded', 'true');
    sidebar?.querySelector('a')?.focus();
  }));
  document.querySelectorAll('[data-sidebar-close]').forEach(button => button.addEventListener('click', () => { closeSidebar(); navOpener?.focus(); }));
  function collapsedState() {
    const collapsed = html.classList.contains('sidebar-collapsed');
    document.querySelectorAll('[data-sidebar-collapse]').forEach(b => {
      b.setAttribute('aria-label', mobileNav.matches ? 'Close navigation' : collapsed ? 'Expand navigation' : 'Collapse navigation');
      b.setAttribute('aria-expanded', String(!collapsed));
    });
  }
  try { html.classList.toggle('sidebar-collapsed', localStorage.getItem('cdl_sidebar') === 'collapsed'); } catch (_) {}
  document.querySelectorAll('[data-sidebar-collapse]').forEach(button => button.addEventListener('click', () => {
    if (mobileNav.matches) { closeSidebar(); navOpener?.focus(); return; }
    const collapsed = html.classList.toggle('sidebar-collapsed');
    try { localStorage.setItem('cdl_sidebar', collapsed ? 'collapsed' : 'expanded'); } catch (_) {}
    collapsedState();
  }));
  mobileNav.addEventListener('change', () => { closeSidebar(); collapsedState(); }); closeSidebar(); collapsedState();
  document.addEventListener('keydown', event => {
    if (!body.classList.contains('sidebar-open')) return;
    if (event.key === 'Escape') { closeSidebar(); navOpener?.focus(); }
    if (event.key === 'Tab' && sidebar) {
      const items = [...sidebar.querySelectorAll('a,button')].filter(e => !e.disabled);
      if (event.shiftKey && document.activeElement === items[0]) { event.preventDefault(); items.at(-1)?.focus(); }
      else if (!event.shiftKey && document.activeElement === items.at(-1)) { event.preventDefault(); items[0]?.focus(); }
    }
  });
  // The mobile bag reuses the very same checkout form and event handlers.
  const cartDialog = document.getElementById('mobile-cart-dialog');
  const cartPanel = document.getElementById('cart-panel');
  const cartSlot = document.getElementById('cart-slot');
  const cartOpener = document.getElementById('mobile-cart-toggle');
  const mobileCart = window.matchMedia('(max-width: 1100px)');
  if (cartDialog && cartPanel && cartSlot && cartOpener) {
    cartOpener.addEventListener('click', () => {
      if (!mobileCart.matches || cartDialog.open) return;
      cartDialog.appendChild(cartPanel); cartDialog.showModal(); body.classList.add('cart-open');
      cartPanel.querySelector('[data-close-cart]')?.focus();
    });
    cartPanel.querySelector('[data-close-cart]')?.addEventListener('click', () => cartDialog.close());
    cartDialog.addEventListener('click', e => { if (e.target === cartDialog) cartDialog.close(); });
    cartDialog.addEventListener('close', () => { cartSlot.appendChild(cartPanel); body.classList.remove('cart-open'); if (mobileCart.matches) cartOpener.focus(); });
    mobileCart.addEventListener('change', () => { if (!mobileCart.matches && cartDialog.open) cartDialog.close(); });
  }
  document.querySelectorAll('[data-dismiss]').forEach(el => el.addEventListener('click', () => el.closest('.message')?.remove()));
  document.querySelectorAll('[data-print]').forEach(el => el.addEventListener('click', () => window.print()));
  document.querySelectorAll('[data-reload]').forEach(el => el.addEventListener('click', () => window.location.reload()));
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => { if (!window.confirm(form.dataset.confirm)) event.preventDefault(); }));
  document.addEventListener('click', event => {
    document.querySelectorAll('.profile-menu[open], .row-menu[open]').forEach(detail => { if (!detail.contains(event.target)) detail.removeAttribute('open'); });
  });
  let toastTimer;
  window.cafeToast = message => {
    const toast = document.getElementById('toast'); if (!toast) return;
    toast.textContent = message; toast.classList.add('visible'); clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('visible'), 2800);
  };
  document.getElementById('add-recipe-row')?.addEventListener('click', () => {
    const total = document.getElementById('id_recipe-TOTAL_FORMS'), index = Number(total.value);
    if (index >= 50) return window.cafeToast('Use up to 50 ingredients per recipe.');
    const fragment = document.getElementById('recipe-empty-template').content.cloneNode(true);
    fragment.querySelectorAll('[name],[id],[for]').forEach(el => ['name','id','for'].forEach(attr => {
      if (el.hasAttribute(attr)) el.setAttribute(attr, el.getAttribute(attr).replaceAll('__prefix__', String(index)));
    }));
    document.getElementById('recipe-rows').appendChild(fragment); total.value = String(index + 1);
  });
  const extra = document.getElementById('id_is_add_on');
  function extraFields() {
    ['customization_type','max_per_drink','replaces_ingredient'].forEach(name => {
      const input = document.getElementById('id_'+name);
      if (input) input.closest('.field').hidden = !extra.checked;
    });
    if (!extra.checked && document.getElementById('id_replaces_ingredient')) document.getElementById('id_replaces_ingredient').value = '';
  }
  if (extra) { extra.addEventListener('change', extraFields); extraFields(); }
  window.addEventListener('pageshow', event => { if (event.persisted && body.classList.contains('workspace')) window.location.reload(); });
})();
