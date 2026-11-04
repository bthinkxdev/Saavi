(function () {
  var variantGroup = document.getElementById('variant-select-group');
  var variantRadios = document.querySelectorAll('.variant-radio');
  if (variantGroup && variantRadios.length > 0) {
    variantRadios.forEach(function (radio) {
      radio.addEventListener('change', function () {
        var url = variantGroup.getAttribute('data-price-url');
        var vid = this.value;

        try {
          var currentUrl = new URL(window.location.href);
          currentUrl.searchParams.set('variant_id', vid);
          if (window.history && window.history.replaceState) {
            window.history.replaceState(null, '', currentUrl.pathname + currentUrl.search + currentUrl.hash);
          }
        } catch (e) { }

        document.querySelectorAll('.pdp-variant-id-input').forEach(function (input) {
          input.value = vid;
        });

        var thumbs = document.querySelectorAll('.jm-pdp-gallery__thumb');
        var firstVisible = null;
        
        thumbs.forEach(function (thumb) {
          //ensure all thumbnails remain visible, rather than hiding other variants
          thumb.style.display = '';
          
          var thumbVid = thumb.getAttribute('data-variant-id');
          //prioritize finding an image specifically tied to this variant
          if (!firstVisible && thumbVid === vid) {
            firstVisible = thumb;
          }
        });

        //if no variant-specific image is found, fallback to the first common image (no variant id)
        if (!firstVisible) {
           thumbs.forEach(function (thumb) {
              var thumbVid = thumb.getAttribute('data-variant-id');
              if (!firstVisible && !thumbVid) {
                  firstVisible = thumb;
              }
           });
        }

        if (thumbs.length > 0 && !firstVisible) {
          var main = document.getElementById('main-pdp-image');
          var mainVideo = document.getElementById('main-pdp-video');
          if (mainVideo) {
            mainVideo.pause();
            mainVideo.classList.add('d-none');
          }
          if (main) {
            main.src = "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='800' viewBox='0 0 800 800'%3E%3Crect width='100%25' height='100%25' fill='%23f1f5f9'/%3E%3C/svg%3E";
            main.classList.remove('d-none');
          }
          document.querySelectorAll('.jm-pdp-gallery__thumb').forEach(function(t) {
            t.classList.remove('active', 'is-active');
          });
        }

        if (firstVisible) {
          firstVisible.click();
        }

        var stickyImg = document.getElementById('pdp-sticky-image');
        if (firstVisible) {
          var thumbImg = firstVisible.querySelector('img');
          if (stickyImg && thumbImg) {
            stickyImg.src = thumbImg.src;
          }
        } else if (thumbs.length > 0) {
          if (stickyImg) {
            stickyImg.src = "data:image/svg+xml;charset=utf-8,%3Csvg xmlns='http://www.w3.org/2000/svg' width='800' height='800' viewBox='0 0 800 800'%3E%3Crect width='100%25' height='100%25' fill='%23f1f5f9'/%3E%3C/svg%3E";
          }
        }

        var qtyInput = document.getElementById('pdp-qty');
        if (qtyInput) qtyInput.value = '1';
        document.querySelectorAll('.pdp-qty-input').forEach(function (input) {
          input.value = '1';
        });
        var qty = '1';
        var queryString = '?quantity=' + qty + (vid ? '&variant_id=' + vid : '');

        fetch(url + queryString)
          .then(function (r) { return r.json(); })
          .then(function (data) {
            var el = document.getElementById('pdp-price');
            var elSticky = document.getElementById('pdp-sticky-price');
            var retailContainer = document.getElementById('pdp-retail-price-container');
            var symbol = variantGroup.getAttribute('data-currency-symbol') || '';
            var elPriceValue = document.getElementById('pdp-price-value');

            if (data.sku) {
              var elSku = document.getElementById('pdp-sku-display');
              if (elSku) elSku.textContent = 'SKU: ' + data.sku;
            }

            if (elPriceValue) {
              elPriceValue.textContent = symbol + ' ' + parseFloat(data.price).toFixed(2).replace(/\.00$/, '');
            }

            var elMrp = document.getElementById('pdp-price-mrp');
            if (elMrp) {
              if (data.is_flash_sale !== 'true' && data.has_mrp_discount === 'true' && data.mrp) {
                elMrp.textContent = symbol + ' ' + parseFloat(data.mrp).toFixed(2).replace(/\.00$/, '');
                elMrp.style.display = 'inline';
              } else {
                elMrp.style.display = 'none';
              }
            }

            if (retailContainer) {
              if (data.is_tier_active === 'true') {
                retailContainer.classList.remove("d-none");
              } else {
                retailContainer.classList.add("d-none");
              }
            }
            if (elSticky) elSticky.textContent = symbol + ' ' + parseFloat(data.price).toFixed(2).replace(/\.00$/, '');
            
            var stickyVariantName = document.getElementById('pdp-sticky-variant-name');
            if (stickyVariantName) {
              var checkedLabel = document.querySelector('label[for="variant_' + vid + '"]');
              if (checkedLabel) {
                 var nameText = checkedLabel.childNodes[0].textContent.trim();
                 stickyVariantName.textContent = nameText;
              }
            }

            var elRetail = document.getElementById('pdp-retail-price');
            if (elRetail && data.retail_price) {
              elRetail.textContent = symbol + ' ' + parseFloat(data.retail_price).toFixed(2).replace(/\.00$/, '');
            }
            var elRetailVal = document.getElementById('pdp-retail-price-val');
            if (elRetailVal && data.retail_price) {
              elRetailVal.value = data.retail_price;
            }

            if (data.is_in_cart !== undefined) {
              var addGroup = document.getElementById('pdp-add-to-cart-group');
              var viewGroup = document.getElementById('pdp-view-cart-group');
              var stickyAdd = document.getElementById('sticky-buy-form');
              var stickyView = document.getElementById('pdp-sticky-view-cart-btn');

              if (data.is_in_cart) {
                if (addGroup) addGroup.classList.add('d-none');
                if (viewGroup) viewGroup.classList.remove('d-none');
                if (stickyAdd) stickyAdd.classList.add('d-none');
                if (stickyView) stickyView.classList.remove('d-none');
              } else {
                if (addGroup) addGroup.classList.remove('d-none');
                if (viewGroup) viewGroup.classList.add('d-none');
                if (stickyAdd) stickyAdd.classList.remove('d-none');
                if (stickyView) stickyView.classList.add('d-none');
              }
            }

            if (data.is_in_stock !== undefined) {
              var atcBtn = document.querySelector('#buy-form button');
              var bnForm = document.getElementById('buy-now-form');
              var qtyStepper = document.querySelector('.jm-pdp-qty');
              var stickyAtcBtn = document.querySelector('#sticky-buy-form button');
              var stickyBnForm = document.getElementById('sticky-buy-now-form');

              if (data.is_in_stock) {
                if (atcBtn) {
                  atcBtn.type = 'submit';
                  atcBtn.classList.remove('disabled');
                  atcBtn.style.cursor = 'pointer';
                  atcBtn.style.opacity = '1';
                  atcBtn.style.pointerEvents = 'auto';
                  atcBtn.onclick = null;
                  atcBtn.textContent = 'Add to Cart';
                }
                if (stickyAtcBtn) {
                  stickyAtcBtn.type = 'submit';
                  stickyAtcBtn.classList.remove('disabled');
                  stickyAtcBtn.style.cursor = 'pointer';
                  stickyAtcBtn.style.opacity = '1';
                  stickyAtcBtn.style.pointerEvents = 'auto';
                  stickyAtcBtn.onclick = null;
                  var stText = stickyAtcBtn.querySelector('.btn-text');
                  if (stText) stText.textContent = 'Add to cart';
                  else stickyAtcBtn.textContent = 'Add to cart';
                }
                if (bnForm) bnForm.classList.remove('d-none');
                if (stickyBnForm) stickyBnForm.classList.remove('d-none');
                if (qtyStepper) qtyStepper.style.opacity = '1';
              } else {
                if (atcBtn) {
                  atcBtn.type = 'button';
                  atcBtn.classList.add('disabled');
                  atcBtn.style.cursor = 'not-allowed';
                  atcBtn.style.opacity = '0.6';
                  atcBtn.style.pointerEvents = 'auto';
                  atcBtn.onclick = function (e) { e.preventDefault(); return false; };
                  atcBtn.textContent = 'Sold out';
                }
                if (stickyAtcBtn) {
                  stickyAtcBtn.type = 'button';
                  stickyAtcBtn.classList.add('disabled');
                  stickyAtcBtn.style.cursor = 'not-allowed';
                  stickyAtcBtn.style.opacity = '0.6';
                  stickyAtcBtn.style.pointerEvents = 'auto';
                  stickyAtcBtn.onclick = function (e) { e.preventDefault(); return false; };
                  var stText = stickyAtcBtn.querySelector('.btn-text');
                  if (stText) stText.textContent = 'Sold out';
                  else stickyAtcBtn.textContent = 'Sold out';
                }
                if (bnForm) bnForm.classList.add('d-none');
                if (stickyBnForm) stickyBnForm.classList.add('d-none');
                if (qtyStepper) qtyStepper.style.opacity = '0.5';
              }

              var stockText = document.getElementById('pdp-stock-text');
              if (stockText) {
                if (data.is_in_stock) {
                  stockText.classList.remove('is-out');
                  if (data.stock_quantity !== undefined && data.low_stock_threshold !== undefined && data.stock_quantity <= data.low_stock_threshold) {
                    stockText.classList.remove('is-in');
                    stockText.classList.add('is-low');
                    stockText.innerHTML = 'Only ' + data.stock_quantity + ' left';
                  } else {
                    stockText.classList.remove('is-low');
                    stockText.classList.add('is-in');
                    stockText.innerHTML = 'In stock';
                  }
                } else {
                  stockText.classList.remove('is-in');
                  stockText.classList.remove('is-low');
                  stockText.classList.add('is-out');
                  stockText.textContent = 'Out of stock';
                }
              }
            }
            if (data.stock_quantity !== undefined) {
              var qtyInput = document.getElementById('pdp-qty');
              if (qtyInput) qtyInput.setAttribute('data-max-stock', data.stock_quantity);
            }
            if (window.validatePdpStock) window.validatePdpStock();
          });
      });
    });

    var urlParams = new URLSearchParams(window.location.search);
    var urlVid = urlParams.get('variant_id');
    var radioToSelect = null;
    if (urlVid) {
      radioToSelect = document.querySelector('.variant-radio[value="' + urlVid + '"]');
    }
    if (!radioToSelect) {
      radioToSelect = document.querySelector('.variant-radio:checked');
    }
    if (radioToSelect) {
      radioToSelect.checked = true;
      radioToSelect.dispatchEvent(new Event('change'));
    }
  }

  var citySelect = document.getElementById('delivery-city');
  if (citySelect) {
    citySelect.addEventListener('change', function () {
      if (!this.value) {
        return;
      }
      var url = this.getAttribute('data-estimate-url') + '?city=' + encodeURIComponent(this.value);
      fetch(url)
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var el = document.getElementById('delivery-estimate-text');
          if (el) el.textContent = 'Delivery: ' + data.label + ' to ' + data.city;
        });
    });
  }

  window.handlePdpQtyChange = function (delta) {
    var qtyInput = document.getElementById('pdp-qty');
    if (!qtyInput) return;
    var maxStock = parseInt(qtyInput.getAttribute('data-max-stock'));
    var currQty = parseInt(qtyInput.value) || 1;
    var errorMsg = document.getElementById('pdp-stock-error-msg');

    if (delta > 0 && !isNaN(maxStock) && currQty >= maxStock) {
      if (errorMsg) {
        errorMsg.textContent = maxStock <= 0 ? 'Out of stock' : 'Only ' + maxStock + ' items available in stock.';
        errorMsg.classList.remove('d-none');
      }
      return;
    }

    var newQty = currQty + delta;
    if (newQty < 1) newQty = 1;
    qtyInput.value = newQty;
    document.querySelectorAll('.pdp-qty-input').forEach(function (i) { i.value = newQty; });

    if (errorMsg) {
      errorMsg.classList.add('d-none');
      errorMsg.textContent = '';
    }
    if (window.validatePdpStock) window.validatePdpStock();
  };

  window.validatePdpStock = function () {
    var qtyInput = document.getElementById('pdp-qty');
    if (!qtyInput) return;
    var maxStock = parseInt(qtyInput.getAttribute('data-max-stock'));
    if (isNaN(maxStock)) return;
    var currQty = parseInt(qtyInput.value) || 1;
    var errorMsg = document.getElementById('pdp-stock-error-msg');
    var atcBtn = document.querySelector('#buy-form button');
    var bnBtn = document.querySelector('#buy-now-form button');
    var stickyAtcBtn = document.querySelector('#sticky-buy-form button');
    var stickyBnBtn = document.querySelector('#sticky-buy-now-form button');
    var allBtns = [atcBtn, bnBtn, stickyAtcBtn, stickyBnBtn].filter(Boolean);

    if (currQty > maxStock && maxStock > 0) {
      currQty = maxStock;
      qtyInput.value = maxStock;
      document.querySelectorAll('.pdp-qty-input').forEach(function (i) { i.value = maxStock; });
    }

    if (maxStock <= 0) {
      if (errorMsg) {
        errorMsg.textContent = '';
        errorMsg.classList.add('d-none');
      }
      allBtns.forEach(function (btn) {
        btn.type = 'button';
        btn.classList.add('disabled');
        btn.style.cursor = 'not-allowed';
        btn.style.opacity = '0.6';
        btn.style.pointerEvents = 'auto';
        btn.onclick = function (e) { e.preventDefault(); return false; };
      });
      if (atcBtn) atcBtn.textContent = 'Sold out';
      if (stickyAtcBtn) {
        var stText = stickyAtcBtn.querySelector('.btn-text');
        if (stText) stText.textContent = 'Sold out';
        else stickyAtcBtn.textContent = 'Sold out';
      }
    } else {
      if (errorMsg) {
        errorMsg.textContent = '';
        errorMsg.classList.add('d-none');
      }
      allBtns.forEach(function (btn) {
        btn.type = 'submit';
        btn.classList.remove('disabled');
        btn.style.cursor = 'pointer';
        btn.style.opacity = '1';
        btn.style.pointerEvents = 'auto';
        btn.onclick = null;
      });
      if (atcBtn) atcBtn.textContent = 'Add to Cart';
      if (stickyAtcBtn) {
        var stText = stickyAtcBtn.querySelector('.btn-text');
        if (stText) stText.textContent = 'Add to cart';
        else stickyAtcBtn.textContent = 'Add to cart';
      }
    }
  };

  if (window.validatePdpStock) window.validatePdpStock();

  //gallery media grouping and two-way synced
  document.addEventListener("DOMContentLoaded", function() {
    var thumbsContainer = document.querySelector('.jm-pdp-gallery__thumbs');
    if (thumbsContainer) {
        var thumbs = Array.from(thumbsContainer.querySelectorAll('.jm-pdp-gallery__thumb'));
        var groupedThumbs = {};
        var commonThumbs = [];

        //group by variant ID
        thumbs.forEach(function(thumb) {
            var variantId = thumb.getAttribute('data-variant-id');
            if (variantId) {
                if (!groupedThumbs[variantId]) groupedThumbs[variantId] = [];
                groupedThumbs[variantId].push(thumb);
            } else {
                commonThumbs.push(thumb);
            }
        });

        //variant-specific media first, then common media last)
        thumbsContainer.innerHTML = '';
        Object.values(groupedThumbs).forEach(function(group) {
            group.forEach(function(thumb) { thumbsContainer.appendChild(thumb); });
        });
        commonThumbs.forEach(function(thumb) { thumbsContainer.appendChild(thumb); });
    }

    document.querySelectorAll('.jm-pdp-gallery__thumb').forEach(function(thumb) {
        thumb.addEventListener('click', function() {
            var vid = this.getAttribute('data-variant-id');
            if (vid) {
                var radio = document.querySelector('input.variant-radio[value="' + vid + '"]');
                if (radio && !radio.checked) {
                    radio.checked = true;
                    radio.dispatchEvent(new Event('change'));
                }
            }
        });
    });

    initPdpGalleryZoom();
  });

  // PDP gallery fullscreen zoom
  function initPdpGalleryZoom() {
    var modal = document.getElementById('pdpGalleryModal'),
        box = document.getElementById('pdp-modal-container'),
        img = document.getElementById('pdp-modal-img'),
        vp = document.getElementById('pdp-modal-viewport'),
        counter = document.getElementById('pdp-modal-counter'),
        scale = 1, panX = 0, panY = 0, cur = 0,
        startX = 0, startY = 0, lastX = 0, lastY = 0, lastTap = 0,
        startDist = 0, startScale = 1, midX = 0, midY = 0, initPanX = 0, initPanY = 0;

    if (!modal || !box || !img || !vp) return;

    function getList() {
      var thumbs = Array.from(document.querySelectorAll('.jm-pdp-gallery__thumb[data-full]'));
      return thumbs.length ? thumbs.map(function(t) { return t.getAttribute('data-full'); }) : (img.src ? [img.src] : []);
    }

    function update(anim) {
      var w = Math.max(0, (img.offsetWidth * scale - vp.offsetWidth) / 2);
      var h = Math.max(0, (img.offsetHeight * scale - vp.offsetHeight) / 2);
      panX = scale <= 1 ? 0 : Math.max(-w, Math.min(w, panX));
      panY = scale <= 1 ? 0 : Math.max(-h, Math.min(h, panY));
      box.style.transition = anim ? 'transform .25s ease-out' : 'none';
      box.style.transform = 'translate(' + panX.toFixed(1) + 'px,' + panY.toFixed(1) + 'px) scale(' + scale.toFixed(2) + ')';
    }

    function zoomAt(x, y, s) {
      var r = vp.getBoundingClientRect();
      scale = Math.max(1, Math.min(4, s));
      panX = scale <= 1 ? 0 : -(x - (r.left + r.width / 2)) * (scale - 1);
      panY = scale <= 1 ? 0 : -(y - (r.top + r.height / 2)) * (scale - 1);
      update(true);
    }

    function setImg(i) {
      var list = getList();
      if (!list.length) return;
      cur = (i + list.length) % list.length;
      img.src = list[cur];
      scale = 1; update();
      if (counter) counter.textContent = (cur + 1) + ' / ' + list.length;
      document.querySelectorAll('.pdp-modal-thumb-btn').forEach(function(b, k) {
        b.classList.toggle('border-primary', k === cur);
        b.classList.toggle('border-2', k === cur);
        b.classList.toggle('opacity-50', k !== cur);
      });
    }

    modal.addEventListener('show.bs.modal', function() {
      var active = document.querySelector('.jm-pdp-gallery__thumb.is-active, .jm-pdp-gallery__thumb.active');
      var list = getList(), idx = active ? list.indexOf(active.getAttribute('data-full')) : 0;
      setImg(idx > -1 ? idx : 0);
    });

    var prevBtn = document.getElementById('pdp-modal-prev'), nextBtn = document.getElementById('pdp-modal-next');
    if (prevBtn) prevBtn.addEventListener('click', function() { setImg(cur - 1); });
    if (nextBtn) nextBtn.addEventListener('click', function() { setImg(cur + 1); });
    document.addEventListener('click', function(e) {
      var b = e.target.closest('.pdp-modal-thumb-btn');
      if (b) setImg(parseInt(b.getAttribute('data-idx'), 10) || 0);
    });

    // touch: pinch, pan, swipe, double-tap
    vp.addEventListener('touchstart', function(e) {
      var t = e.touches;
      if (t.length === 2) {
        startDist = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
        startScale = scale;
        midX = (t[0].clientX + t[1].clientX) / 2;
        midY = (t[0].clientY + t[1].clientY) / 2;
        initPanX = panX; initPanY = panY;
      } else if (t.length === 1) {
        startX = t[0].clientX; startY = t[0].clientY;
        lastX = panX; lastY = panY;
      }
    }, { passive: true });

    vp.addEventListener('touchmove', function(e) {
      var t = e.touches;
      if (t.length === 2 && startDist > 0) {
        if (e.cancelable) e.preventDefault();
        var d = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
        scale = Math.max(1, Math.min(4, startScale * (d / startDist)));
        var curMidX = (t[0].clientX + t[1].clientX) / 2, curMidY = (t[0].clientY + t[1].clientY) / 2;
        var r = vp.getBoundingClientRect(), ox = midX - (r.left + r.width / 2), oy = midY - (r.top + r.height / 2);
        panX = ox - (ox - initPanX) * (scale / startScale) + (curMidX - midX);
        panY = oy - (oy - initPanY) * (scale / startScale) + (curMidY - midY);
        update(false);
      } else if (t.length === 1 && scale > 1) {
        if (e.cancelable) e.preventDefault();
        panX = lastX + (t[0].clientX - startX);
        panY = lastY + (t[0].clientY - startY);
        update(false);
      }
    }, { passive: false });

    vp.addEventListener('touchend', function(e) {
      if (e.touches.length === 0) {
        var t = e.changedTouches[0], now = Date.now();
        if (scale > 1) { update(true); }
        else if (Math.abs(t.clientX - startX) > 50) { setImg(t.clientX < startX ? cur + 1 : cur - 1); }
        if (now - lastTap < 300) { zoomAt(t.clientX, t.clientY, scale > 1.2 ? 1 : 2.5); lastTap = 0; }
        else { lastTap = now; }
      }
    });

    // desktop: double-click, wheel, drag
    vp.addEventListener('dblclick', function(e) { zoomAt(e.clientX, e.clientY, scale > 1.2 ? 1 : 2.5); });
    vp.addEventListener('wheel', function(e) {
      e.preventDefault();
      zoomAt(e.clientX, e.clientY, scale * (e.deltaY < 0 ? 1.25 : 0.8));
    }, { passive: false });

    var dragging = false;
    vp.addEventListener('mousedown', function(e) {
      if (scale > 1) { dragging = true; startX = e.clientX; startY = e.clientY; lastX = panX; lastY = panY; }
    });
    window.addEventListener('mousemove', function(e) {
      if (dragging) { panX = lastX + (e.clientX - startX); panY = lastY + (e.clientY - startY); update(false); }
    });
    window.addEventListener('mouseup', function() { if (dragging) { dragging = false; update(true); } });
  }

})();
