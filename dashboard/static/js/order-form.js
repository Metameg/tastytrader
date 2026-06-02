/* order-form.js — vanilla JS, no build step */
(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var form = document.getElementById('order-form');
    if (!form) { return; }

    form.addEventListener('submit', function (event) {
      event.preventDefault();

      var symbol = document.getElementById('of-symbol').value.trim();
      var instrumentType = document.getElementById('of-instrument-type').value;
      var action = document.getElementById('of-action').value;
      var quantity = document.getElementById('of-quantity').value;
      var limitPrice = document.getElementById('of-limit-price').value;
      var feedback = document.getElementById('order-feedback');

      fetch('/api/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol,
          instrument_type: instrumentType,
          action: action,
          quantity: quantity,
          limit_price: limitPrice,
        }),
      })
        .then(function (resp) {
          return resp.json().then(function (data) {
            return { ok: resp.ok, data: data };
          });
        })
        .then(function (result) {
          if (result.ok) {
            feedback.textContent = 'Order placed: ' + result.data.order_id;
            feedback.classList.remove('feedback-error');
            feedback.classList.add('feedback-success');
          } else {
            feedback.textContent = result.data.error || 'Order failed';
            feedback.classList.remove('feedback-success');
            feedback.classList.add('feedback-error');
          }
        })
        .catch(function () {
          feedback.textContent = 'Network error — could not place order';
          feedback.classList.remove('feedback-success');
          feedback.classList.add('feedback-error');
        });
    });
  });
})();
