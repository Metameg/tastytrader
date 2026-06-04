const statusDot = document.querySelector('.status-dot');
let es;
let selectedSymbol = null;
let selectedRow = null;

function connect() {
  es = new EventSource('/stream/live');

  es.onopen = () => {
    statusDot.className = 'status-dot connected';
  };

  es.onerror = () => {
    statusDot.className = 'status-dot disconnected';
  };

  es.addEventListener('quote', e => handleQuote(JSON.parse(e.data)));
  es.addEventListener('positions', e => handlePositions(JSON.parse(e.data)));
}

function handleQuote(quote) {
  console.log('[SSE quote]', quote);
  const { symbol, bid, ask, last } = quote;
  const mark = (bid != null && ask != null) ? (bid + ask) / 2 : last;
  if (mark == null) return;

  document.querySelectorAll(`tr[data-symbol="${CSS.escape(symbol)}"]`).forEach(tr => {
    const qty = parseInt(tr.dataset.qty, 10);
    const avgCost = parseFloat(tr.dataset.avgCost);
    const isOption = tr.dataset.instrumentType.includes('Option');
    const multiplier = isOption ? 100 : 1;
    const pnl = (mark - avgCost) * qty * multiplier;

    const markCell = tr.querySelector('[data-col="mark"]');
    if (markCell) {
      markCell.textContent = fmtDollar(mark);
      markCell.className = 'mark';
    }

    const pnlCell = tr.querySelector('[data-col="pnl"]');
    if (pnlCell) {
      const chip = pnlCell.querySelector('.chip') || pnlCell;
      chip.textContent = fmtPnl(pnl);
      chip.className = 'chip ' + (pnl > 0 ? 'pl-positive' : pnl < 0 ? 'pl-negative' : 'neutral');
    }
  });

  // Update detail panel if it's open for this symbol
  if (selectedSymbol === symbol) {
    updateDetailQuote(symbol, quote);
    if (selectedRow) {
      updateDetailPnl(symbol, selectedRow.dataset.qty, selectedRow.dataset.avgCost, quote);
    }
  }
}

function parseOcc(symbol) {
  // OCC: 6-char underlying (right-padded) + YYMMDD + C/P + 8-digit strike*1000
  const m = symbol.match(/^([A-Z ]{6})(\d{6})([CP])(\d{8})$/);
  if (!m) return null;
  const underlying = m[1].trim();
  const dateStr = m[2];   // YYMMDD
  const optChar = m[3];
  const strikeRaw = parseInt(m[4], 10);

  const yy = parseInt(dateStr.slice(0, 2), 10);
  const mm = parseInt(dateStr.slice(2, 4), 10) - 1; // 0-indexed
  const dd = parseInt(dateStr.slice(4, 6), 10);
  const year = 2000 + yy;
  const expiry = new Date(year, mm, dd);
  const expStr = expiry.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

  return {
    underlying,
    expiry: expStr,
    option_type: optChar === 'C' ? 'Call' : 'Put',
    strike: strikeRaw / 1000,
  };
}

function populateDetailPanel(symbol, instrumentType, qty, avgCost, quote) {
  const empty   = document.getElementById('detail-empty');
  const content = document.getElementById('detail-content');

  // Symbol header
  document.getElementById('detail-symbol').textContent = formatSymbol(symbol);
  document.getElementById('detail-type-chip').textContent =
    instrumentType === 'Equity Option' ? 'option' : 'equity';

  // Option fields
  const optFields = document.getElementById('detail-option-fields');
  if (instrumentType === 'Equity Option') {
    const parsed = parseOcc(symbol);
    if (parsed) {
      document.getElementById('detail-underlying').textContent  = parsed.underlying;
      document.getElementById('detail-expiry').textContent      = parsed.expiry;
      document.getElementById('detail-option-type').textContent = parsed.option_type;
      document.getElementById('detail-strike').textContent      = fmtDollar(parsed.strike);
    }
    optFields.removeAttribute('hidden');
  } else {
    optFields.setAttribute('hidden', '');
  }

  // Greeks section (only shown for Equity Option rows; populated async below)
  const greeksSection = document.getElementById('detail-greeks-section');
  if (instrumentType === 'Equity Option') {
    greeksSection.removeAttribute('hidden');
  } else {
    greeksSection.setAttribute('hidden', '');
    populateGreeks({ delta: '—', gamma: '—', theta: '—', vega: '—', iv: '—' });
  }

  // Live quote fields (may be null on first populate before warm-up)
  updateDetailQuote(symbol, quote);

  // Cost basis
  document.getElementById('detail-avg-cost').textContent =
    avgCost != null ? fmtDollar(parseFloat(avgCost)) : '—';

  // P&L (will also be updated live in updateDetailQuote)
  updateDetailPnl(symbol, qty, avgCost, quote);

  // Show content, hide empty state
  empty.setAttribute('hidden', '');
  content.removeAttribute('hidden');
}

