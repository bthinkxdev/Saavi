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
