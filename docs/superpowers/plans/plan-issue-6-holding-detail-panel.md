# Implementation Plan — Issue #6: Holding Detail Panel (live quote + EMA)

## Header

**Goal:** Add a detail panel to the dashboard that populates with live quote data, EMA values, P&L, and parsed OCC option fields when a position row is clicked.

**Architecture:** All state lives in `DashboardState`; the panel is driven by SSE `quote` events already flowing. No new backend routes are needed — `/api/quotes/{symbol}` already exists for the initial fetch. The Python `parse_occ()` function is pure (no I/O) and lives in `state.py` for easy unit testing.

**Tech stack:**
- Python 3.12, FastAPI, `re` stdlib for OCC parser
- Vanilla JS (ES2020+, no build step), SSE EventSource already connected
- CSS custom properties from `tokens.css`, mobile-first, BEM-ish

---

## File Structure

```
dashboard/
  state.py                         ← add parse_occ() function
  templates/
    index.html                     ← add #detail-panel section inside panels-area
  static/
    css/
      layout.css                   ← add desktop split media query (≥1024px)
      components.css               ← add .detail-panel, .detail-section, .detail-row styles
    js/
      dashboard.js                 ← row click handler, panel update, JS OCC display
tests/
  test_dashboard.py                ← Phase 1 already added parse_occ tests (failing)
```

---

## Tasks

---

### TASK 1 — Python `parse_occ()` function (TDD)

**Goal:** Make the 6 failing `test_parse_occ_*` tests in `tests/test_dashboard.py` pass.

**Prerequisites:** Phase 1 tests are already written and imported from `dashboard.state`. The import `from dashboard.state import parse_occ` currently fails with `ImportError`.

#### Step 1a — Confirm tests fail

```bash
safe-test python -m pytest tests/test_dashboard.py -k "parse_occ" --tb=short -q
```

Expected: `ImportError` or 6 failures. Confirm before implementing.

#### Step 1b — Implement `parse_occ` in `dashboard/state.py`

Add this function at the bottom of `dashboard/state.py`, after the imports block (which already has `import re`):

```python
def parse_occ(symbol: str) -> dict | None:
    """Parse an OCC option symbol into its components.

    OCC format: 6-char underlying (right-padded) + YYMMDD + C/P + 8-digit strike*1000
    Example: 'AAPL  240119C00150000' → underlying=AAPL, expiry=Jan 19 2024,
             option_type=Call, strike=150.0

    Returns None if the symbol does not match the OCC format.
    """
    from datetime import datetime

    m = re.fullmatch(r"([A-Z ]{6})(\d{6})([CP])(\d{8})", symbol)
    if not m:
        return None
    underlying = m.group(1).strip()
    date_str = m.group(2)
    opt_char = m.group(3)
    strike_raw = m.group(4)

    try:
        expiry_dt = datetime.strptime(date_str, "%y%m%d")
    except ValueError:
        return None

    return {
        "underlying": underlying,
        "expiry": expiry_dt.strftime("%b %-d %Y"),   # e.g. "Jan 19 2024"
        "option_type": "Call" if opt_char == "C" else "Put",
        "strike": int(strike_raw) / 1000,
    }
```

> Note on `strftime("%-d")`: strips leading zero on Linux. If CI runs on Windows use `%#d`. Since the OS is Linux (confirmed in env), `%-d` is safe.

#### Step 1c — Run tests to confirm green

```bash
safe-test python -m pytest tests/test_dashboard.py -k "parse_occ" --tb=short -q
```

Expected: 6 passed.

#### Step 1d — Run full suite to confirm no regressions

```bash
safe-test python -m pytest --tb=short -q
```

Expected: 123+ passed (117 baseline + 6 new), 0 failed.

#### Step 1e — Commit

```bash
git add dashboard/state.py
git commit -m "feat(#6): implement parse_occ() for OCC option symbol parsing"
```

---

### TASK 2 — HTML: Detail Panel Structure

**Goal:** Add the `#detail-panel` section to `index.html` inside `.panels-area`, after the orders `<section>`.

