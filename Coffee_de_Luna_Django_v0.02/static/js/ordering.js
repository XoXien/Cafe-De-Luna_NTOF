/* Each basket line is one drink + its own extras. Django owns prices and stock. */
(() => {
  'use strict';
  const root = document.querySelector('[data-ordering]');
  if (!root) return;
  const products = new Map(JSON.parse(document.getElementById('products-data').textContent).map(p => [p.id, p]));
  const addons = [...products.values()].filter(p => p.is_add_on);
  const isPublic = root.dataset.public === 'true';
  const storageKey = isPublic ? (root.dataset.cartScope ? `cdl_${root.dataset.cartScope}_cart_v001` : 'cdl_guest_cart_v001') : 'cdl_counter_cart_v001';
  const form = document.getElementById('checkout-form');
  const itemsElement = document.getElementById('cart-items');
  const dialog = document.getElementById('drink-customizer');
  const money = cents => new Intl.NumberFormat('en-PH', {style: 'currency', currency: 'PHP'}).format(cents / 100);
  const price = product => Math.round(Number(product.price) * 100);
  const $ = id => document.getElementById(id);
  const toast = message => window.cafeToast?.(message);
  let cart = new Map(), category = root.dataset.initialCategory || 'all', search = (root.dataset.initialSearch || '').trim().toLowerCase(), busy = false, cashEdited = false, editor = null;
  const orderedExtras = extras => [...extras].sort((a, b) => a[0] - b[0]);
  const signature = line => JSON.stringify([line.id, orderedExtras(line.extras)]);
  const unitPrice = line => price(products.get(line.id)) + [...line.extras].reduce((sum, [id, qty]) => sum + price(products.get(id)) * qty, 0);
  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }
  function button(text, action, className = '') {
    const element = node('button', className, text); element.type = 'button';
    element.addEventListener('click', action); return element;
  }
  function selectedCapacity(line) {
    const product = products.get(line.id);
    let capacity = product.default_capacity;
    for (const [id, count] of line.extras) {
      const extra = products.get(id);
      if (extra.customization_type === 'milk') capacity = product.milk_options[String(id)]?.capacity || 0;
    }
    for (const [id, count] of line.extras) {
      const extra = products.get(id);
      if (extra.customization_type !== 'milk') capacity = Math.min(capacity, Math.floor(extra.capacity / count));
    }
    // Shared ingredients across drinks/extras are checked together by Django.
    return Math.min(99, capacity);
  }
  function extraDescription(product, extra) {
    if (extra.customization_type === 'milk') {
      const option = product.milk_options[String(extra.id)];
      return option?.mode === 'replace' ? `${extra.extra_label} · replaces whole milk` : `Add ${extra.extra_label}`;
    }
    return extra.extra_label;
  }
  function restore(saved) {
    if (!saved || Date.now() - saved.time >= 7200000 || !Array.isArray(saved.items)) return;
    for (const row of saved.items.slice(0, 50)) {
      const product = products.get(row.id);
      if (!product || product.is_add_on || !Number.isInteger(row.quantity) || row.quantity < 1 || row.quantity > 99 || !Array.isArray(row.add_ons)) continue;
      const extras = new Map();
      let valid = true;
      const kinds = new Set();
      for (const extra of row.add_ons) {
        const item = products.get(extra.id), kind = item?.customization_type;
        const max = ['milk', 'whip', 'sea_salt'].includes(kind) ? 1 : Math.min(3, item?.max_per_drink || 1);
        if (!item?.is_add_on || !Number.isInteger(extra.quantity) || extra.quantity < 1 || extra.quantity > max || extras.has(extra.id) || (kind !== 'extra' && kinds.has(kind))) { valid = false; break; }
        extras.set(extra.id, extra.quantity); kinds.add(kind);
      }
      if (valid) { const line = {id: row.id, quantity: row.quantity, extras}; cart.set(signature(line), line); }
    }
  }
  try { restore(JSON.parse(localStorage.getItem(storageKey))); } catch (_) { /* Storage can be disabled. */ }
  const draftElement = document.getElementById('reorder-data');
  if (draftElement) {
    try {
      const draft = JSON.parse(draftElement.textContent);
      const seenKey = storageKey + '_reorder';
      let seen = null; try { seen = sessionStorage.getItem(seenKey); } catch (_) {}
      if (draft.draft_id && seen !== draft.draft_id && Array.isArray(draft.items)) {
        cart.clear(); restore({time: Date.now(), items: draft.items});
        try { sessionStorage.setItem(seenKey, draft.draft_id); } catch (_) {}
      }
    } catch (_) { /* A failed draft must not interrupt normal menu browsing. */ }
  }
  const serialize = () => [...cart.values()].map(line => ({id: line.id, quantity: line.quantity,
    add_ons: orderedExtras(line.extras).map(([id, quantity]) => ({id, quantity}))}));
  function persist() {
    try { localStorage.setItem(storageKey, JSON.stringify({time: Date.now(), items: serialize()})); } catch (_) {}
  }
  function totals() {
    const subtotal = [...cart.values()].reduce((sum, line) => sum + unitPrice(line) * line.quantity, 0);
    const discount = Math.round(subtotal * Number($('discount')?.value || 0) / 100);
    return {subtotal, discount, total: subtotal - discount};
  }
  function updateChange() {
    if (!$('cash-change')) return;
    const amount = Math.round(Number($('cash-received').value || 0) * 100);
    $('cash-change').textContent = money(Math.max(0, amount - totals().total));
  }
  function groupFor(id) {
    for (const card of document.querySelectorAll('[data-customize]')) {
      const ids = card.dataset.customize.split(',').map(Number);
      if (ids.includes(id)) return ids;
    }
    return [id];
  }
  function render() {
    itemsElement.replaceChildren();
    let count = 0;
    for (const [key, line] of cart) {
      const product = products.get(line.id);
      count += line.quantity;
      const row = node('div', 'cart-item');
      const image = node('img'); image.src = product.image || `/static/img/${product.artwork}.svg`; image.alt = '';
      const info = node('div', 'cart-item-info');
      info.append(node('strong', '', product.name), node('small', '', `${money(unitPrice(line))} per drink`));
      if (line.extras.size) {
        const list = node('ul', 'cart-customizations');
        for (const [id, qty] of orderedExtras(line.extras)) {
          const extra = products.get(id);
          list.append(node('li', '', `+ ${extraDescription(product, extra)}${qty > 1 ? ` × ${qty}` : ''} · ${money(price(extra) * qty)}`));
        }
        info.append(list);
      } else info.append(node('p', 'cart-standard', 'House recipe · no extras'));
      const controls = node('div', 'cart-line-controls');
      const stepper = node('div', 'quantity-stepper');
      const minus = button('−', () => change(key, -1)); minus.setAttribute('aria-label', `One fewer ${product.name}`); minus.disabled = busy;
      const plus = button('+', () => change(key, 1)); plus.setAttribute('aria-label', `One more ${product.name}`); plus.disabled = busy;
      const quantity = node('span', '', String(line.quantity)); quantity.setAttribute('aria-label', 'Quantity');
      stepper.append(minus, quantity, plus);
      const edit = button('Edit drink', () => openEditor(groupFor(line.id), key), 'cart-edit'); edit.disabled = busy;
      edit.setAttribute('aria-label', `Edit ${product.name} and its extras`);
      controls.append(stepper, edit); info.append(controls);
      const right = node('div', 'cart-item-right');
      right.append(node('strong', '', money(unitPrice(line) * line.quantity)));
      const remove = button('Remove', () => { if (!busy) { cart.delete(key); render(); } }); remove.disabled = busy;
      remove.setAttribute('aria-label', `Remove ${product.name} from order`);
      right.append(remove); row.append(image, info, right); itemsElement.append(row);
    }
    $('cart-count').textContent = count;
    if ($('mobile-cart-count')) $('mobile-cart-count').textContent = count;
    if ($('mobile-cart-toggle')) $('mobile-cart-toggle').disabled = count === 0 || busy;
    $('cart-empty').hidden = count > 0;
    $('place-order').disabled = count === 0 || busy;
    const {subtotal, discount, total} = totals();
    $('cart-subtotal').textContent = money(subtotal); $('cart-total').textContent = money(total);
    if ($('mobile-cart-total')) $('mobile-cart-total').textContent = money(total);
    $('cart-discount').textContent = '−' + money(discount); $('cart-discount-row').hidden = discount === 0;
    const cash = $('cash-received');
    if (cash && !cashEdited) cash.value = total ? (total / 100).toFixed(2) : '';
    updateChange(); persist();
  }
  function change(key, delta) {
    if (busy) return;
    const line = cart.get(key), quantity = line.quantity + delta;
    const sameDrinkCount = [...cart.values()].filter(l => l.id === line.id).reduce((n, l) => n + l.quantity, 0);
    if (delta > 0 && (quantity > selectedCapacity(line) || sameDrinkCount >= 99)) { toast('That’s all we can make with the current stock.'); return; }
    if (quantity <= 0) cart.delete(key); else line.quantity = quantity;
    $('checkout-error').hidden = true; render();
  }
  function setKind(kind, id, quantity) {
    for (const selected of [...editor.extras.keys()]) {
      if (products.get(selected).customization_type === kind) editor.extras.delete(selected);
    }
    if (id && quantity > 0) editor.extras.set(id, quantity);
    renderEditor();
  }
  function choice(label, detail, selected, action, control, unavailable = false) {
    const item = button('', action, 'drink-choice');
    item.append(node('span', '', label));
    if (detail) item.append(node('small', '', detail));
    item.setAttribute('aria-pressed', String(selected)); item.dataset.control = control;
    item.disabled = unavailable; return item;
  }
  function extraStepper(extra, quantity, action) {
    const stepper = node('div', 'extra-stepper');
    const minus = button('−', () => action(quantity - 1)); minus.dataset.control = `minus-${extra.id}`;
    minus.setAttribute('aria-label', `Remove one ${extra.extra_label}`); minus.disabled = quantity === 0;
    const output = node('output', '', String(quantity)); output.setAttribute('aria-label', `${extra.extra_label} portions per drink`);
    const plus = button('+', () => action(quantity + 1)); plus.dataset.control = `plus-${extra.id}`;
    plus.setAttribute('aria-label', `Add one ${extra.extra_label}`); plus.disabled = quantity >= Math.min(3, extra.max_per_drink) || quantity >= extra.capacity;
    stepper.append(minus, output, plus); return stepper;
  }
  function renderEditor() {
    if (!editor) return;
    const focusedControl = document.activeElement?.dataset.control;
    const product = products.get(editor.id);
    const variants = editor.group.map(id => products.get(id)).filter(Boolean);
    $('customizer-title').textContent = product.menu_name;
    $('customizer-category').textContent = product.category.toUpperCase();
    $('customizer-description').textContent = product.description;
    $('customizer-base-price').textContent = `Base drink ${money(price(product))}`;
    $('customizer-image').src = product.image || `/static/img/${product.artwork}.svg`;
    $('customizer-image').classList.toggle('is-photo', !!product.image);
    $('customizer-visual').className = `customizer-visual art-${product.artwork}`;
    const servingChoices = $('serving-choices'); servingChoices.replaceChildren();
    for (const serving of new Set(variants.map(v => v.serving))) {
      const candidates = variants.filter(v => v.serving === serving);
      const target = candidates.find(v => v.option === product.option) || candidates[0];
      servingChoices.append(choice(serving, money(price(target)), serving === product.serving, () => {
        editor.id = target.id; renderEditor();
      }, `serving-${target.id}`, candidates.every(v => v.capacity < 1)));
    }
    const options = [...new Set(variants.map(v => v.option).filter(Boolean))];
    $('variant-option-section').hidden = !options.length;
    $('variant-option-label').textContent = product.option_title;
    const variantOptions = $('variant-options'); variantOptions.replaceChildren();
    for (const option of options) {
      const candidates = variants.filter(v => v.option === option);
      const target = candidates.find(v => v.serving === product.serving) || candidates[0];
      variantOptions.append(choice(option, '', option === product.option, () => {
        editor.id = target.id; renderEditor();
      }, `option-${target.id}`, target.capacity < 1));
    }
    const milkOptions = addons.filter(p => p.customization_type === 'milk');
    const selectedMilk = [...editor.extras.keys()].find(id => products.get(id).customization_type === 'milk');
    $('customizer-milk-section').hidden = !milkOptions.length;
    const milkChoices = $('milk-choices'); milkChoices.replaceChildren();
    const hasMilk = Object.values(product.milk_options).some(option => option.mode === 'replace');
    milkChoices.append(choice(hasMilk ? 'Whole milk' : 'House recipe', hasMilk ? 'Included' : 'No added milk', !selectedMilk,
      () => setKind('milk', null, 0), 'milk-standard', product.default_capacity < 1));
    for (const extra of milkOptions) {
      const option = product.milk_options[String(extra.id)];
      milkChoices.append(choice(option?.label || extra.extra_label, `+ ${money(price(extra))}`, selectedMilk === extra.id,
        () => setKind('milk', extra.id, 1), `milk-${extra.id}`, !option?.capacity));
    }
    $('milk-explanation').textContent = hasMilk
      ? 'Oat milk replaces whole milk. Other ingredients, including any cream or condensed milk, stay in the recipe.'
      : 'Keep the house recipe, or add an extra portion of milk. Each choice shows its additional charge.';
    const extraChoices = $('extra-choices'); extraChoices.replaceChildren();
    $('customizer-extras-section').hidden = !addons.some(p => p.customization_type !== 'milk');
    for (const extra of addons.filter(p => p.customization_type === 'espresso')) {
      const row = node('div', 'customizer-extra');
      const label = node('div'); label.append(node('span', 'customizer-extra-title', extra.extra_label), node('small', '', `+ ${money(price(extra))} per extra portion`));
      row.append(label, extraStepper(extra, editor.extras.get(extra.id) || 0, qty => setKind('espresso', extra.id, qty))); extraChoices.append(row);
    }
    const syrups = addons.filter(p => p.customization_type === 'syrup');
    if (syrups.length) {
      const row = node('div', 'customizer-extra syrup-extra');
      const label = node('label'); label.htmlFor = 'extra-syrup';
      label.append(node('span', 'customizer-extra-title', 'Extra syrup'), node('small', '', 'Optional flavour on top of the house recipe'));
      const select = node('select'); select.id = 'extra-syrup'; select.dataset.control = 'syrup';
      const none = node('option', '', 'No extra syrup'); none.value = ''; select.append(none);
      const selected = [...editor.extras.keys()].find(id => products.get(id).customization_type === 'syrup');
      for (const syrup of syrups) {
        const option = node('option', '', `${syrup.variant_label || syrup.extra_label} · + ${money(price(syrup))} per portion`);
        option.value = syrup.id; option.disabled = syrup.capacity < 1; select.append(option);
      }
      select.value = selected || '';
      select.addEventListener('change', () => setKind('syrup', Number(select.value), select.value ? 1 : 0));
      label.append(select); row.append(label);
      if (selected) row.append(extraStepper(products.get(selected), editor.extras.get(selected), qty => setKind('syrup', selected, qty)));
      extraChoices.append(row);
    }
    for (const extra of addons.filter(p => ['whip', 'sea_salt', 'extra'].includes(p.customization_type))) {
      const row = node('div', 'customizer-extra');
      const label = node('label', 'extra-toggle');
      const input = node('input'); input.type = 'checkbox'; input.checked = editor.extras.has(extra.id);
      input.disabled = extra.capacity < 1 && !input.checked; input.dataset.control = `toggle-${extra.id}`;
      input.addEventListener('change', () => { if (input.checked) editor.extras.set(extra.id, 1); else editor.extras.delete(extra.id); renderEditor(); });
      const copy = node('span'); copy.append(node('span', 'customizer-extra-title', extra.extra_label), node('small', '', extra.customization_type === 'whip' && product.category.includes('Frappé') ? 'Adds more cream to the included topping' : 'One extra portion per drink'));
      label.append(input, copy, node('span', 'extra-upcharge', '+ ' + money(price(extra)))); row.append(label); extraChoices.append(row);
    }
    const breakdown = $('customizer-breakdown'); breakdown.replaceChildren();
    const base = node('div', 'breakdown-line base-line'); base.append(node('span', '', product.variant_label || product.name), node('span', '', money(price(product)))); breakdown.append(base);
    for (const [id, qty] of orderedExtras(editor.extras)) {
      const extra = products.get(id), row = node('div', 'breakdown-line');
      row.append(node('span', '', `${extraDescription(product, extra)}${qty > 1 ? ` × ${qty}` : ''}`), node('span', '', '+ ' + money(price(extra) * qty))); breakdown.append(row);
    }
    if (!editor.extras.size) breakdown.append(node('p', 'customizer-help', 'House recipe · no extra charges'));
    $('customizer-unit-price').textContent = money(unitPrice(editor));
    $('customizer-quantity').textContent = editor.quantity;
    $('customizer-total-label').textContent = `${editor.quantity} drink${editor.quantity > 1 ? 's' : ''}${editor.extras.size ? ' · extras on each' : ''}`;
    $('customizer-total').textContent = money(unitPrice(editor) * editor.quantity);
    const capacity = selectedCapacity(editor);
    $('customizer-minus').disabled = editor.quantity <= 1;
    $('customizer-plus').disabled = editor.quantity >= capacity;
    $('customizer-add').disabled = capacity < editor.quantity;
    $('customizer-add').textContent = editor.editKey ? 'Save drink changes' : 'Add to order';
    $('customizer-availability').textContent = capacity < editor.quantity
      ? (!selectedMilk && product.default_capacity === 0 && product.capacity > 0
        ? 'The house milk is unavailable. Choose an available milk option to continue; its price is shown above.'
        : 'This combination is unavailable in that quantity. Change your choices or choose another drink.')
      : 'Extras apply to each drink in this line. Stock is confirmed when you place your order.';
    if (focusedControl) [...dialog.querySelectorAll('[data-control]')].find(e => e.dataset.control === focusedControl)?.focus({preventScroll: true});
  }
  function openEditor(group, key = null) {
    if (busy) return;
    const line = key ? cart.get(key) : null;
    const first = group.map(id => products.get(id)).find(p => p?.capacity > 0) || products.get(group[0]);
    if (!first) return;
    editor = {id: line?.id || first.id, quantity: line?.quantity || 1,
      extras: new Map(line?.extras || []), group, editKey: key};
    renderEditor(); document.body.classList.add('customizer-open'); dialog.showModal(); dialog.scrollTop = 0;
  }
  function closeEditor() { dialog.close(); document.body.classList.remove('customizer-open'); editor = null; }
  document.querySelectorAll('[data-customize]').forEach(button => button.addEventListener('click', () => openEditor(button.dataset.customize.split(',').map(Number))));
  dialog.querySelector('[data-close-customizer]').addEventListener('click', closeEditor);
  dialog.addEventListener('close', () => { document.body.classList.remove('customizer-open'); editor = null; });
  dialog.addEventListener('click', event => { if (event.target === dialog) closeEditor(); });
  $('customizer-minus').addEventListener('click', () => { if (editor && editor.quantity > 1) { editor.quantity--; renderEditor(); } });
  $('customizer-plus').addEventListener('click', () => { if (editor && editor.quantity < selectedCapacity(editor)) { editor.quantity++; renderEditor(); } });
  $('customizer-add').addEventListener('click', () => {
    if (!editor || selectedCapacity(editor) < editor.quantity) return;
    const line = {id: editor.id, quantity: editor.quantity, extras: new Map(editor.extras)}, key = signature(line);
    const otherLines = [...cart].filter(([k]) => k !== editor.editKey);
    const already = otherLines.filter(([, l]) => l.id === line.id).reduce((sum, [, l]) => sum + l.quantity, 0);
    if (already + line.quantity > 99) { toast('Choose at most 99 of the same drink.'); return; }
    const matching = otherLines.find(([k]) => k === key)?.[1];
    if (line.quantity + (matching?.quantity || 0) > selectedCapacity(line)) { toast('Reduce the quantity to match the current stock.'); return; }
    if (!cart.has(key) && cart.size >= 50 && !editor.editKey) { toast('Place this order before adding more drinks.'); return; }
    const wasEdit = Boolean(editor.editKey);
    if (editor.editKey) cart.delete(editor.editKey);
    line.quantity += matching?.quantity || 0; cart.set(key, line);
    closeEditor(); $('checkout-error').hidden = true; render();
    toast(wasEdit ? 'Your drink has been updated.' : `${products.get(line.id).menu_name} added to your order.`);
  });
  function filter() {
    let visible = 0;
    document.querySelectorAll('[data-menu-card]').forEach(card => {
      const show = (category === 'all' || card.dataset.productCategory === category) && card.dataset.productName.toLowerCase().includes(search);
      card.hidden = !show; if (show) visible++;
    });
    document.querySelector('.catalog-no-results').hidden = visible > 0;
  }
  document.querySelectorAll('[data-category]').forEach(button => button.addEventListener('click', () => {
    category = button.dataset.category;
    document.querySelectorAll('[data-category]').forEach(b => { b.classList.toggle('active', b === button); b.setAttribute('aria-pressed', String(b === button)); }); filter();
  }));
  document.querySelector('[data-catalog-search]')?.addEventListener('input', event => { search = event.target.value.trim().toLowerCase(); filter(); });
  $('clear-cart').addEventListener('click', () => { if (!busy && cart.size && window.confirm('Clear the current order?')) { cart.clear(); cashEdited = false; render(); } });
  $('discount')?.addEventListener('change', render);
  $('cash-received')?.addEventListener('input', () => { cashEdited = true; updateChange(); });
  $('order-type').addEventListener('change', event => { $('table-field').hidden = event.target.value !== 'dine_in'; });
  function paymentFields() {
    if (!$('paid-now')) return;
    $('payment-fields').hidden = !$('paid-now').checked;
    const cash = $('payment-method').value === 'cash';
    $('cash-field').hidden = !cash; $('external-payment-note').hidden = cash;
    $('cash-received').required = $('paid-now').checked && cash;
  }
  $('paid-now')?.addEventListener('change', paymentFields);
  $('payment-method')?.addEventListener('change', paymentFields);
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !cart.size) return;
    const error = $('checkout-error'); error.hidden = true;
    const fields = new FormData(form), payload = Object.fromEntries(fields.entries());
    delete payload.csrfmiddlewaretoken;
    payload.items = serialize(); payload.submission_key = root.dataset.submissionKey;
    payload.source = isPublic ? 'online' : 'pos'; payload.paid = !isPublic && $('paid-now').checked;
    busy = true; render();
    const button = $('place-order'), original = button.textContent; button.textContent = 'Brewing your order…';
    try {
      const response = await fetch(root.dataset.submitUrl, {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': fields.get('csrfmiddlewaretoken')}, body: JSON.stringify(payload)});
      let result;
      try { result = await response.json(); } catch (_) { throw new Error('Your session may have expired. Reload this page and sign in again if needed.'); }
      if (!response.ok || !result.ok) throw new Error(result.error || 'We could not place your order. Please try again.');
      cart.clear(); persist(); window.location.assign(result.redirect);
    } catch (problem) {
      error.textContent = problem.message || 'Connection interrupted. Your cart is saved; please try again.';
      error.hidden = false; busy = false; button.textContent = original; render(); error.scrollIntoView({behavior: 'smooth', block: 'nearest'});
    }
  });
  document.querySelectorAll('[data-category]').forEach(button => {
    const active = button.dataset.category === category;
    button.classList.toggle('active', active); button.setAttribute('aria-pressed', String(active));
  });
  const searchInput = document.querySelector('[data-catalog-search]');
  if (searchInput) searchInput.value = root.dataset.initialSearch || '';
  paymentFields(); render(); filter();
})();
