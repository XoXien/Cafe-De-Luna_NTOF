/* Small interactions shared by the staff workspace and customer menu. */
(() => {
  'use strict';
  const body = document.body;
  const toggle = document.querySelector('[data-sidebar-toggle]');
  const closeSidebar = () => {
    body.classList.remove('sidebar-open');
    toggle?.setAttribute('aria-expanded', 'false');
  };
  toggle?.addEventListener('click', () => {
    const open = body.classList.toggle('sidebar-open');
    toggle.setAttribute('aria-expanded', String(open));
  });
  document.querySelectorAll('[data-sidebar-close]').forEach(el => el.addEventListener('click', closeSidebar));
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeSidebar(); });
  document.querySelectorAll('[data-dismiss]').forEach(el => el.addEventListener('click', () => el.closest('.message').remove()));
  document.querySelectorAll('[data-print]').forEach(el => el.addEventListener('click', () => window.print()));
  document.querySelectorAll('[data-reload]').forEach(el => el.addEventListener('click', () => window.location.reload()));
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  document.addEventListener('click', event => {
    document.querySelectorAll('.profile-menu[open], .row-menu[open]').forEach(detail => {
      if (!detail.contains(event.target)) detail.removeAttribute('open');
    });
  });
  let toastTimer;
  window.cafeToast = message => {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => toast.classList.remove('visible'), 2800);
  };
  document.getElementById('add-recipe-row')?.addEventListener('click', () => {
    const total = document.getElementById('id_recipe-TOTAL_FORMS');
    const index = Number(total.value);
    if (index >= 50) return window.cafeToast('Use up to 50 ingredients per recipe.');
    const template = document.getElementById('recipe-empty-template');
    const fragment = template.content.cloneNode(true);
    fragment.querySelectorAll('[name], [id], [for]').forEach(element => {
      ['name', 'id', 'for'].forEach(attribute => {
        if (element.hasAttribute(attribute)) {
          element.setAttribute(attribute, element.getAttribute(attribute).replaceAll('__prefix__', String(index)));
        }
      });
    });
    document.getElementById('recipe-rows').appendChild(fragment);
    total.value = String(index + 1);
  });
  // Recheck authentication when a browser restores a page from its history cache.
  window.addEventListener('pageshow', event => {
    if (event.persisted && body.classList.contains('workspace')) window.location.reload();
  });
})();