**File:** `dashboard/templates/index.html`

Insert the following block immediately after the closing `</section>` of the orders panel (before `</div><!-- /panels-area -->`):

```html
      <!-- Detail panel — populated on row click -->
      <aside class="detail-panel" id="detail-panel" aria-label="Position detail" hidden>

        <!-- No-selection empty state (shown when nothing is selected) -->
        <div class="detail-empty" id="detail-empty">
          <span class="detail-empty-msg">select a position to view details</span>
        </div>

        <!-- Detail content (shown when a row is selected) -->
        <div class="detail-content" id="detail-content" hidden>

          <!-- Header: symbol + type chip -->
          <div class="detail-header">
            <span class="detail-symbol" id="detail-symbol"></span>
            <span class="detail-type-chip" id="detail-type-chip"></span>
          </div>

          <!-- Option fields (only shown for Equity Option rows) -->
          <div class="detail-section detail-option-fields" id="detail-option-fields" hidden>
            <div class="detail-row">
              <span class="detail-label">underlying</span>
              <span class="detail-value" id="detail-underlying"></span>
            </div>
            <div class="detail-row">
              <span class="detail-label">expiry</span>
              <span class="detail-value" id="detail-expiry"></span>
            </div>
            <div class="detail-row">
              <span class="detail-label">type</span>
              <span class="detail-value" id="detail-option-type"></span>
            </div>
            <div class="detail-row">
              <span class="detail-label">strike</span>
              <span class="detail-value" id="detail-strike"></span>
            </div>
          </div>

          <!-- Live quote fields -->
          <div class="detail-section">
            <div class="detail-row">
              <span class="detail-label">last</span>
              <span class="detail-value detail-mono" id="detail-last">—</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">bid</span>
              <span class="detail-value detail-mono" id="detail-bid">—</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">ask</span>
              <span class="detail-value detail-mono" id="detail-ask">—</span>
            </div>
          </div>

          <!-- EMA fields -->
          <div class="detail-section">
            <div class="detail-row">
              <span class="detail-label">ema 10</span>
              <span class="detail-value detail-mono" id="detail-ema-short">—</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">ema 20</span>
              <span class="detail-value detail-mono" id="detail-ema-long">—</span>
            </div>
          </div>

          <!-- Cost basis + P&L fields -->
          <div class="detail-section">
            <div class="detail-row">
              <span class="detail-label">avg cost</span>
              <span class="detail-value detail-mono" id="detail-avg-cost">—</span>
            </div>
            <div class="detail-row">
              <span class="detail-label">open p&amp;l</span>
              <span class="detail-value detail-mono" id="detail-open-pnl">—</span>
            </div>
          </div>

          <!-- Chart placeholder (chart implemented in issue #7) -->
          <div class="detail-chart-placeholder" id="detail-chart-placeholder">
            <span class="detail-chart-msg">chart · coming in #7</span>
          </div>

        </div><!-- /detail-content -->
      </aside><!-- /detail-panel -->
```

No tests for HTML structure — the production-validator verifies frontend behavior.

#### Commit

```bash
git add dashboard/templates/index.html
git commit -m "feat(#6): add detail panel HTML structure to index.html"
```

---

### TASK 3 — CSS: Detail Panel Component Styles

**Goal:** Add `.detail-panel` and related component classes to `components.css`.

**File:** `dashboard/static/css/components.css`

Append at the end of the file:

