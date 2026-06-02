(function () {
  'use strict';

  const dot = document.querySelector('.status-dot');

  // --- SSE connection ---
  const es = new EventSource('/stream/live');

  es.onopen = function () {
    if (dot) { dot.className = 'status-dot connected'; }
  };

  es.onerror = function () {
    if (dot) { dot.className = 'status-dot disconnected'; }
  };

  // --- Event: quote — update mark price cell for symbol ---
  es.addEventListener('quote', function (e) {
    const data = JSON.parse(e.data);
    const row = document.querySelector('[data-symbol="' + CSS.escape(data.symbol) + '"]');
    if (!row) return;
    const cells = row.querySelectorAll('td');
    if (cells[4]) {
      cells[4].textContent = data.last != null ? data.last.toFixed(2) : '—';
    }
  });

  // --- Event: positions — re-render positions table body ---
  es.addEventListener('positions', function (e) {
    const data = JSON.parse(e.data);
    const tbody = document.querySelector('#positions-table tbody');
    if (!tbody) return;
    if (!data.positions || data.positions.length === 0) {
      tbody.innerHTML = '<tr class="placeholder-row"><td colspan="7">no positions</td></tr>';
      return;
    }
    tbody.innerHTML = data.positions.map(function (pos) {
      return '<tr data-symbol="' + esc(pos.symbol) + '">' +
        '<td>' + esc(pos.symbol) + '</td>' +
        '<td>' + esc(pos.instrument_type || '—') + '</td>' +
        '<td>' + (pos.quantity || '—') + '</td>' +
        '<td>' + esc(pos.avg_cost || '—') + '</td>' +
        '<td class="neutral">—</td>' +
        '<td class="neutral">—</td>' +
        '<td class="neutral">—</td>' +
        '</tr>';
    }).join('');
  });

  // --- Event: account — update header values ---
  es.addEventListener('account', function (e) {
    const data = JSON.parse(e.data);
    const nlv = document.querySelector('.header-nlv .value');
    const bp = document.querySelector('.header-bp .value');
    const acct = document.querySelector('.header-account');
    if (nlv) nlv.textContent = data.net_liquidating_value || '—';
    if (bp) bp.textContent = data.buying_power || '—';
    if (acct) acct.textContent = data.account_number || '—';
  });

  // --- Event: orders — re-render orders list ---
  es.addEventListener('orders', function (e) {
    const data = JSON.parse(e.data);
    const container = document.querySelector('#orders-list');
    if (!container) return;
    if (!data.orders || data.orders.length === 0) {
      container.innerHTML = '<div class="orders-empty">no open orders</div>';
      return;
    }
    container.innerHTML =
      '<table class="orders-table"><thead><tr>' +
      '<th>symbol</th><th>action</th><th>type</th><th>qty</th><th>price</th><th>status</th><th>time</th>' +
      '</tr></thead><tbody>' +
      data.orders.map(function (o) {
        return '<tr>' +
          '<td>' + esc(o.symbol) + '</td>' +
          '<td>' + esc(o.action) + '</td>' +
          '<td>' + esc(o.order_type) + '</td>' +
          '<td>' + (o.quantity || '—') + '</td>' +
          '<td>' + esc(o.price) + '</td>' +
          '<td>' + esc(o.status) + '</td>' +
          '<td>' + esc(o.time) + '</td>' +
          '</tr>';
      }).join('') +
      '</tbody></table>';
  });

  function esc(s) {
    if (s == null) return '—';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