function populateGreeks(data) {
  document.getElementById('detail-delta').textContent = data.delta ?? '—';
  document.getElementById('detail-gamma').textContent = data.gamma ?? '—';
  document.getElementById('detail-theta').textContent = data.theta ?? '—';
  document.getElementById('detail-vega').textContent  = data.vega  ?? '—';
  document.getElementById('detail-iv').textContent    = data.iv    ?? '—';
}

function updateDetailQuote(symbol, quote) {
  if (!quote) return;
  const { last, bid, ask, ema_short, ema_long } = quote;

  document.getElementById('detail-last').textContent      = fmtDollar(last);
  document.getElementById('detail-bid').textContent       = fmtDollar(bid);
  document.getElementById('detail-ask').textContent       = fmtDollar(ask);
  document.getElementById('detail-ema-short').textContent = fmtDollar(ema_short);
  document.getElementById('detail-ema-long').textContent  = fmtDollar(ema_long);
}

function updateDetailPnl(symbol, qty, avgCost, quote) {
  if (!quote || qty == null || avgCost == null) return;
  const { bid, ask, last } = quote;
  const mark = (bid != null && ask != null) ? (bid + ask) / 2 : last;
  if (mark == null) return;

  const isOption = selectedRow?.dataset.instrumentType?.includes('Option') ?? false;
  const multiplier = isOption ? 100 : 1;
  const pnl = (mark - parseFloat(avgCost)) * parseInt(qty, 10) * multiplier;

  const el = document.getElementById('detail-open-pnl');
  el.textContent = fmtPnl(pnl);
  el.className = 'detail-value detail-mono ' +
    (pnl > 0 ? 'detail-pnl-positive' : pnl < 0 ? 'detail-pnl-negative' : '');
}

function formatSymbol(sym) {
  const m = sym.trim().match(/^([A-Z]+)\s+(\d{6})([CP])(\d{8})$/);
  if (!m) return sym;
  const [, und, exp, type, strike] = m;
  return `${und} ${exp} ${type} ${(parseInt(strike) / 1000).toFixed(2)}`;
}

function handlePositions(positions) {
  const tbody = document.querySelector('#positions-table tbody');
  if (!tbody) return;

  const equities = positions.filter(p => p.instrument_type === 'Equity');
  const options = positions.filter(p => p.instrument_type === 'Equity Option');
  const equitySymbols = new Set(equities.map(p => p.symbol));

  const optionsByParent = {};
  for (const opt of options) {
    const parent = opt.symbol.trim().match(/^([A-Z]+)/)?.[1] ?? opt.symbol.slice(0, 6).trim();
    if (!optionsByParent[parent]) optionsByParent[parent] = [];
    optionsByParent[parent].push(opt);
  }

  const rendered = new Set();
  const rows = [];

  for (const pos of equities) {
    rows.push(buildRow(pos, false));
    rendered.add(pos.symbol);
    const children = optionsByParent[pos.symbol] ?? [];
    for (const opt of children) {
      rows.push(buildRow(opt, true));
      rendered.add(opt.symbol);
    }
  }

  for (const opt of options) {
    if (!rendered.has(opt.symbol)) {
      rows.push(buildRow(opt, false));
    }
  }

  tbody.innerHTML = rows.join('') || '<tr class="placeholder-row"><td colspan="7">no positions</td></tr>';

  // Re-attach selected state after DOM rebuild
  if (selectedSymbol) {
    const reselected = tbody.querySelector(`tr[data-symbol="${CSS.escape(selectedSymbol)}"]`);
    if (reselected) {
      reselected.setAttribute('data-selected', '');
      selectedRow = reselected;
    } else {
      selectedRow = null;
    }
  }
}