```css
/* ── DETAIL PANEL ────────────────────────────────── */
.detail-panel {
  flex-shrink: 0;
  width: 280px;
  background: var(--bg-overlay);
  border-left: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* Empty state — nothing selected */
.detail-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-4);
}

.detail-empty-msg {
  font-size: var(--text-xs);
  color: var(--text-muted);
  text-align: center;
  line-height: 1.6;
}

/* Content area — shown when a row is selected */
.detail-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  min-height: 0;
}

/* Symbol header */
.detail-header {
  padding: var(--sp-3) var(--sp-3) var(--sp-2);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-shrink: 0;
}

.detail-symbol {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--text);
  font-family: var(--font-ui);
  letter-spacing: -0.01em;
}

.detail-type-chip {
  font-size: var(--text-2xs);
  font-family: var(--font-ui);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted);
  background: var(--bg-hover);
  border: 1px solid var(--border-mid);
  border-radius: var(--r-xs);
  padding: 0 4px;
  line-height: 16px;
}

/* Grouped sections of rows */
.detail-section {
  border-bottom: 1px solid var(--border);
  padding: var(--sp-2) 0;
}

/* Individual label/value row */
.detail-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px var(--sp-3);
  height: 22px;
}

.detail-label {
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-family: var(--font-ui);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.detail-value {
  font-size: var(--text-sm);
  color: var(--text-dim);
}

.detail-mono {
  font-family: var(--font-mono);
}

/* P&L coloring in detail panel */
.detail-pnl-positive { color: var(--green) !important; }
.detail-pnl-negative { color: var(--red) !important; }

/* Chart placeholder */
.detail-chart-placeholder {
  flex: 1;
  min-height: 120px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-top: 1px dashed var(--border-mid);
  margin-top: var(--sp-2);
}

.detail-chart-msg {
  font-size: var(--text-xs);
  color: var(--text-faint);
  font-family: var(--font-mono);
}

/* Selected row highlight in positions table */
#positions-table tr[data-selected] {
  background: var(--bg-hover);
  outline: 1px solid var(--accent);
  outline-offset: -1px;
}

#positions-table tbody tr {
  cursor: pointer;
}
```

No tests for CSS — the production-validator verifies rendering.

#### Commit

```bash
git add dashboard/static/css/components.css
git commit -m "feat(#6): add detail panel CSS component styles"
```

---

### TASK 4 — CSS: Layout Split at Desktop

**Goal:** At ≥1024px, show the detail panel side-by-side with the panels column (positions + orders). On narrower viewports the detail panel stays hidden until a row is clicked (it then shows as an overlay-like aside — since `hidden` attribute controls visibility, no extra mobile logic needed at this stage).

**File:** `dashboard/static/css/layout.css`

Add inside the existing `@media (min-width: 768px)` block, or add a new media query after it. The key change: at ≥1024px, `.panels-area` uses a row flex to split positions/orders column left and the detail panel right.

Append after the existing `@media (min-width: 768px)` block:

```css
/* ── WIDE DESKTOP (≥1024px) — show detail panel alongside positions ── */
@media (min-width: 1024px) {
  .panels-area {
    flex-direction: row;
  }

  /* left column: positions + orders stacked vertically, fills remaining space */
  .panels-column {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 0;
  }

  /* detail panel: fixed 280px on the right, always present in DOM,
     visibility controlled by [hidden] attribute */
  .detail-panel {
    /* override the mobile default — at desktop it's always in the flex row */
  }

  .detail-panel[hidden] {
    /* At desktop, show a collapsed state rather than completely hidden */
    display: flex !important;
    width: 240px;
    min-width: 200px;
  }
}
```

> **Note:** At desktop the detail panel is always rendered in the flex row for layout stability. When `hidden` it shows the "no selection" empty state (its `#detail-empty` child). When populated it shows `#detail-content`. The `hidden` attribute on the aside itself controls which child is visible via JS, not the panel's own display.

> **Revised approach:** The `hidden` attribute approach above is cleaner if we _don't_ put `hidden` on the `<aside>` itself at desktop. Instead: the `<aside>` is always visible at desktop. On mobile it's `display:none` (via layout default) until a row is clicked. JS adds/removes `hidden` only on `#detail-empty` and `#detail-content`. This avoids the `display: flex !important` hack.

**Revised layout strategy:**

