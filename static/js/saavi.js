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
    if (e.target.closest('[data-sv-address-new]')) {
      fill(form, null);
      var m = modal();
      if (m) m.show();
    }
    var card = e.target.closest('[data-address]');
    if (!card) return;
    var data = null;
    try { data = JSON.parse(card.getAttribute('data-address')); } catch (err) {}
    if (e.target.closest('[data-sv-address-edit]')) {
      fill(form, data);
      var m = modal();
      if (m) m.show();
    }
    if (e.target.closest('[data-sv-address-delete]')) {
      if (!confirm('Delete this address?')) return;
      fetch(form.dataset.detailUrl.replace('/0/', '/' + data.id + '/'), { method: 'DELETE', headers: { 'X-CSRFToken': csrf() } })
        .then(function () { window.location.reload(); });
    }
  });
  document.addEventListener('submit', function (e) {
    var form = e.target;
    if (!form || form.getAttribute('id') !== 'svAddressForm') return;
    e.preventDefault();
    var id = (form.elements.id && form.elements.id.value) || '';
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
/* PLP price range slider (values are base currency; labels show display currency) */
(function () {
  function fmt(box, v) { var r = parseFloat(box.dataset.rate) || 1; return (box.dataset.symbol || '') + Math.round(v / r).toLocaleString('en-US'); }
  function init(root) {
    root.querySelectorAll('[data-sv-range]').forEach(function (box) {
      if (box.dataset.ready) return; box.dataset.ready = '1';
      var lo = box.querySelector('[data-sv-range-lo]'), hi = box.querySelector('[data-sv-range-hi]');
      var fill = box.querySelector('.sv-range__fill'), min = +box.dataset.min, max = +box.dataset.max;
      var form = box.closest('form');
      function paint() {
        if (+lo.value > +hi.value) { var t = lo.value; lo.value = hi.value; hi.value = t; }
        var a = (lo.value - min) / ((max - min) || 1) * 100, b = (hi.value - min) / ((max - min) || 1) * 100;
        fill.style.left = a + '%'; fill.style.width = (b - a) + '%';
        box.querySelector('[data-sv-range-lo-label]').textContent = fmt(box, lo.value);
        box.querySelector('[data-sv-range-hi-label]').textContent = fmt(box, hi.value);
      }
      function commit() {
        form.elements.min_price.value = +lo.value > min ? lo.value : '';
        form.elements.max_price.value = +hi.value < max ? hi.value : '';
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
      }
      [lo, hi].forEach(function (el) {
        el.addEventListener('input', function (e) { e.stopPropagation(); paint(); });
        el.addEventListener('change', function (e) { e.stopPropagation(); commit(); });
      });
      paint();
    });
  }
  document.addEventListener('DOMContentLoaded', function () { init(document); });
  document.addEventListener('htmx:afterSwap', function (e) { init(e.target); });
  document.addEventListener('click', function (e) {
    var m = e.target.closest('[data-sv-more]');
    if (m) { m.closest('.sv-filter__body').classList.add('show-all'); m.remove(); }
  });
})();
/* Mobile top bar: rotate trust messages */
(function () {
  document.addEventListener('DOMContentLoaded', function () {
    var bar = document.querySelector('[data-sv-ticker]'); if (!bar) return;
    var items = bar.querySelectorAll('[data-sv-tick]'), i = 0;
    function show(n) { i = (n + items.length) % items.length; items.forEach(function (it, k) { it.classList.toggle('is-on', k === i); }); }
    bar.addEventListener('click', function (e) { var b = e.target.closest('[data-sv-step]'); if (b) show(i + (+b.dataset.svStep)); });
    show(0); setInterval(function () { if (window.innerWidth < 768) show(i + 1); }, 4500);
  });
})();
/* PDP: thumbnail arrows + selected variant name */
document.addEventListener('click', function (e) {
  var b = e.target.closest('[data-sv-thumbs]');
  if (!b) return;
  var list = b.parentElement.querySelector('.jm-pdp-gallery__thumbs');
  var vertical = list.scrollHeight > list.clientHeight + 4;
  var d = (+b.getAttribute('data-sv-thumbs')) * 110;
  list.scrollBy(vertical ? { top: d, behavior: 'smooth' } : { left: d, behavior: 'smooth' });
});
document.addEventListener('change', function (e) {
  if (!e.target.matches('.variant-radio')) return;
  var lab = document.querySelector('label[for="' + e.target.id + '"]');
  var out = document.querySelector('[data-sv-variant-name]');
  if (lab && out) out.textContent = lab.getAttribute('data-name') || lab.textContent.trim();
});
window.addEventListener('pageshow', function () { if (window.htmx) htmx.trigger('#cart-count-badge', 'cartUpdated'); });
