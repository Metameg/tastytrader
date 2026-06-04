(function () {
  'use strict';

  /* ── Element refs ─────────────────────────────── */
  var overlay  = document.getElementById('order-modal-overlay');
  var form     = document.getElementById('order-form');
  var feedback = document.getElementById('order-feedback');
  var btnOpen  = document.getElementById('btn-new-order');
  var btnClose = document.getElementById('order-modal-close');
  var symbolIn = document.getElementById('of-symbol');
  var actionIn = document.getElementById('of-action');
  var qtyIn    = document.getElementById('of-quantity');
  var priceIn  = document.getElementById('of-limit-price');
  var sideTabs = document.querySelectorAll('.order-side-tab');
  var placeBtn = document.getElementById('btn-place-order');

  if (!overlay || !form) return;

  /* ── Open / close ─────────────────────────────── */
  function openModal() {
    overlay.removeAttribute('hidden');
    if (symbolIn) symbolIn.focus();
  }

  function closeModal() {
    overlay.setAttribute('hidden', '');
    form.reset();
    if (actionIn) actionIn.value = 'Buy to Open';
    setActiveSide('Buy to Open');
    setFeedback('', null);
  }

  btnOpen && btnOpen.addEventListener('click', openModal);
  btnClose && btnClose.addEventListener('click', closeModal);

  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) closeModal();
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !overlay.hasAttribute('hidden')) closeModal();
  });

  /* ── Buy / Sell side tabs ─────────────────────── */
  function setActiveSide(action) {
    if (actionIn) actionIn.value = action;
    var isSell = action === 'Sell to Close';
    sideTabs.forEach(function (tab) {
      tab.classList.toggle('active', tab.dataset.action === action);
    });
    if (placeBtn) placeBtn.classList.toggle('place-order-sell', isSell);
  }

  sideTabs.forEach(function (tab) {
    tab.addEventListener('click', function () { setActiveSide(tab.dataset.action); });
  });

  /* ── Symbol → auto-fill ask price ─────────────── */
  var quoteTimer = null;

  function fetchAsk(sym) {
    if (!sym) return;
    fetch('/api/quotes/' + encodeURIComponent(sym))
      .then(function (r) { return r.json(); })
      .then(function (q) {
        if (q && q.ask != null && priceIn && !priceIn.value) {
          priceIn.value = q.ask.toFixed(2);
        }
      })
      .catch(function () {});
  }

  if (symbolIn) {
    symbolIn.addEventListener('input', function () {
      var sym = symbolIn.value.toUpperCase();
      symbolIn.value = sym;
      clearTimeout(quoteTimer);
      if (sym.length >= 1) {
        quoteTimer = setTimeout(function () { fetchAsk(sym); }, 450);
      } else {
        if (priceIn) priceIn.value = '';
      }
    });

    symbolIn.addEventListener('blur', function () {
      var sym = symbolIn.value.trim().toUpperCase();
      symbolIn.value = sym;
      if (sym && priceIn && !priceIn.value) fetchAsk(sym);
    });
  }

  /* ── Form submit ──────────────────────────────── */
  form.addEventListener('submit', function (event) {
    event.preventDefault();

    var symbol     = symbolIn ? symbolIn.value.trim().toUpperCase() : '';
    var instrType  = (document.getElementById('of-instrument-type') || {}).value || 'Equity';
    var action     = actionIn ? actionIn.value : 'Buy to Open';
    var quantity   = qtyIn ? qtyIn.value : '';
    var limitPrice = priceIn ? priceIn.value : '';

    if (!symbol)     { setFeedback('Symbol is required', 'err'); return; }
    if (!quantity)   { setFeedback('Quantity is required', 'err'); return; }
    if (!limitPrice) { setFeedback('Limit price is required', 'err'); return; }

    setFeedback('Placing order…', null);
    if (placeBtn) placeBtn.disabled = true;

    fetch('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol:          symbol,
        instrument_type: instrType,
        action:          action,
        quantity:        quantity,
        limit_price:     limitPrice,
      }),
    })
      .then(function (resp) {
        return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
      })
      .then(function (result) {
        if (placeBtn) placeBtn.disabled = false;
        if (result.ok) {
          setFeedback('Order ' + result.data.order_id + ' placed', 'ok');
          setTimeout(closeModal, 1400);
        } else {
          setFeedback(result.data.error || 'Order failed', 'err');
        }
      })
      .catch(function () {
        if (placeBtn) placeBtn.disabled = false;
        setFeedback('Network error', 'err');
      });
  });

  function setFeedback(msg, type) {
    if (!feedback) return;
    feedback.textContent = msg;
    feedback.className = 'order-feedback' + (type ? ' feedback-' + type : '');
  }

})();
