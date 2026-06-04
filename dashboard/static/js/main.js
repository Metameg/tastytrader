/* ── Dollar formatting utilities (global) ─────────── */
window.fmtDollar = function (v) {
  if (v == null || v === '—') return '—';
  var n = parseFloat(String(v).replace(/,/g, ''));
  if (isNaN(n)) return v === '—' ? '—' : String(v);
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

window.fmtPnl = function (v) {
  if (v == null) return '—';
  var n = parseFloat(String(v).replace(/,/g, ''));
  if (isNaN(n)) return '—';
  return (n >= 0 ? '+$' : '-$') + Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

(function () {
  'use strict';

  /* ── DOM refs ─────────────────────────────────── */
  var statusDot   = document.getElementById('status-dot');
  var navToggle   = document.getElementById('nav-toggle');
  var holdingsNav = document.getElementById('holdings-nav');
  var navBackdrop = document.getElementById('nav-backdrop');
  var ordersCount = document.getElementById('orders-count');
  var ordersList  = document.getElementById('orders-list');

  /* ── Mobile nav drawer ────────────────────────── */
  function openNav() {
    holdingsNav.classList.add('open');
    navBackdrop.classList.add('visible');
    navToggle.setAttribute('aria-expanded', 'true');
  }

  function closeNav() {
    holdingsNav.classList.remove('open');
    navBackdrop.classList.remove('visible');
    navToggle.setAttribute('aria-expanded', 'false');
  }

  if (navToggle) {
    navToggle.addEventListener('click', function () {
      holdingsNav.classList.contains('open') ? closeNav() : openNav();
    });
  }

  if (navBackdrop) {
    navBackdrop.addEventListener('click', closeNav);
  }

  /* ── Mobile tab switching ─────────────────────── */
  var tabs = document.querySelectorAll('.tab-strip .tab');

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      var target = tab.dataset.panel;

      tabs.forEach(function (t) {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });

      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');

      document.querySelectorAll('.panel').forEach(function (p) {
        var isTarget = p.id === 'panel-' + target;
        p.classList.toggle('active', isTarget);
        p.setAttribute('aria-hidden', String(!isTarget));
      });
    });
  });

  /* ── Cancel button — event delegation ────────── */
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('.cancel-btn');
    if (!btn) return;

    var orderId = btn.dataset.orderId;
    if (!orderId) return;

    btn.disabled = true;
    btn.textContent = '…';

    fetch('/api/orders/' + orderId, { method: 'DELETE' })
      .then(function (resp) {
        if (resp.ok) {
          var row = document.querySelector('tr[data-order-id="' + orderId + '"]');
          if (row) row.remove();
          updateOrderCount();
        } else {
          btn.disabled = false;
          btn.textContent = '✕';
        }
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = '✕';
      });
  });

  function updateOrderCount() {
    var rows = document.querySelectorAll('#orders-list tbody tr[data-order-id]');
    var n = rows.length;
    if (ordersCount) ordersCount.textContent = n;
    var badge = document.querySelector('.tab[data-panel="orders"] .tab-badge');
    if (badge) {
      badge.textContent = n;
      badge.style.display = n === 0 ? 'none' : '';
    }
  }

  /* ── SSE connection ───────────────────────────── */
  var es = new EventSource('/stream/live');

  es.onopen = function () {
    if (statusDot) { statusDot.className = 'status-dot connected'; statusDot.title = 'live'; }
  };

  es.onerror = function () {
    if (statusDot) { statusDot.className = 'status-dot disconnected'; statusDot.title = 'disconnected'; }
  };

  /* quote: update mark price for a symbol row */
  es.addEventListener('quote', function (e) {
    var data = JSON.parse(e.data);
    var row = document.querySelector('#positions-table [data-symbol="' + CSS.escape(data.symbol) + '"]');
    if (!row) return;
    var cells = row.querySelectorAll('td');
    if (cells[4]) {
      cells[4].textContent = data.last != null ? fmtDollar(data.last) : '—';
      cells[4].className = 'neutral';
    }
  });

  /* account: update topbar stats */
  es.addEventListener('account', function (e) {
    var data = JSON.parse(e.data);
    setText('.header-account', data.account_number);
    setText('.header-nlv', fmtDollar(data.net_liquidating_value));
    setText('.header-bp', fmtDollar(data.buying_power));
  });

  /* positions: re-render positions table body + holdings sidebar */
  es.addEventListener('positions', function (e) {
    var data = JSON.parse(e.data);
    var tbody = document.querySelector('#positions-table tbody');
    if (!tbody) return;

    if (!data.positions || data.positions.length === 0) {
      tbody.innerHTML = '<tr class="empty-row"><td colspan="7">no positions</td></tr>';
      renderHoldings([]);
      return;
    }

    tbody.innerHTML = data.positions.map(function (pos) {
      return '<tr data-symbol="' + esc(pos.symbol) + '">' +
        '<td class="col-left symbol-cell">' + esc(pos.symbol) + '</td>' +
        '<td class="col-dim">' + esc(pos.instrument_type || '—') + '</td>' +
        '<td>' + (pos.quantity != null ? pos.quantity : '—') + '</td>' +
        '<td>' + fmtDollar(pos.avg_cost) + '</td>' +
        '<td class="neutral">—</td>' +
        '<td class="neutral">—</td>' +
        '<td class="neutral">—</td>' +
        '</tr>';
    }).join('');

    renderHoldings(data.positions);
    updateSymbolSuggestions(data.positions);
  });

  function updateSymbolSuggestions(positions) {
    var dl = document.getElementById('symbol-suggestions');
    if (!dl) return;
    dl.innerHTML = (positions || []).map(function (p) {
      return '<option value="' + esc(p.symbol) + '">';
    }).join('');
  }

  function renderHoldings(positions) {
    var list = document.getElementById('holdings-list');
    if (!list) return;
    if (!positions || positions.length === 0) {
      list.innerHTML = '<li class="holding-item placeholder">no holdings</li>';
      return;
    }
    list.innerHTML = positions.map(function (pos) {
      return '<li class="holding-item">' +
        '<span class="holding-symbol">' + esc(pos.symbol) + '</span>' +
        '<span class="holding-qty">' + (pos.quantity != null ? pos.quantity : '') + '</span>' +
        '</li>';
    }).join('');
  }

  /* orders: re-render entire orders panel */
  es.addEventListener('orders', function (e) {
    var data = JSON.parse(e.data);
    if (!ordersList) return;

    var cancelable = { 'Received': true, 'Routed': true, 'Live': true };
    var statusClass = {
      'Received': 'status-received', 'Routed': 'status-routed',
      'Live': 'status-live', 'Filled': 'status-filled',
      'Rejected': 'status-rejected', 'Cancelled': 'status-cancelled'
    };

    if (!data.orders || data.orders.length === 0) {
      ordersList.innerHTML = '<div class="empty-state">no open orders</div>';
      if (ordersCount) ordersCount.textContent = '0';
      updateTabBadge(0);
      return;
    }

    var rows = data.orders.map(function (o) {
      var chipClass = statusClass[o.status] || 'status-received';
      var cancelCell = (cancelable[o.status] && o.id)
        ? '<button class="cancel-btn" data-order-id="' + esc(o.id) + '" aria-label="Cancel order ' + esc(o.id) + '">✕</button>'
        : '';
      var isBuy = (o.action || '').startsWith('Buy');
      var sideClass = isBuy ? 'buy-action' : 'sell-action';
      return '<tr data-order-id="' + esc(o.id) + '">' +
        '<td class="col-left symbol-cell">' + esc(o.symbol) + '</td>' +
        '<td class="col-dim ' + sideClass + '">' + esc(o.action) + '</td>' +
        '<td class="col-dim">' + esc(o.order_type) + '</td>' +
        '<td>' + (o.quantity != null ? o.quantity : '—') + '</td>' +
        '<td class="' + sideClass + '">' + fmtDollar(o.price) + '</td>' +
        '<td class="col-left"><span class="status-chip ' + chipClass + '">' + esc(o.status) + '</span></td>' +
        '<td>' + esc(o.time) + '</td>' +
        '<td class="col-end">' + cancelCell + '</td>' +
        '</tr>';
    }).join('');

    ordersList.innerHTML =
      '<table class="data-table orders-table"><thead><tr>' +
      '<th class="col-left">symbol</th>' +
      '<th class="col-left">action</th>' +
      '<th class="col-left">type</th>' +
      '<th>qty</th><th>price</th>' +
      '<th class="col-left">status</th>' +
      '<th class="col-left">time</th>' +
      '<th class="col-end"></th>' +
      '</tr></thead><tbody>' + rows + '</tbody></table>';

    var n = data.orders.length;
    if (ordersCount) ordersCount.textContent = n;
    updateTabBadge(n);
  });

  function updateTabBadge(n) {
    var badge = document.querySelector('.tab[data-panel="orders"] .tab-badge');
    if (!badge) return;
    badge.textContent = n;
    badge.style.display = n === 0 ? 'none' : '';
  }

  /* ── Helpers ──────────────────────────────────── */
  function setText(selector, value) {
    var el = document.querySelector(selector);
    if (el) el.textContent = value || '—';
  }

  function esc(s) {
    if (s == null) return '—';
    return String(s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

})();
