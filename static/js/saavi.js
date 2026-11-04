/* Saavi storefront helpers: tabs, qty steppers, simple toggles. */
(function () {
  function initTabs(root) {
    root.querySelectorAll('[data-sv-tabs]').forEach(function (box) {
      if (box.dataset.svTabsReady) return;
      box.dataset.svTabsReady = '1';
      box.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-sv-tab]');
        if (!btn || !box.contains(btn)) return;
        var id = btn.getAttribute('data-sv-tab');
        box.querySelectorAll('[data-sv-tab]').forEach(function (b) {
          var on = b === btn;
          b.classList.toggle('is-active', on);
          b.setAttribute('aria-selected', on ? 'true' : 'false');
        });
        box.querySelectorAll('[data-sv-panel]').forEach(function (p) {
          p.hidden = p.getAttribute('data-sv-panel') !== id;
        });
      });
    });
  }
  document.addEventListener('DOMContentLoaded', function () { initTabs(document); });
  document.addEventListener('htmx:afterSwap', function (e) { initTabs(e.target); });
})();
(function () {
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-sv-view]');
    if (!b) return;
    var grid = document.getElementById('product-grid');
    if (!grid) return;
    document.querySelectorAll('[data-sv-view]').forEach(function (x) { x.classList.toggle('is-active', x === b); });
    grid.classList.toggle('is-list', b.getAttribute('data-sv-view') === 'list');
  });
})();
document.addEventListener('click', function (e) {
  var a = e.target.closest('[data-sv-open-tab]');
  if (!a) return;
  var btn = document.querySelector('[data-sv-tab="' + a.getAttribute('data-sv-open-tab') + '"]');
  if (btn) btn.click();
});
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-sv-orders] [data-filter]');
  if (!b) return;
  var box = b.closest('[data-sv-orders]'), f = b.getAttribute('data-filter');
  box.querySelectorAll('[data-filter]').forEach(function (x) { x.classList.toggle('is-active', x === b); });
  box.querySelectorAll('tr[data-group]').forEach(function (r) { r.hidden = f !== 'all' && r.getAttribute('data-group') !== f; });
});
document.addEventListener('change', function (e) {
  var t = e.target;
  if (t.matches('[data-sv-billing-toggle]')) {
    var box = document.querySelector('[data-sv-billing]');
    if (box) box.hidden = t.checked;
  }
});
/* Saved addresses (My Account): add / edit / delete via the accounts address API */
(function () {
  function csrf() { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ''; }
  function modal() { var el = document.getElementById('svAddressModal'); return el && window.bootstrap ? bootstrap.Modal.getOrCreateInstance(el) : null; }
  function fill(form, data) {
    ['id', 'label', 'line1', 'line2', 'city', 'state', 'pincode'].forEach(function (k) { form.elements[k].value = (data && data[k]) || ''; });
    form.elements.is_default.checked = !!(data && data.is_default);
    form.querySelector('[data-sv-address-error]').hidden = true;
  }
  document.addEventListener('click', function (e) {
    var form = document.getElementById('svAddressForm');
    if (!form) return;
    if (e.target.closest('[data-sv-address-new]')) { fill(form, null); modal().show(); }
    var card = e.target.closest('[data-address]');
    if (!card) return;
    var data = JSON.parse(card.getAttribute('data-address'));
    if (e.target.closest('[data-sv-address-edit]')) { fill(form, data); modal().show(); }
    if (e.target.closest('[data-sv-address-delete]')) {
      if (!confirm('Delete this address?')) return;
      fetch(form.dataset.detailUrl.replace('/0/', '/' + data.id + '/'), { method: 'DELETE', headers: { 'X-CSRFToken': csrf() } })
        .then(function () { window.location.reload(); });
    }
  });
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (form.id !== 'svAddressForm') return;
    e.preventDefault();
    var id = form.elements.id.value;
    var body = {};
    ['label', 'line1', 'line2', 'city', 'state', 'pincode'].forEach(function (k) { body[k] = form.elements[k].value.trim(); });
    body.is_default = form.elements.is_default.checked;
    var url = id ? form.dataset.detailUrl.replace('/0/', '/' + id + '/') : form.dataset.createUrl;
    fetch(url, { method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(body) })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (res.ok && res.j.success !== false) { window.location.reload(); return; }
        var err = form.querySelector('[data-sv-address-error]');
        err.textContent = (res.j.error && (res.j.error.message || res.j.error)) || 'Please check the address details.';
        err.hidden = false;
      });
  });
})();
