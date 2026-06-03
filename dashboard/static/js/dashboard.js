const statusDot = document.querySelector('.status-dot');
let es;

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
    if (markCell) markCell.textContent = mark.toFixed(2);

    const pnlCell = tr.querySelector('[data-col="pnl"]');
    if (pnlCell) {
      const chip = pnlCell.querySelector('.chip') || pnlCell;
      chip.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2);
      chip.className = 'chip ' + (pnl > 0 ? 'pl-positive' : pnl < 0 ? 'pl-negative' : 'neutral');
    }
  });
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
    <td>${escapeHtml(pos.avg_cost)}</td>
    <td class="mark neutral" data-col="mark">${mark}</td>
    <td class="pnl neutral" data-col="pnl"><span class="chip neutral">—</span></td>
    <td class="pnl neutral" data-col="total-pnl"><span class="chip neutral">—</span></td>
  </tr>`;
}

document.addEventListener('click', e => {
  const btn = e.target.closest('[data-cancel-order]');
  if (!btn) return;
  const orderId = btn.dataset.cancelOrder;
  fetch(`/api/orders/${orderId}`, { method: 'DELETE' }).then(r => {
    if (r.ok) btn.closest('tr')?.remove();
  });
});

connect();