1. The `<aside class="detail-panel">` has NO `hidden` attribute in the HTML.
2. `#detail-empty` is visible by default; `#detail-content` has `hidden` attribute.
3. On mobile (`< 1024px`), the detail panel is `display: none` via CSS (no JS needed for show/hide at mobile — it's simply not in the flow).
4. On desktop (`≥ 1024px`), the aside is a flex child of `.panels-area` and always visible.
5. Clicking a row: reveals `#detail-content`, hides `#detail-empty`.
6. Mobile "back" behavior: not required for this issue — detail panel is desktop-only per acceptance criteria (panel visible at ≥1024px).

**Updated HTML change from Task 2:** Remove the `hidden` attribute from the `<aside>` tag itself. The initial `<aside class="detail-panel" ...>` should have NO `hidden` attribute.

**Updated CSS to append at end of `layout.css`:**

```css
/* ── DETAIL PANEL — hidden on mobile ────────────── */
.detail-panel {
  display: none;
}

/* ── WIDE DESKTOP (≥1024px) ─────────────────────── */
@media (min-width: 1024px) {
  .panels-area {
    flex-direction: row;
    align-items: stretch;
  }

  .panels-column {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    min-width: 0;
  }

  .detail-panel {
    display: flex;
    width: 280px;
    flex-shrink: 0;
  }
}
```

**HTML wrapping change (also needed in Task 2 HTML):** The tab strip, positions section, and orders section need to be wrapped in a `<div class="panels-column">` inside `.panels-area`. This keeps the existing vertical stacking and gives us the flex child to position against the detail panel.

**Updated HTML structure in `index.html`:**

```html
    <!-- Main panels area -->
    <div class="panels-area">

      <div class="panels-column">
        <!-- Mobile tab strip -->
        ...

        <!-- Positions panel -->
        ...

        <!-- Orders panel -->
        ...
      </div><!-- /panels-column -->

      <!-- Detail panel -->
      <aside class="detail-panel" id="detail-panel" aria-label="Position detail">
        ...
      </aside>

    </div><!-- /panels-area -->
```

#### Commit

```bash
git add dashboard/static/css/layout.css dashboard/templates/index.html
git commit -m "feat(#6): desktop layout split — detail panel alongside positions"
```

---

### TASK 5 — JS: Row Click Handler + Panel Population

**Goal:** Clicking a `<tr>` in `#positions-table` fetches the initial quote, populates the detail panel, and marks the row as selected.

**File:** `dashboard/static/js/dashboard.js`

#### State variables to add (near top, after `let es;`):

```js
let selectedSymbol = null;
let selectedRow = null;
```

#### JS OCC parser (mirrors Python logic):

```js
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
```

#### Detail panel population function:

```js
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
      document.getElementById('detail-strike').textContent      = '$' + parsed.strike.toFixed(2);
    }
    optFields.removeAttribute('hidden');
  } else {
    optFields.setAttribute('hidden', '');
  }

  // Live quote fields (may be null on first populate before warm-up)
  updateDetailQuote(symbol, quote);

  // Cost basis
  document.getElementById('detail-avg-cost').textContent =
    avgCost != null ? '$' + parseFloat(avgCost).toFixed(2) : '—';

  // P&L (will also be updated live in updateDetailQuote)
  updateDetailPnl(symbol, qty, avgCost, quote);

  // Show content, hide empty state
  empty.setAttribute('hidden', '');
  content.removeAttribute('hidden');
}

function updateDetailQuote(symbol, quote) {
  if (!quote) return;
  const { last, bid, ask, ema_short, ema_long } = quote;

  const fmt = v => (v != null ? v.toFixed(2) : '—');
  document.getElementById('detail-last').textContent     = fmt(last);
  document.getElementById('detail-bid').textContent      = fmt(bid);
  document.getElementById('detail-ask').textContent      = fmt(ask);
  document.getElementById('detail-ema-short').textContent = fmt(ema_short);
  document.getElementById('detail-ema-long').textContent  = fmt(ema_long);
}

function updateDetailPnl(symbol, qty, avgCost, quote) {
  if (!quote || qty == null || avgCost == null) return;
  const { bid, ask, last } = quote;
  const mark = (bid != null && ask != null) ? (bid + ask) / 2 : last;
  if (mark == null) return;

  // Read instrument type from the selected row's data attribute
  const row = document.querySelector(`tr[data-symbol="${CSS.escape(symbol)}"][data-selected]`);
  const isOption = row?.dataset.instrumentType?.includes('Option') ?? false;
  const multiplier = isOption ? 100 : 1;
  const pnl = (mark - parseFloat(avgCost)) * parseInt(qty, 10) * multiplier;

  const el = document.getElementById('detail-open-pnl');
  el.textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2);
  el.className = 'detail-value detail-mono ' +
    (pnl > 0 ? 'detail-pnl-positive' : pnl < 0 ? 'detail-pnl-negative' : '');
}
```

#### Row click handler (add to the existing `document.addEventListener('click', ...)` or add a new one):

Replace the existing click handler block entirely with:

```js
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
});
```

#### No frontend unit tests needed — the production-validator will verify click and live-update behavior.

#### Commit

```bash
git add dashboard/static/js/dashboard.js
git commit -m "feat(#6): row click handler and detail panel population"
```

---

### TASK 6 — JS: Live Quote Updates to Open Detail Panel

**Goal:** While the detail panel is open for `selectedSymbol`, incoming `quote` SSE events update the displayed values.

**File:** `dashboard/static/js/dashboard.js`

Modify the existing `handleQuote` function to also update the detail panel when it's open for the same symbol:

```js
function handleQuote(quote) {
  const { symbol, bid, ask, last } = quote;
  const mark = (bid != null && ask != null) ? (bid + ask) / 2 : last;
  if (mark == null) return;

  // Update positions table row(s)
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

  // Update detail panel if it's open for this symbol
  if (selectedSymbol === symbol) {
    updateDetailQuote(symbol, quote);
    if (selectedRow) {
      updateDetailPnl(symbol, selectedRow.dataset.qty, selectedRow.dataset.avgCost, quote);
    }
  }
}
```

#### Commit

```bash
git add dashboard/static/js/dashboard.js
git commit -m "feat(#6): live quote updates to open detail panel via SSE"
```

---

### TASK 7 — JS: OCC Component Display Verification

**Goal:** Verify that clicking an option leg row (`.option-leg-row`) shows the parsed option fields in the detail panel. No new code — this is a wiring verification step.

**Check:** The `parseOcc()` function in JS is called inside `populateDetailPanel()` when `instrumentType === 'Equity Option'`. Confirm the JS regex pattern matches the OCC format used in `formatSymbol()`:

- `formatSymbol` regex: `/^([A-Z]+)\s+(\d{6})([CP])(\d{8})$/` — matches trimmed symbol with variable-length underlying
- `parseOcc` regex: `/^([A-Z ]{6})(\d{6})([CP])(\d{8})$/` — matches 6-char padded underlying

The `data-symbol` attribute on `<tr>` stores the raw OCC string (e.g., `"AAPL  240119C00150000"`) which is exactly 21 chars and matches the `parseOcc` pattern. Confirm this by checking `buildRow()` in `dashboard.js` — `data-symbol="${escapeHtml(pos.symbol)}"` stores the raw symbol, not the formatted display value.

No code changes needed if the regex and data attribute are correct. If `parseOcc` returns `null` for a known option row, debug the regex against the actual symbol string.

#### Manual verification checklist (for production-validator):

1. Open app at `http://127.0.0.1:8000`
2. Click an equity row → detail panel shows equity type, no option fields section
3. Click an option leg row → detail panel shows underlying, expiry, call/put, strike
4. Quote SSE event arrives → `last`, `bid`, `ask`, `ema_short`, `ema_long` update in real time
5. Clicking a different row switches the panel (old row loses `data-selected`, new row gains it)
6. Panel shows "select a position to view details" on first load (no row selected)
7. Chart placeholder shows "chart · coming in #7"

---

## Execution Order Summary

```
TASK 1  →  parse_occ() Python (TDD, green suite)
TASK 2  →  HTML structure (detail panel + panels-column wrapper)
TASK 3  →  CSS components (.detail-panel, .detail-row, etc.)
TASK 4  →  CSS layout split (≥1024px side-by-side)
TASK 5  →  JS row click + panel population + parseOcc()
TASK 6  →  JS handleQuote() update to live-update open panel
TASK 7  →  Verify OCC display wiring (no code if correct)
```

Tasks 2–4 can be done in parallel (CSS and HTML don't depend on each other). Task 5 depends on Tasks 2 and 3 (needs IDs and classes to exist). Task 6 depends on Task 5 (extends `handleQuote`).

---

## Key Decisions

1. **`parse_occ` in `state.py`** — keeps it importable in tests without a new module; the function is pure and stateless so it fits cleanly alongside other pure helpers.
2. **No `hidden` on `<aside>` at desktop** — the detail panel is always in the flex row at ≥1024px; show/hide is controlled on `#detail-empty` / `#detail-content` children, avoiding `display:flex !important` hacks.
3. **`panels-column` wrapper** — the tab strip + panels need to be wrapped to become a single flex child alongside the detail panel in the row layout. Without this, the panels become siblings of `detail-panel` and the tab strip/positions/orders would each be their own flex columns.
4. **`/api/quotes/{symbol}` for initial fetch** — already implemented; no new backend route needed. Returns empty `{}` before first quote arrives, handled gracefully in JS.
5. **JS `parseOcc` mirrors Python** — the regex pattern is equivalent; the expiry formatting uses `Date.toLocaleDateString` which produces the same "Jan 19 2024" format as Python's `strftime("%b %-d %Y")`.

---

## Risks and Mitigations

1. **`%-d` strftime format on non-Linux** — the CI environment is Linux (confirmed), so `%-d` strips the leading zero correctly. If ever run on Windows/macOS CI, replace with `%#d` (Windows) or `str(dt.day)` (portable). Mitigation: the existing test `test_parse_occ_call_aapl` asserts `"Jan 19 2024"` (no leading zero), which will catch this if CI changes platform.

2. **OCC symbol length edge cases** — the Python regex uses `re.fullmatch(r"([A-Z ]{6})(\d{6})([CP])(\d{8})", symbol)` which requires exactly 21 characters total. If a real symbol has extra whitespace (e.g., trailing space after the 21 chars), it will return `None`. Mitigation: the tests cover the canonical format; if edge cases arise, add `.strip()` before the match.

3. **Mobile layout** — the detail panel is hidden at `< 1024px` (CSS `display: none`). There is no mobile "back" button or swipe-to-show gesture. This is acceptable per acceptance criteria (criteria 1–8 do not mention mobile detail panel behavior). If mobile support is needed in a future issue, a tab-based approach (add "detail" to the tab strip) is the cleanest path.

---

## Self-Review Checklist

- [ ] `parse_occ` handles all 6 test cases: AAPL call, AAPL put, SPY 3-char, QQQ 3-char, equity (None), fractional strike
- [ ] `parse_occ` imported at module level in `state.py` (not buried in a method)
- [ ] `<aside>` has `aria-label="Position detail"` for accessibility
- [ ] `#detail-empty` visible by default; `#detail-content` has `hidden` attribute in HTML
- [ ] `panels-column` wrapper added in HTML and targeted in CSS for the layout split
- [ ] Detail panel width 280px defined in both `components.css` (component) and confirmed in `layout.css` (layout shows it)
- [ ] `data-selected` attribute is set on the selected `<tr>` and removed from the previous one
- [ ] `cursor: pointer` on tbody rows added in `components.css`
- [ ] `handleQuote` still updates the positions table (existing behavior preserved)
- [ ] `handleQuote` additionally calls `updateDetailQuote` + `updateDetailPnl` when `selectedSymbol` matches
- [ ] P&L uses correct multiplier (×100 for options, ×1 for equity) in `updateDetailPnl`
- [ ] Chart placeholder is present and shows descriptive text
- [ ] Full test suite passes with 0 regressions after Task 1
- [ ] No `console.log` or debug statements left in JS
