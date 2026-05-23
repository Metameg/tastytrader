# TastyTrader — Design Spec
_Date: 2026-05-22_

## Overview

A continuous Python daemon that streams live quotes from TastyTrade's sandbox, detects EMA10/EMA20 crossover signals, and automatically places equity option orders on a paper trading account visible in TastyTrade's web portal.

---

## Constraints & Environment

- **Language:** Python (asyncio)
- **API base URL:** `https://api.cert.tastyworks.com`
- **WebSocket streamer:** `wss://streamer.cert.tastyworks.com`
- **Auth:** Session token (POST `/sessions` with username/password — no OAuth2)
- **Instrument:** Equity options (OCC symbol format)
- **Mode:** Sandbox / paper trading only

---

## Architecture

Three layers connected by `asyncio.Queue` instances, plus an auth module and orchestrator.

```
config/
  settings.toml          ← symbol, account, EMA periods, thresholds, hardcoded OCC symbols
  .env                   ← credentials (never committed)
src/
  auth.py                ← session token login and refresh
  streamer.py            ← WebSocket → price_queue
  strategy.py            ← price_queue → EMA state machine → signal_queue
  executor.py            ← signal_queue → REST order placement
  main.py                ← wires all layers, runs asyncio tasks, handles shutdown
tests/
  test_strategy.py
  test_executor.py
```

### Data Flow

```
streamer.cert (WebSocket / DXFeed)
  → Streamer emits PriceEvent(symbol, price, timestamp)
    → price_queue (asyncio.Queue)
      → Strategy computes EMA10/EMA20, emits TradeSignal(direction)
        → signal_queue (asyncio.Queue)
          → Executor places option order via REST POST /orders
            → api.cert.tastyworks.com
```

---

## Layer Designs

### Auth (`src/auth.py`)

- On startup: POST `{username, password}` to `/sessions`
- Response yields `session-token` (short-lived) and `remember-token` (for refresh)
- Token stored in memory; passed into Streamer and Executor at construction
- On 401 mid-session: re-authenticates automatically
- Credentials loaded from `.env` via `python-dotenv`; never hardcoded

### Streamer (`src/streamer.py`)

- Opens WebSocket to `wss://streamer.cert.tastyworks.com`
- Uses DXFeed protocol: sends subscription message for configured symbol, receives `Quote` events
- Extracts `last`, `bid`, and `ask` from each Quote event, puts `PriceEvent(symbol, last, bid, ask, timestamp)` onto `price_queue`
- Reconnection: waits 5s on drop, retries with exponential backoff capped at 60s
- No computation — pure I/O boundary that normalizes DXFeed wire format

### Strategy (`src/strategy.py`)

- Consumes `PriceEvent` from `price_queue`
- Maintains rolling price buffer; seeds EMA from simple average of first N prices
- No signals emitted until buffer has ≥ 20 prices

**EMA update:**
```
k = 2 / (period + 1)
ema = price * k + previous_ema * (1 - k)
```

**Signal state machine:**

| State | Condition | Action |
|---|---|---|
| `WATCHING` | No proximity | Monitor EMA gap |
| `APPROACHING` | `\|EMA10 - EMA20\| < threshold` and narrowing | Log warning, arm |
| `CROSSED` | EMA10 and EMA20 swap sides | Emit `TradeSignal` |

- `BULLISH` signal: EMA10 crosses above EMA20
- `BEARISH` signal: EMA10 crosses below EMA20
- After signal fires: enters `COOLDOWN` (configurable, default 300s) to prevent re-firing on choppy crosses
- No I/O — pure state machine; fully unit-testable with a list of prices

### Executor (`src/executor.py`)

- Consumes `TradeSignal` from `signal_queue`; `TradeSignal` carries the triggering `PriceEvent` so bid/ask are available
- Places order via `POST /accounts/{account_number}/orders`
- `BULLISH` → buy call OCC symbol; `BEARISH` → buy put OCC symbol (both hardcoded in config)
- Order type: Limit at `(bid + ask) / 2`; time-in-force: Day; quantity: 1
- Logs order response (order ID) to stdout as structured JSON
- No position management or exit logic in v1

Sample order body:
```json
{
  "order-type": "Limit",
  "time-in-force": "Day",
  "price": "<mid>",
  "legs": [{
    "instrument-type": "Equity Option",
    "symbol": "<OCC symbol>",
    "quantity": 1,
    "action": "Buy to Open"
  }]
}
```

### Orchestrator (`src/main.py`)

- Creates `price_queue` and `signal_queue` (`asyncio.Queue`)
- Initializes Auth, Streamer, Strategy, Executor
- Runs all three layer tasks concurrently via `asyncio.gather`
- Catches `SIGINT`/`SIGTERM`, cancels all tasks cleanly
- Logs all signals and order responses as structured JSON lines to stdout

---

## Configuration (`config/settings.toml`)

```toml
[market]
symbol = "AAPL"
ema_short = 10
ema_long = 20
threshold = 0.05          # dollars — proximity threshold to arm APPROACHING state
cooldown_seconds = 300

[execution]
account_number = "..."
call_symbol = "AAPL  240119C00150000"
put_symbol   = "AAPL  240119P00150000"
quantity = 1
```

Credentials (`config/.env`):
```
TASTYTRADE_USERNAME=...
TASTYTRADE_PASSWORD=...
```

---

## Dependencies

| Package | Purpose |
|---|---|
| `websockets` | Async WebSocket client (Streamer) |
| `httpx` | Async HTTP client (Auth, Executor) |
| `python-dotenv` | Load credentials from `.env` |
| `tomllib` (stdlib 3.11+) | Parse `settings.toml` |

---

## Testing Strategy

- **Strategy:** Unit-tested with synthetic price lists — no live connection needed
- **Executor:** Unit-tested with a mocked `httpx` client — verifies correct order body construction
- **Streamer / Auth / Orchestrator:** Integration-tested manually against sandbox

---

## Out of Scope (v1)

- Contract selection logic (strike, expiration, delta targeting) — hardcoded OCC symbols only
- Position tracking or exit orders
- Multiple symbols or strategies running concurrently
- Persistent logging to file or database
- Any production (non-sandbox) usage
