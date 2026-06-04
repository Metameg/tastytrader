# Implementation Plan — Issue #7: Daily OHLC Chart with EMA Overlays

## Goal
Deliver a Chart.js line chart in the dashboard detail panel showing close price + EMA-10 (green) + EMA-20 (amber) for the selected holding. Candle history is stored server-side per symbol; chart data is fetched on row click via `GET /api/chart/{symbol}`. Chart is hidden (not errored) when no candle data exists.

## Architecture
```
DXLink candle stream
    → DashboardStreamer.candle_callback
    → DashboardState.on_candle(ohlc)       ← append to self.candles[plain_symbol]
    → DashboardState.get_chart_data(sym)    ← compute EMA arrays from stored close prices
    → GET /api/chart/{symbol}               ← subscribe candle feed + return chart data
    → dashboard.js row-click handler        ← fetch + call updateChart()
    → chart.js updateChart()                ← Chart.js destroy+reinit
```

## Tech Stack
- **Backend**: Python 3.12, FastAPI, `src.strategy.EMACalculator` (already in repo)
- **Frontend**: Vanilla JS (ES modules via defer), Chart.js 4.x via CDN
- **CSS tokens**: `--green` (#3dd68c) for EMA-10, `--yellow` (#f5a623) for EMA-20 (amber), `--text-dim` (#b0bbc8) for close price line. No new tokens needed — existing semantic tokens cover all colors.

## Color Tokens (from tokens.css)
- Close price line: `--text-dim` (`#b0bbc8`) — neutral/dim
- EMA-10 (short): `--green` (`#3dd68c`)
- EMA-20 (long): `--yellow` (`#f5a623`) — this is the amber token

---

## Phase 1 — Backend: DashboardState candle storage + get_chart_data

### Task 1.1 — Add candle history storage to DashboardState

**Files**: `dashboard/state.py`, `tests/test_dashboard.py`

**RED** — The Phase-1 TDD agent writes these tests. For completeness the plan shows what they assert:

```python
# tests/test_dashboard.py (new tests added by Phase-1 TDD agent)

def test_on_candle_stores_candle_keyed_by_plain_symbol():
    """on_candle appends the candle dict to self.candles[plain_symbol],
    stripping the {=d} suffix from eventSymbol."""
    state = DashboardState()
    ohlc = {"eventSymbol": "AAPL{=d}", "open": 100.0, "high": 105.0,
            "low": 99.0, "close": 102.0, "time": 1700000000000}
    state.on_candle(ohlc)
    assert "AAPL" in state.candles
    assert len(state.candles["AAPL"]) == 1
    assert state.candles["AAPL"][0]["close"] == 102.0


def test_on_candle_strips_suffix_preserves_plain_symbol():
    """Symbol 'TSLA{=d}' must key as 'TSLA' in state.candles."""
    state = DashboardState()
    state.on_candle({"eventSymbol": "TSLA{=d}", "close": 200.0, "time": 1700000000000})
    assert "TSLA" in state.candles
    assert "TSLA{=d}" not in state.candles


def test_on_candle_accumulates_multiple_candles():
    """Multiple on_candle calls for the same symbol must accumulate in order."""
    state = DashboardState()
    for i, close in enumerate([100.0, 101.0, 102.0]):
        state.on_candle({"eventSymbol": "AAPL{=d}", "close": close,
                         "time": 1700000000000 + i})
    assert len(state.candles["AAPL"]) == 3
    assert state.candles["AAPL"][2]["close"] == 102.0


def test_on_candle_still_broadcasts_event():
    """on_candle must still put a 'candle' SSE event on subscriber queues
    (existing behaviour must not regress)."""
    state = DashboardState()
    queue = asyncio.Queue()
    state.subscribers.append(queue)
    state.on_candle({"eventSymbol": "AAPL{=d}", "close": 102.0, "time": 1700000000000})
    assert not queue.empty()
    item = queue.get_nowait()
    assert item["event"] == "candle"


def test_get_chart_data_unknown_symbol_returns_empty_arrays():
    """Unknown symbol must return empty arrays — never an error."""
    state = DashboardState()
    result = state.get_chart_data("ZZZZ")
    assert result == {"labels": [], "close": [], "ema_short": [], "ema_long": []}


def test_get_chart_data_returns_correct_keys():
    """Return dict must have exactly these four keys."""
    state = DashboardState()
    result = state.get_chart_data("ZZZZ")
    assert set(result.keys()) == {"labels", "close", "ema_short", "ema_long"}


def test_get_chart_data_ema_arrays_computed_from_known_close_sequence():
    """With a deterministic close sequence, ema_short and ema_long must match
    the EMACalculator output for short=10, long=20."""
    from src.strategy import EMACalculator
    state = DashboardState()
    closes = [float(100 + i) for i in range(25)]
    for i, c in enumerate(closes):
        state.on_candle({"eventSymbol": "AAPL{=d}", "close": c, "time": 1700000000000 + i})

    result = state.get_chart_data("AAPL")

    # Recompute expected EMA values independently
    ema_s = EMACalculator(10)
    ema_l = EMACalculator(20)
    expected_short = [ema_s.update(c) for c in closes]
    expected_long  = [ema_l.update(c) for c in closes]

    assert result["close"] == closes
    assert len(result["ema_short"]) == 25
    assert len(result["ema_long"]) == 25
    # Compare non-None values (warm-up period returns None for raw EMACalculator)
    for i, (es, el) in enumerate(zip(result["ema_short"], result["ema_long"])):
        if expected_short[i] is not None:
            assert abs(es - expected_short[i]) < 1e-9
        if expected_long[i] is not None:
            assert abs(el - expected_long[i]) < 1e-9


def test_get_chart_data_labels_are_sorted_by_time():
    """labels must be in ascending time order (matching candle order)."""
    state = DashboardState()
    # Insert out of order (streamer may deliver out of order)
    state.on_candle({"eventSymbol": "AAPL{=d}", "close": 102.0, "time": 1700000002000})
    state.on_candle({"eventSymbol": "AAPL{=d}", "close": 100.0, "time": 1700000000000})
    state.on_candle({"eventSymbol": "AAPL{=d}", "close": 101.0, "time": 1700000001000})
    result = state.get_chart_data("AAPL")
    assert result["close"] == [100.0, 101.0, 102.0]
```

**GREEN** — Edit `dashboard/state.py`:

```python
# In __post_init__, add after existing EMA dicts:
self.candles: dict[str, list[dict]] = {}

# Replace on_candle method:
def on_candle(self, ohlc: dict) -> None:
    # Normalize eventSymbol: strip {=d} suffix to get plain symbol
    raw_sym: str = ohlc.get("eventSymbol", "")
    plain_sym = raw_sym.split("{")[0] if "{" in raw_sym else raw_sym
    if plain_sym:
        self.candles.setdefault(plain_sym, []).append(ohlc)
    # Existing broadcast (must not regress)
    payload = {"event": "candle", "data": ohlc}
    for q in self.subscribers:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass

# Add get_chart_data method (after on_candle):
def get_chart_data(self, symbol: str) -> dict:
    """Return chart data for Chart.js: sorted close prices + EMA-10/20 arrays.

    Returns empty arrays if symbol is unknown or has no candle history.
    """
    candles = self.candles.get(symbol)
    if not candles:
        return {"labels": [], "close": [], "ema_short": [], "ema_long": []}

    sorted_candles = sorted(candles, key=lambda c: c.get("time", 0))
    closes = [float(c["close"]) for c in sorted_candles]
    labels = [c.get("time", i) for i, c in enumerate(sorted_candles)]

    ema_s = EMACalculator(10)
    ema_l = EMACalculator(20)
    ema_short_vals = [ema_s.update(p) for p in closes]
    ema_long_vals  = [ema_l.update(p) for p in closes]

    # Convert None (warm-up period) to null-safe float or keep None
    # JS chart.js will receive null for warm-up points and skip them
    return {
        "labels": labels,
        "close": closes,
        "ema_short": ema_short_vals,
        "ema_long": ema_long_vals,
    }
```

**REFACTOR** — No structural changes needed; method is < 20 lines.

**COMMIT**: `git commit -m "feat(#7): store candle history per symbol; add get_chart_data with EMA-10/20"`

---

## Phase 2 — Backend: GET /api/chart/{symbol} route

### Task 2.1 — Add chart route + candle subscription trigger

**Files**: `dashboard/app.py`, `tests/dashboard/test_app.py`

**RED** — The Phase-1 TDD agent writes these tests. For completeness:

```python
# tests/dashboard/test_app.py (new tests added by Phase-1 TDD agent)

def test_get_chart_returns_200_and_correct_shape(client):
    """GET /api/chart/{symbol} must return 200 with the four expected keys."""
    from dashboard.app import app
    app.state.dashboard.candles["AAPL"] = [
        {"eventSymbol": "AAPL{=d}", "close": 150.0, "time": 1700000000000},
        {"eventSymbol": "AAPL{=d}", "close": 151.0, "time": 1700000086400000},
    ]
    response = client.get("/api/chart/AAPL")
    app.state.dashboard.candles.pop("AAPL", None)
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"labels", "close", "ema_short", "ema_long"}
    assert isinstance(data["close"], list)
    assert isinstance(data["ema_short"], list)
    assert isinstance(data["ema_long"], list)


def test_get_chart_unknown_symbol_returns_empty_arrays(client):
    """Unknown symbol must return empty arrays (not 404), so JS hides the chart."""
    response = client.get("/api/chart/UNKNOWN_SYM_XYZ_99")
    assert response.status_code == 200
    data = response.json()
    assert data == {"labels": [], "close": [], "ema_short": [], "ema_long": []}


def test_get_chart_calls_add_candle_when_streamer_present(client):
    """Route must call streamer.add_candle(symbol, from_time) when app.state.streamer exists."""
    from dashboard.app import app
    import time

    mock_streamer = MagicMock()
    app.state.streamer = mock_streamer

    response = client.get("/api/chart/AAPL")
    assert response.status_code == 200

    mock_streamer.add_candle.assert_called_once()
    call_args = mock_streamer.add_candle.call_args
    assert call_args[0][0] == "AAPL"  # positional symbol arg
    from_time_arg = call_args[0][1]
    assert isinstance(from_time_arg, int)
    expected_approx = int(time.time() - 60 * 86400)
    assert abs(from_time_arg - expected_approx) < 5  # within 5 seconds


def test_get_chart_no_error_when_streamer_absent(client):
    """If app.state.streamer does not exist (lifespan failed), route must not crash."""
    from dashboard.app import app
    if hasattr(app.state, "streamer"):
        del app.state.streamer
    response = client.get("/api/chart/AAPL")
    assert response.status_code == 200
    # Restore mock for other tests
    app.state.streamer = MagicMock()


def test_get_chart_route_is_registered(client):
    """The /api/chart/{symbol} route must appear in the app routing table."""
    from dashboard.app import app
    from starlette.routing import Route
    paths = [r.path for r in app.routes if isinstance(r, Route)]
    assert "/api/chart/{symbol}" in paths
```

**GREEN** — Edit `dashboard/app.py` — add one import and one route:

```python
# Add to imports at top of file:
import time

# Add route after the existing /api/quotes/{symbol} route:
@app.get("/api/chart/{symbol}")
async def get_chart(symbol: str, request: Request):
    state: DashboardState = request.app.state.dashboard
    # Trigger daily candle subscription if streamer is available.
    # "Subscribe on selection" pattern: first chart fetch for a symbol
    # triggers the candle feed subscription. Idempotent — streamer
    # handles duplicate subscriptions gracefully.
    if hasattr(request.app.state, "streamer"):
        from_time = int(time.time() - 60 * 86400)
        request.app.state.streamer.add_candle(symbol, from_time)
    return state.get_chart_data(symbol)
```

**REFACTOR** — None needed; route body is 5 lines.

**COMMIT**: `git commit -m "feat(#7): add GET /api/chart/{symbol} with candle subscription trigger"`

---

## Phase 3 — CSS: Chart container styles

### Task 3.1 — Add chart container CSS to components.css

**Files**: `dashboard/static/css/components.css`

No inline styles allowed. The chart `<canvas>` must be sized via CSS classes. Replace the `.detail-chart-placeholder` block and add new `.detail-chart-area` + `.detail-chart-hidden` classes.

**GREEN** — Edit `dashboard/static/css/components.css` — replace the existing placeholder block and append chart styles:

```css
/* Replace existing .detail-chart-placeholder block: */
/* OLD:
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
*/

/* NEW — keep old placeholder class for backwards compat during transition,
   add chart-area classes: */
.detail-chart-area {
  flex: 1;
  min-height: 160px;
  border-top: 1px solid var(--border);
  margin-top: var(--sp-2);
  padding: var(--sp-2) var(--sp-3) var(--sp-3);
  position: relative;
}

.detail-chart-area.detail-chart-hidden {
  display: none;
}

.detail-chart-canvas {
  display: block;
  width: 100%;
}
```

**NOTE**: The `<canvas>` in the template will use `width` and `height` HTML attributes (not `style=`) for the intrinsic size hint, plus the `.detail-chart-canvas` CSS class for display:block + width:100%.

**COMMIT**: `git commit -m "feat(#7): add chart area CSS classes to components.css"`

---

## Phase 4 — HTML: Chart.js CDN + canvas element

### Task 4.1 — Add Chart.js CDN script and replace placeholder with canvas

**Files**: `dashboard/templates/index.html`

**Constraint**: `test_html_has_no_inline_styles` forbids `style="` in the HTML response. Use `width`/`height` HTML attributes on `<canvas>` (these are NOT inline styles) plus CSS classes.

**GREEN** — Two edits to `index.html`:

**Edit 1** — Add Chart.js CDN before the defer scripts (before `<script src="/static/js/main.js" defer>`):

```html
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
  <script src="/static/js/chart.js" defer></script>
  <script src="/static/js/main.js" defer></script>
  <script src="/static/js/order-form.js" defer></script>
  <script src="/static/js/dashboard.js" defer></script>
```

Note: Chart.js CDN is loaded WITHOUT `defer` so it is synchronously available before the deferred `chart.js` module executes.

**Edit 2** — Replace the placeholder div with a chart container:

```html
          <!-- Chart area (issue #7) — hidden until candle data arrives -->
          <div class="detail-chart-area detail-chart-hidden" id="detail-chart-area">
            <canvas class="detail-chart-canvas" id="detail-chart-canvas" width="240" height="140"></canvas>
          </div>
```

Replaces:
```html
          <!-- Chart placeholder (chart implemented in issue #7) -->
          <div class="detail-chart-placeholder" id="detail-chart-placeholder">
            <span class="detail-chart-msg">chart · coming in #7</span>
          </div>
```

**COMMIT**: `git commit -m "feat(#7): add Chart.js CDN and chart canvas to index.html"`

---

## Phase 5 — Frontend: chart.js module

### Task 5.1 — Create dashboard/static/js/chart.js

**Files**: `dashboard/static/js/chart.js` (new file)

**GREEN** — Create the file:

```javascript
// dashboard/static/js/chart.js
// Exposes updateChart(labels, close, emaShort, emaLong) globally.
// Destroy + re-init on each call so switching symbols always shows fresh data.
// Uses design tokens via getComputedStyle for colors.

(function () {
  let _chart = null;

  function _token(name) {
    return getComputedStyle(document.documentElement)
      .getPropertyValue(name).trim();
  }

  /**
   * Render or re-render the OHLC close + EMA chart.
   *
   * @param {Array}  labels    - x-axis labels (timestamps or indices)
   * @param {Array}  close     - close price array (may contain nulls during warm-up)
   * @param {Array}  emaShort  - EMA-10 array (may contain nulls)
   * @param {Array}  emaLong   - EMA-20 array (may contain nulls)
   */
  function updateChart(labels, close, emaShort, emaLong) {
    const canvas = document.getElementById('detail-chart-canvas');
    const area   = document.getElementById('detail-chart-area');
    if (!canvas || !area) return;

    // Destroy previous instance to avoid canvas reuse errors
    if (_chart) {
      _chart.destroy();
      _chart = null;
    }

    const colorClose = _token('--text-dim');
    const colorShort = _token('--green');
    const colorLong  = _token('--yellow');
    const colorGrid  = _token('--border');

    _chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'close',
            data: close,
            borderColor: colorClose,
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
            spanGaps: true,
          },
          {
            label: 'ema 10',
            data: emaShort,
            borderColor: colorShort,
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
            spanGaps: true,
          },
          {
            label: 'ema 20',
            data: emaLong,
            borderColor: colorLong,
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.1,
            spanGaps: true,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: {
            display: true,
            labels: {
              color: _token('--text-dim'),
              font: { size: 10 },
              boxWidth: 12,
              padding: 8,
            },
          },
          tooltip: { enabled: false },
        },
        scales: {
          x: {
            display: false,
          },
          y: {
            grid: { color: colorGrid },
            ticks: {
              color: _token('--text-muted'),
              font: { size: 10 },
              maxTicksLimit: 4,
            },
          },
        },
      },
    });

    // Reveal the chart area
    area.classList.remove('detail-chart-hidden');
  }

  // Export to global scope so dashboard.js can call it
  window.updateChart = updateChart;
})();
```

**REFACTOR** — File is ~80 lines, well under the 500-line limit. `_token()` helper avoids repeating `getComputedStyle` calls.

**COMMIT**: `git commit -m "feat(#7): add chart.js module with Chart.js destroy+reinit and token-based colors"`

---

## Phase 6 — Frontend: dashboard.js row-click integration

### Task 6.1 — Fetch chart data on row selection and call updateChart

**Files**: `dashboard/static/js/dashboard.js`

**GREEN** — Edit the row-click handler in `dashboard.js`. The current handler ends with a `.then(quote => { populateDetailPanel(...) }).catch(...)` block. After `populateDetailPanel(...)` call, add chart fetch logic:

The existing click handler block (lines 256–267 in current file):
```javascript
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
```

Replace with:
```javascript
  fetch(`/api/quotes/${encodeURIComponent(symbol)}`)
    .then(r => r.json())
    .then(quote => {
      populateDetailPanel(symbol, instrumentType, qty, avgCost,
        Object.keys(quote).length ? quote : null);
    })
    .catch(() => {
      populateDetailPanel(symbol, instrumentType, qty, avgCost, null);
    });

  // Fetch chart data — hide chart area if no candle data yet (no error shown)
  const chartArea = document.getElementById('detail-chart-area');
  if (chartArea) chartArea.classList.add('detail-chart-hidden');

  fetch('/api/chart/' + encodeURIComponent(symbol))
    .then(r => r.json())
    .then(data => {
      if (data.close && data.close.length > 0 && typeof window.updateChart === 'function') {
        window.updateChart(data.labels, data.close, data.ema_short, data.ema_long);
      }
      // If arrays are empty, chart area stays hidden — no error
    });
    // No .catch() — network errors silently leave chart hidden
```

**REFACTOR** — No structural change needed. The guard `typeof window.updateChart === 'function'` is defensive for cases where Chart.js CDN fails to load (cert sandbox).

**COMMIT**: `git commit -m "feat(#7): fetch and render OHLC chart on row selection in dashboard.js"`

---

## Self-Review Checklist

### Spec Coverage
- [x] AC1: selecting a holding renders Chart.js line chart — covered by Phase 4+5+6
- [x] AC2: chart shows close, EMA-10 (green), EMA-20 (amber) — chart.js datasets + token colors
- [x] AC3: chart re-fetches on new selection — row-click always fetches, chart.js destroys+reinits
- [x] AC4: chart hidden when no candle data — `detail-chart-hidden` class, no error shown
- [x] AC5: DashboardStreamer candle subscription test — route triggers `add_candle` on each fetch
- [x] AC6: `get_chart_data` EMA unit test — Phase 1 test asserts deterministic EMA computation

### Constraint Compliance
- [x] No `style="` in index.html — canvas uses HTML `width`/`height` attributes + CSS class
- [x] All files < 500 lines — chart.js ~80 lines, state.py additions ~20 lines, app.py +6 lines
- [x] Colors from tokens.css — `--green`, `--yellow`, `--text-dim` used via `getComputedStyle`
- [x] EMACalculator reused from `src/strategy.py` — not reimplemented
- [x] Return shape: `{"labels", "close", "ema_short", "ema_long"}` — matches test expectations
- [x] Candle subscription triggered in route handler — "subscribe on selection" pattern
- [x] `fromTime = int(time.time() - 60*86400)` — 60 days lookback, integer

### Placeholder Scan
No placeholder text remains. All code blocks contain exact, runnable Python/JS.

### Type/Name Consistency
- `get_chart_data(symbol: str) -> dict` — consistent across state.py, test assertions, route
- `candles: dict[str, list[dict]]` — typed in state.py `__post_init__`
- `ema_short` / `ema_long` — consistent snake_case in Python dict keys; JS receives `data.ema_short`, `data.ema_long`
- `detail-chart-area` / `detail-chart-hidden` — consistent HTML id and CSS class names
- `detail-chart-canvas` — consistent `id` used in chart.js `getElementById`

---

## Execution Order (critical path)

```
Task 1.1 (state.py candles + get_chart_data)
    → Task 2.1 (app.py route)
    → Task 3.1 (CSS classes)           \
    → Task 4.1 (HTML canvas + CDN)      |- parallel after Task 2.1
    → Task 5.1 (chart.js module)       /
    → Task 6.1 (dashboard.js integration) — depends on Tasks 4.1 + 5.1
```

Tasks 3.1, 4.1, 5.1 are independent of each other and can run in parallel after Task 2.1.

## Risks

1. **Chart.js CDN unavailable in cert sandbox**: mitigated by the `typeof window.updateChart === 'function'` guard in dashboard.js — chart stays hidden, no JS error.
2. **EMACalculator warm-up returns None for early candles**: `get_chart_data` returns the raw list including `None` values. Chart.js `spanGaps: true` skips null points cleanly. No filtering needed.
3. **Candle data never arrives (sandbox limitation)**: AC4 specifically handles this — empty arrays → chart hidden. No fallback UI needed beyond the hidden state.
