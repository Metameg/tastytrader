# Phase 1 — Tests Report (Red Phase)

## Status
12 new failing tests written. All 137 original tests still pass (139 total passing = 137 original + 2 new tests that verify already-implemented behavior).

## Failures breakdown

### tests/test_dashboard.py (8 failing)
All fail with: `AttributeError: 'DashboardState' object has no attribute 'get_chart_data'`

- `test_on_candle_accumulates_candles_for_symbol` — on_candle must store candles; get_chart_data must return them
- `test_on_candle_normalizes_dxfeed_suffix_to_plain_symbol` — AAPL{=d} stored under plain AAPL key
- `test_on_candle_accumulates_multiple_candles_in_order` — multiple calls append in order
- `test_get_chart_data_unknown_symbol_returns_empty_arrays` — returns `{"labels":[], "close":[], "ema_short":[], "ema_long":[]}`
- `test_get_chart_data_returns_required_keys` — dict has labels/close/ema_short/ema_long
- `test_get_chart_data_close_matches_stored_close_prices` — close array equals accumulated closes
- `test_get_chart_data_ema_arrays_same_length_as_close` — both EMA arrays length == close length
- `test_get_chart_data_ema_final_value_matches_ema_calculator` — final EMA value matches independently-computed EMACalculator(10)/(20)

### tests/dashboard/test_app.py (4 failing)
Fail with: `assert 404 == 200` (route does not exist yet)

- `test_get_chart_returns_200_when_candle_data_exists` — 404 because /api/chart/{symbol} not registered
- `test_get_chart_returns_required_keys_when_data_exists` — 404 → wrong keys in response
- `test_get_chart_close_reflects_stored_closes` — 404 → KeyError on 'close'
- `test_get_chart_returns_200_with_empty_arrays_when_no_data` — 404 for unknown symbol

### tests/test_streamer.py (0 failing — 1 new passing)
`test_candle_subscription_from_time_is_integer` PASSES because the streamer already sends `int(from_time)` in `_subscribe_all` and `add_candle`. The CONTEXT.md confirms this is existing behavior. The test verifies correctness and serves as a regression guard.

Similarly, `test_on_candle_still_broadcasts_candle_event` PASSES because `on_candle` already broadcasts to subscribers.

## Key decisions

1. **get_chart_data return shape**: `{"labels": [...], "close": [...], "ema_short": [...], "ema_long": []}` — matches CONTEXT.md suggestion exactly; labels will hold date/time strings from candle eventTime or index.

2. **EMA periods**: short=10, long=20 — matches `on_quote` in `state.py` and CONTEXT.md specification. EMACalculator is NOT seeded (no `.seed()` call) — the chart uses the canonical warm-up: values are None until the period is reached, then become floats. Tests assert final value only, using `pytest.approx`, not the seeded display-mode used by on_quote.

3. **Symbol normalization**: `{=d}` suffix stripped via regex `re.sub(r'\{.*?\}', '', symbol)` or simple split on `{`. Tests assert that `get_chart_data("AAPL{=d}")` returns empty arrays while `get_chart_data("AAPL")` returns data.

4. **Route cleanup pattern**: The route tests follow the existing pattern from `test_get_quote_returns_required_fields_when_quote_exists` — seed state directly on `app.state.dashboard`, call the route, then clean up via `candles.pop(symbol, None)`. The cleanup uses `hasattr` guard since `candles` doesn't exist yet.

5. **Streamer fromTime test**: Test passes against existing implementation — this is correct behavior confirmed by CONTEXT.md. It serves as a regression guard. The test passes an intentional float (`1_234_567_890.5`) and asserts `isinstance(val, int)` and `val == int(from_time_float)`.

## Concerns / risks

1. **EMA null values in arrays**: The `ema_short`/`ema_long` arrays will contain `None` for indices before the warm-up period (first 10/20 closes). Tests assert length equality and only the final value — this is consistent. The implementation agent should handle None values gracefully (Chart.js accepts null in datasets).

2. **Test isolation for app.py tests**: The `client` fixture is `scope="module"` — all tests share the same app instance and `app.state.dashboard`. The candle-accumulation route tests must clean up after themselves to avoid polluting subsequent tests. Current cleanup uses `hasattr(app.state.dashboard, "candles")` guard, which is defensive since the attribute doesn't exist yet.

3. **Candle history growth**: No cap on history length is tested. The implementation should probably cap at ~90 days of candles to avoid unbounded memory. This is not tested in the red phase but the implementation agent should consider it.
