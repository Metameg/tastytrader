(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', function () {
    var form     = document.getElementById('order-form');
    var feedback = document.getElementById('order-feedback');
    if (!form) return;

    form.addEventListener('submit', function (event) {
      event.preventDefault();

      var symbol      = document.getElementById('of-symbol').value.trim().toUpperCase();
      var instrType   = document.getElementById('of-instrument-type').value;
      var action      = document.getElementById('of-action').value;
      var quantity    = document.getElementById('of-quantity').value;
      var limitPrice  = document.getElementById('of-limit-price').value;

      setFeedback('', null);

      fetch('/api/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbol: symbol,
          instrument_type: instrType,
          action: action,
          quantity: quantity,
          limit_price: limitPrice,
        }),
      })
        .then(function (resp) {
          return resp.json().then(function (data) { return { ok: resp.ok, data: data }; });
        })
        .then(function (result) {
          if (result.ok) {
            setFeedback('order ' + result.data.order_id + ' placed', 'ok');
            document.getElementById('of-symbol').value = '';
            document.getElementById('of-quantity').value = '';
            document.getElementById('of-limit-price').value = '';
          } else {
            setFeedback(result.data.error || 'order failed', 'err');
          }
        })
        .catch(function () {
          setFeedback('network error', 'err');
        });
    });

    function setFeedback(msg, type) {
      feedback.textContent = msg;
      feedback.className = 'order-feedback' + (type ? ' feedback-' + type : '');
    }
  });
})();