function escapeHtml(str) {
  const d = document.createElement('div');
  d.appendChild(document.createTextNode(String(str ?? '')));
  return d.innerHTML;
}

function buildRow(pos, isSubRow) {
  const cls = isSubRow ? ' class="option-leg-row"' : '';
  const symDisplay = pos.instrument_type === 'Equity Option' ? formatSymbol(pos.symbol) : pos.symbol;
  const parentAttr = isSubRow
    ? ` data-parent="${escapeHtml(pos.symbol.trim().match(/^([A-Z]+)/)?.[1] ?? '')}"`
    : '';
  const mark = pos.current_price != null ? escapeHtml(pos.current_price) : '—';
  return `<tr${cls} data-symbol="${escapeHtml(pos.symbol)}" data-instrument-type="${escapeHtml(pos.instrument_type)}" data-qty="${escapeHtml(pos.quantity)}" data-avg-cost="${escapeHtml(pos.avg_cost)}"${parentAttr}>
    <td>${escapeHtml(symDisplay)}</td>
    <td>${escapeHtml(pos.instrument_type)}</td>
    <td>${escapeHtml(pos.quantity)}</td>
    <td>${fmtDollar(pos.avg_cost)}</td>
    <td class="mark neutral" data-col="mark">${mark}</td>
    <td class="pnl neutral" data-col="pnl"><span class="chip neutral">—</span></td>
    <td class="pnl neutral" data-col="total-pnl"><span class="chip neutral">—</span></td>
  </tr>`;
}

document.addEventListener('click', e => {
  // Cancel order button
  const cancelBtn = e.target.closest('[data-cancel-order]');
  if (cancelBtn) {
    const orderId = cancelBtn.dataset.cancelOrder;
    fetch(`/api/orders/${orderId}`, { method: 'DELETE' }).then(r => {
      if (r.ok) cancelBtn.closest('tr')?.remove();
    });
    return;
  }

  // Position row click → open detail panel
  const tr = e.target.closest('#positions-table tbody tr');
  if (!tr) return;

  const symbol = tr.dataset.symbol;
  if (!symbol) return;

  // Deselect previous row
  if (selectedRow) selectedRow.removeAttribute('data-selected');

  // Select new row
  tr.setAttribute('data-selected', '');
  selectedRow = tr;
  selectedSymbol = symbol;

  const instrumentType = tr.dataset.instrumentType ?? 'Equity';
  const qty     = tr.dataset.qty;
  const avgCost = tr.dataset.avgCost;

  // Fetch current quote, then populate panel
  fetch(`/api/quotes/${encodeURIComponent(symbol)}`)
    .then(r => r.json())
    .then(quote => {
      // quote may be empty object {} if not yet streamed
      populateDetailPanel(symbol, instrumentType, qty, avgCost,
        Object.keys(quote).length ? quote : null);
    })
    .catch(() => {
      populateDetailPanel(symbol, instrumentType, qty, avgCost, null);
    });

  // Fetch greeks for option rows only
  if (instrumentType === 'Equity Option') {
    fetch(`/api/greeks/${encodeURIComponent(symbol)}`)
      .then(r => r.json())
      .then(data => {
        populateGreeks(data);
      })
      .catch(() => {
        populateGreeks({ delta: '—', gamma: '—', theta: '—', vega: '—', iv: '—' });
      });
  }
});

connect();
