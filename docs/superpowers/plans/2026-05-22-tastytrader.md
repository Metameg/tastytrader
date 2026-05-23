# TastyTrader — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python async daemon that streams live quotes from TastyTrade's sandbox, detects EMA10/EMA20 crossover signals, and places equity option orders on a paper trading account.

**Architecture:** Three asyncio layers connected by queues — Streamer (WebSocket → price_queue), Strategy (price_queue → EMA state machine → signal_queue), Executor (signal_queue → REST order placement) — wired by a main orchestrator with SIGINT-clean shutdown.

**Tech Stack:** Python 3.11+, websockets, httpx, python-dotenv, pytest, pytest-asyncio

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Dependencies, pytest config |
| `config/settings.toml` | Symbol, EMA params, execution config |
| `config/.env.example` | Credential template |
| `src/__init__.py` | Empty package marker |
| `src/models.py` | `PriceEvent`, `TradeSignal`, `Direction`, `StrategyState` dataclasses/enums |
| `src/config.py` | Typed config loading from `.env` + `settings.toml` |
| `src/auth.py` | Session token login and refresh via REST |
| `src/strategy.py` | `EMACalculator` + `Strategy` state machine |
| `src/executor.py` | `Executor` — REST order placement |
| `src/streamer.py` | `Streamer` — DXLink WebSocket → price_queue |
| `src/main.py` | Orchestrator — wires queues, runs TaskGroup, handles SIGINT |
| `tests/__init__.py` | Empty package marker |
| `tests/test_auth.py` | Auth unit tests (mocked httpx) |
| `tests/test_strategy.py` | EMA + state machine unit tests |
| `tests/test_executor.py` | Executor unit tests (mocked httpx) |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `config/settings.toml`
- Create: `config/.env.example`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create pyproject.toml**

```toml
[project]
name = "tastytrader"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "websockets>=12.0",
    "httpx>=0.27.0",
    "python-dotenv>=1.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create .gitignore**

```
.env
__pycache__/
*.pyc
.pytest_cache/
dist/
*.egg-info/
```

- [ ] **Step 3: Create config/settings.toml**

```toml
[market]
symbol = "AAPL"
ema_short = 10
ema_long = 20
threshold = 0.05
cooldown_seconds = 300

[execution]
account_number = "REPLACE_ME"
call_symbol = "AAPL  240119C00150000"
put_symbol   = "AAPL  240119P00150000"
quantity = 1
```

- [ ] **Step 4: Create config/.env.example**

```
TASTYTRADE_USERNAME=your_sandbox_username
TASTYTRADE_PASSWORD=your_sandbox_password
```

Copy to `config/.env` and fill in your sandbox credentials. Add `config/.env` to `.gitignore`.

Update `.gitignore` to also include:
```
config/.env
```

- [ ] **Step 5: Create empty package markers**

Create `src/__init__.py` and `tests/__init__.py` as empty files.

- [ ] **Step 6: Install dependencies**

```bash
pip install -e ".[dev]"
```

Expected: No errors. `pytest` command is now available.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore config/ src/__init__.py tests/__init__.py
git commit -m "chore: project scaffolding"
```

---

## Task 2: Data Models

**Files:**
- Create: `src/models.py`

No tests — these are pure dataclasses with no logic.

- [ ] **Step 1: Write src/models.py**

```python
from dataclasses import dataclass
from enum import Enum


class Direction(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class StrategyState(Enum):
    WATCHING = "WATCHING"
    APPROACHING = "APPROACHING"
    COOLDOWN = "COOLDOWN"


@dataclass
class PriceEvent:
    symbol: str
    last: float
    bid: float
    ask: float
    timestamp: float


@dataclass
class TradeSignal:
    direction: Direction
    price_event: PriceEvent
```

- [ ] **Step 2: Commit**

```bash
git add src/models.py
git commit -m "feat: add core data models"
```

---

## Task 3: Config Module

**Files:**
- Create: `src/config.py`

- [ ] **Step 1: Write src/config.py**

```python
import tomllib
import os
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path


@dataclass
class MarketConfig:
    symbol: str
    ema_short: int
    ema_long: int
    threshold: float
    cooldown_seconds: int


@dataclass
class ExecutionConfig:
    account_number: str
    call_symbol: str
    put_symbol: str
    quantity: int


@dataclass
class AppConfig:
    username: str
    password: str
    market: MarketConfig
    execution: ExecutionConfig


def load_config(
    settings_path: str = "config/settings.toml",
    env_path: str = "config/.env",
) -> AppConfig:
    load_dotenv(env_path)

    with open(settings_path, "rb") as f:
        raw = tomllib.load(f)

    return AppConfig(
        username=os.environ["TASTYTRADE_USERNAME"],
        password=os.environ["TASTYTRADE_PASSWORD"],
        market=MarketConfig(**raw["market"]),
        execution=ExecutionConfig(**raw["execution"]),
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/config.py
git commit -m "feat: add typed config loading"
```

---

## Task 4: Auth Module

**Files:**
- Create: `src/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_auth.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.auth import Auth, login

BASE_URL = "https://api.cert.tastyworks.com"


async def test_login_returns_auth_with_tokens():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "session-token": "tok_session",
            "remember-token": "tok_remember",
        }
    }

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.auth.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        auth = await login("user", "pass", base_url=BASE_URL)

    assert auth.session_token == "tok_session"
    assert auth.remember_token == "tok_remember"
    mock_client.post.assert_called_once_with(
        f"{BASE_URL}/sessions",
        json={"login": "user", "password": "pass"},
    )


async def test_login_raises_on_bad_credentials():
    import httpx

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock()
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.auth.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        with pytest.raises(Exception):
            await login("bad", "creds", base_url=BASE_URL)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_auth.py -v
```

Expected: `ImportError` — `src.auth` does not exist yet.

- [ ] **Step 3: Write src/auth.py**

```python
from dataclasses import dataclass
import httpx

BASE_URL = "https://api.cert.tastyworks.com"


@dataclass
class Auth:
    session_token: str
    remember_token: str


async def login(username: str, password: str, base_url: str = BASE_URL) -> Auth:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/sessions",
            json={"login": username, "password": password},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return Auth(
            session_token=data["session-token"],
            remember_token=data["remember-token"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_auth.py -v
```

Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/auth.py tests/test_auth.py
git commit -m "feat: add auth module with session token login"
```

---

## Task 5: Strategy — EMA Calculator

**Files:**
- Create: `src/strategy.py` (EMACalculator only)
- Create: `tests/test_strategy.py` (EMA tests)

- [ ] **Step 1: Write the failing EMA tests**

```python
# tests/test_strategy.py
import pytest
from src.strategy import EMACalculator


def test_ema_returns_none_before_warmup():
    ema = EMACalculator(period=3)
    assert ema.update(100.0) is None
    assert ema.update(100.0) is None


def test_ema_seeds_with_sma_at_period():
    ema = EMACalculator(period=3)
    ema.update(100.0)
    ema.update(102.0)
    result = ema.update(104.0)
    assert result == pytest.approx(102.0)  # SMA of [100, 102, 104]


def test_ema_updates_correctly_after_seed():
    ema = EMACalculator(period=3)
    ema.update(100.0)
    ema.update(100.0)
    ema.update(100.0)  # seeded at 100.0
    # k = 2 / (3+1) = 0.5
    result = ema.update(110.0)
    assert result == pytest.approx(105.0)  # 110*0.5 + 100*0.5


def test_ema_value_property_matches_last_update():
    ema = EMACalculator(period=2)
    ema.update(10.0)
    last = ema.update(20.0)
    assert ema.value == last
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_strategy.py -v
```

Expected: `ImportError` — `src.strategy` does not exist yet.

- [ ] **Step 3: Write EMACalculator in src/strategy.py**

```python
from __future__ import annotations
import asyncio

from src.models import Direction, PriceEvent, StrategyState, TradeSignal


class EMACalculator:
    def __init__(self, period: int) -> None:
        self._period = period
        self._k = 2.0 / (period + 1)
        self._buffer: list[float] = []
        self._ema: float | None = None

    def update(self, price: float) -> float | None:
        if self._ema is None:
            self._buffer.append(price)
            if len(self._buffer) >= self._period:
                self._ema = sum(self._buffer) / len(self._buffer)
                self._buffer.clear()
            return self._ema
        self._ema = price * self._k + self._ema * (1 - self._k)
        return self._ema

    @property
    def value(self) -> float | None:
        return self._ema
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_strategy.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strategy.py tests/test_strategy.py
git commit -m "feat: add EMACalculator with SMA seeding"
```

---

## Task 6: Strategy — State Machine

**Files:**
- Modify: `src/strategy.py` (add Strategy class)
- Modify: `tests/test_strategy.py` (add state machine tests)

- [ ] **Step 1: Write failing state machine tests**

Add to the bottom of `tests/test_strategy.py`:

```python
import asyncio
from src.models import Direction, PriceEvent
from src.strategy import Strategy
from src.config import MarketConfig


def _cfg(threshold: float = 0.05, cooldown: int = 300) -> MarketConfig:
    return MarketConfig(
        symbol="AAPL",
        ema_short=10,
        ema_long=20,
        threshold=threshold,
        cooldown_seconds=cooldown,
    )


def _event(price: float, bid: float = 0.0, ask: float = 0.0, ts: float = 0.0) -> PriceEvent:
    return PriceEvent(symbol="AAPL", last=price, bid=bid, ask=ask, timestamp=ts)


async def test_no_signal_before_warmup():
    q: asyncio.Queue = asyncio.Queue()
    s = Strategy(config=_cfg(), price_queue=asyncio.Queue(), signal_queue=q)
    for i in range(19):
        await s._on_price(_event(100.0, ts=float(i)))
    assert q.empty()


async def test_bullish_signal_on_crossover():
    """EMA10 crosses above EMA20 → BULLISH signal."""
    q: asyncio.Queue = asyncio.Queue()
    s = Strategy(config=_cfg(), price_queue=asyncio.Queue(), signal_queue=q)

    # Warmup: 20 flat prices → both EMAs seeded at 100.0; prev_short == prev_long
    for i in range(20):
        await s._on_price(_event(100.0, ts=float(i)))

    # One declining price → EMA10 drops faster → EMA10 < EMA20 (prev_diff negative)
    await s._on_price(_event(99.0, ts=20.0))

    # One rising price → EMA10 crosses back above EMA20
    await s._on_price(_event(105.0, ts=21.0))

    assert not q.empty()
    signal = q.get_nowait()
    assert signal.direction == Direction.BULLISH


async def test_bearish_signal_on_crossover():
    """EMA10 crosses below EMA20 → BEARISH signal."""
    q: asyncio.Queue = asyncio.Queue()
    s = Strategy(config=_cfg(), price_queue=asyncio.Queue(), signal_queue=q)

    for i in range(20):
        await s._on_price(_event(100.0, ts=float(i)))

    # One rising price → EMA10 > EMA20 (prev_diff positive)
    await s._on_price(_event(101.0, ts=20.0))

    # One declining price → EMA10 crosses below EMA20
    await s._on_price(_event(95.0, ts=21.0))

    assert not q.empty()
    signal = q.get_nowait()
    assert signal.direction == Direction.BEARISH


async def test_cooldown_prevents_double_signal():
    """A second crossover within cooldown_seconds fires no signal."""
    q: asyncio.Queue = asyncio.Queue()
    s = Strategy(config=_cfg(cooldown=300), price_queue=asyncio.Queue(), signal_queue=q)

    for i in range(20):
        await s._on_price(_event(100.0, ts=float(i)))

    # Trigger first signal (BULLISH)
    await s._on_price(_event(99.0, ts=20.0))
    await s._on_price(_event(105.0, ts=21.0))
    assert q.qsize() == 1
    q.get_nowait()

    # Immediately try to trigger a second crossover (within cooldown)
    await s._on_price(_event(99.0, ts=22.0))   # would be bearish setup
    await s._on_price(_event(105.0, ts=23.0))  # would re-trigger bullish

    assert q.empty()


async def test_signal_fires_after_cooldown_expires():
    """Signal fires normally once cooldown period has elapsed."""
    q: asyncio.Queue = asyncio.Queue()
    s = Strategy(config=_cfg(cooldown=10), price_queue=asyncio.Queue(), signal_queue=q)

    for i in range(20):
        await s._on_price(_event(100.0, ts=float(i)))

    # First signal at t=21
    await s._on_price(_event(99.0, ts=20.0))
    await s._on_price(_event(105.0, ts=21.0))
    q.get_nowait()

    # Reset state for second crossover: feed enough prices after cooldown
    await s._on_price(_event(105.0, ts=32.0))  # cooldown expired (21+10=31 < 32)
    await s._on_price(_event(99.0, ts=33.0))   # EMA10 drops below EMA20 again
    await s._on_price(_event(105.0, ts=34.0))  # crosses back up

    assert not q.empty()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_strategy.py -k "signal or warmup" -v
```

Expected: `AttributeError` or `ImportError` on Strategy class.

- [ ] **Step 3: Add Strategy class to src/strategy.py**

Append to `src/strategy.py` (below EMACalculator):

```python
class Strategy:
    def __init__(
        self,
        config: "MarketConfig",
        price_queue: asyncio.Queue,
        signal_queue: asyncio.Queue,
    ) -> None:
        from src.config import MarketConfig  # local import to avoid circular

        self._ema_short = EMACalculator(config.ema_short)
        self._ema_long = EMACalculator(config.ema_long)
        self._threshold = config.threshold
        self._cooldown_seconds = config.cooldown_seconds
        self._price_queue = price_queue
        self._signal_queue = signal_queue
        self._state = StrategyState.WATCHING
        self._prev_short: float | None = None
        self._prev_long: float | None = None
        self._cooldown_until: float = 0.0

    async def _on_price(self, event: PriceEvent) -> None:
        short = self._ema_short.update(event.last)
        long = self._ema_long.update(event.last)

        if short is None or long is None:
            return

        now = event.timestamp

        if self._state == StrategyState.COOLDOWN:
            if now >= self._cooldown_until:
                self._state = StrategyState.WATCHING
                self._prev_short = short
                self._prev_long = long
            return

        if self._prev_short is not None and self._prev_long is not None:
            prev_diff = self._prev_short - self._prev_long
            curr_diff = short - long

            if prev_diff * curr_diff < 0:
                direction = Direction.BULLISH if curr_diff > 0 else Direction.BEARISH
                signal = TradeSignal(direction=direction, price_event=event)
                await self._signal_queue.put(signal)
                self._state = StrategyState.COOLDOWN
                self._cooldown_until = now + self._cooldown_seconds
                self._prev_short = short
                self._prev_long = long
                return

            gap = abs(short - long)
            self._state = (
                StrategyState.APPROACHING if gap < self._threshold else StrategyState.WATCHING
            )

        self._prev_short = short
        self._prev_long = long

    async def run(self) -> None:
        while True:
            event = await self._price_queue.get()
            await self._on_price(event)
```

Update the imports at the top of `src/strategy.py` to add `MarketConfig`:

```python
from __future__ import annotations
import asyncio

from src.config import MarketConfig
from src.models import Direction, PriceEvent, StrategyState, TradeSignal
```

- [ ] **Step 4: Run all strategy tests**

```bash
pytest tests/test_strategy.py -v
```

Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/strategy.py tests/test_strategy.py
git commit -m "feat: add Strategy EMA crossover state machine"
```

---

## Task 7: Executor

**Files:**
- Create: `src/executor.py`
- Create: `tests/test_executor.py`

- [ ] **Step 1: Write failing executor tests**

```python
# tests/test_executor.py
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.auth import Auth
from src.config import ExecutionConfig
from src.executor import Executor
from src.models import Direction, PriceEvent, TradeSignal


def _cfg() -> ExecutionConfig:
    return ExecutionConfig(
        account_number="TEST123",
        call_symbol="AAPL  240119C00150000",
        put_symbol="AAPL  240119P00150000",
        quantity=1,
    )


def _auth() -> Auth:
    return Auth(session_token="sess-tok", remember_token="rem-tok")


def _signal(direction: Direction, bid: float = 149.90, ask: float = 150.10) -> TradeSignal:
    return TradeSignal(
        direction=direction,
        price_event=PriceEvent(
            symbol="AAPL", last=150.0, bid=bid, ask=ask, timestamp=0.0
        ),
    )


async def _make_executor() -> tuple[Executor, asyncio.Queue]:
    q: asyncio.Queue = asyncio.Queue()
    ex = Executor(config=_cfg(), auth=_auth(), signal_queue=q)
    return ex, q


async def test_bullish_places_call_order():
    ex, _ = await _make_executor()
    signal = _signal(Direction.BULLISH)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "ORD001"}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.executor.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ex._place_order(signal)

    args, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["legs"][0]["symbol"] == "AAPL  240119C00150000"
    assert body["legs"][0]["action"] == "Buy to Open"


async def test_bearish_places_put_order():
    ex, _ = await _make_executor()
    signal = _signal(Direction.BEARISH)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "ORD002"}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.executor.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ex._place_order(signal)

    args, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["legs"][0]["symbol"] == "AAPL  240119P00150000"


async def test_limit_price_is_bid_ask_midpoint():
    ex, _ = await _make_executor()
    signal = _signal(Direction.BULLISH, bid=149.90, ask=150.10)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "ORD003"}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.executor.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ex._place_order(signal)

    args, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["price"] == "150.00"


async def test_auth_header_sent():
    ex, _ = await _make_executor()
    signal = _signal(Direction.BULLISH)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "ORD004"}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.executor.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ex._place_order(signal)

    args, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["Authorization"] == "sess-tok"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_executor.py -v
```

Expected: `ImportError` — `src.executor` does not exist.

- [ ] **Step 3: Write src/executor.py**

```python
from __future__ import annotations
import asyncio
import json

import httpx

from src.auth import Auth
from src.config import ExecutionConfig
from src.models import Direction, TradeSignal

BASE_URL = "https://api.cert.tastyworks.com"


class Executor:
    def __init__(
        self,
        config: ExecutionConfig,
        auth: Auth,
        signal_queue: asyncio.Queue,
    ) -> None:
        self._config = config
        self._auth = auth
        self._signal_queue = signal_queue

    async def _place_order(self, signal: TradeSignal) -> dict:
        symbol = (
            self._config.call_symbol
            if signal.direction == Direction.BULLISH
            else self._config.put_symbol
        )
        mid = (signal.price_event.bid + signal.price_event.ask) / 2
        body = {
            "order-type": "Limit",
            "time-in-force": "Day",
            "price": f"{mid:.2f}",
            "legs": [
                {
                    "instrument-type": "Equity Option",
                    "symbol": symbol,
                    "quantity": self._config.quantity,
                    "action": "Buy to Open",
                }
            ],
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/accounts/{self._config.account_number}/orders",
                json=body,
                headers={"Authorization": self._auth.session_token},
            )
            resp.raise_for_status()
            result = resp.json()

        print(
            json.dumps(
                {
                    "event": "order_placed",
                    "direction": signal.direction.value,
                    "symbol": symbol,
                    "price": mid,
                    "order_id": result.get("data", {}).get("id"),
                }
            )
        )
        return result

    async def run(self) -> None:
        while True:
            signal = await self._signal_queue.get()
            await self._place_order(signal)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_executor.py -v
```

Expected: All 4 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: All tests PASS (auth + strategy + executor).

- [ ] **Step 6: Commit**

```bash
git add src/executor.py tests/test_executor.py
git commit -m "feat: add Executor with limit order placement"
```

---

## Task 8: Streamer

**Files:**
- Create: `src/streamer.py`

No unit tests — this module is pure I/O against the sandbox WebSocket. Tested manually in the next task.

- [ ] **Step 1: Write src/streamer.py**

```python
from __future__ import annotations
import asyncio
import json
import time

import websockets

from src.auth import Auth
from src.models import PriceEvent

STREAMER_URL = "wss://streamer.cert.tastyworks.com"

# DXLink protocol constants
_SETUP = {
    "type": "SETUP",
    "channel": 0,
    "keepaliveTimeout": 60,
    "acceptKeepaliveTimeout": 60,
    "version": "0.1-DXF-JS/0.3.0",
}
_CHANNEL_REQUEST = {
    "type": "CHANNEL_REQUEST",
    "channel": 1,
    "service": "FEED",
    "parameters": {"contract": "AUTO"},
}
_FEED_SETUP = {
    "type": "FEED_SETUP",
    "channel": 1,
    "acceptAggregationPeriod": 0.1,
    "acceptDataFormat": "FULL",
    "acceptEventFields": {
        "Quote": ["eventSymbol", "bidPrice", "askPrice"],
    },
}


class Streamer:
    def __init__(self, symbol: str, auth: Auth, price_queue: asyncio.Queue) -> None:
        self._symbol = symbol
        self._auth = auth
        self._price_queue = price_queue
        self._backoff = 5.0

    async def _connect_and_stream(self) -> None:
        async with websockets.connect(STREAMER_URL) as ws:
            self._backoff = 5.0  # reset on successful connect

            # DXLink handshake
            await ws.send(json.dumps(_SETUP))
            await self._wait_for(ws, "SETUP")

            await ws.send(
                json.dumps({"type": "AUTH", "channel": 0, "token": self._auth.session_token})
            )
            await self._wait_for(ws, "AUTH_STATE")

            await ws.send(json.dumps(_CHANNEL_REQUEST))
            await self._wait_for(ws, "CHANNEL_OPENED")

            await ws.send(json.dumps(_FEED_SETUP))
            await self._wait_for(ws, "FEED_CONFIG")

            await ws.send(
                json.dumps(
                    {
                        "type": "FEED_SUBSCRIPTION",
                        "channel": 1,
                        "add": [{"type": "Quote", "symbol": self._symbol}],
                    }
                )
            )

            async for raw in ws:
                msg = json.loads(raw)
                await self._handle(msg, ws)

    async def _wait_for(self, ws, expected_type: str) -> dict:
        """Consume messages until one matching expected_type is received."""
        async for raw in ws:
            msg = json.loads(raw)
            if msg.get("type") == "KEEPALIVE":
                await ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
            elif msg.get("type") == expected_type:
                return msg

    async def _handle(self, msg: dict, ws) -> None:
        msg_type = msg.get("type")

        if msg_type == "KEEPALIVE":
            await ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
            return

        if msg_type != "FEED_DATA" or msg.get("channel") != 1:
            return

        for entry in msg.get("data", []):
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            event_type, events = entry[0], entry[1]
            if event_type != "Quote":
                continue
            if isinstance(events, list):
                for ev in events:
                    await self._emit(ev)

    async def _emit(self, ev: dict) -> None:
        bid = ev.get("bidPrice", 0.0)
        ask = ev.get("askPrice", 0.0)
        if bid <= 0 or ask <= 0:
            return
        price_event = PriceEvent(
            symbol=ev.get("eventSymbol", self._symbol),
            last=(bid + ask) / 2,
            bid=bid,
            ask=ask,
            timestamp=time.time(),
        )
        await self._price_queue.put(price_event)

    async def run(self) -> None:
        while True:
            try:
                await self._connect_and_stream()
            except Exception as exc:
                print(f"Streamer error: {exc!r} — reconnecting in {self._backoff}s")
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, 60.0)
```

**Note on DXLink FEED_DATA format:** The exact shape of `data` entries may differ from what the sandbox returns. If quotes are not flowing, add a temporary debug print in `_handle`:

```python
if msg_type == "FEED_DATA":
    print("RAW FEED_DATA:", json.dumps(msg, indent=2))
```

This lets you see the actual wire format and adjust `_emit` if needed.

- [ ] **Step 2: Commit**

```bash
git add src/streamer.py
git commit -m "feat: add DXLink WebSocket streamer"
```

---

## Task 9: Orchestrator and End-to-End Smoke Test

**Files:**
- Create: `src/main.py`

- [ ] **Step 1: Write src/main.py**

```python
from __future__ import annotations
import asyncio
import signal

from src.auth import login
from src.config import load_config
from src.executor import Executor
from src.strategy import Strategy
from src.streamer import Streamer


async def main() -> None:
    config = load_config()

    print("Logging in to sandbox...")
    auth = await login(config.username, config.password)
    print("Authenticated.")

    price_queue: asyncio.Queue = asyncio.Queue()
    signal_queue: asyncio.Queue = asyncio.Queue()

    streamer = Streamer(
        symbol=config.market.symbol,
        auth=auth,
        price_queue=price_queue,
    )
    strategy = Strategy(
        config=config.market,
        price_queue=price_queue,
        signal_queue=signal_queue,
    )
    executor = Executor(
        config=config.execution,
        auth=auth,
        signal_queue=signal_queue,
    )

    loop = asyncio.get_running_loop()

    def _shutdown():
        print("Shutdown signal received.")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    print(
        f"Starting daemon — symbol={config.market.symbol} "
        f"EMA{config.market.ema_short}/{config.market.ema_long}"
    )

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(streamer.run())
            tg.create_task(strategy.run())
            tg.create_task(executor.run())
    except* asyncio.CancelledError:
        print("Daemon stopped.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Fill in your sandbox credentials**

Edit `config/.env`:
```
TASTYTRADE_USERNAME=<your sandbox username>
TASTYTRADE_PASSWORD=<your sandbox password>
```

Edit `config/settings.toml`:
```toml
[execution]
account_number = "<your sandbox account number>"
```

Find your sandbox account number in TastyTrade's web portal under account settings.

- [ ] **Step 3: Run the daemon**

```bash
python -m src.main
```

Expected output:
```
Logging in to sandbox...
Authenticated.
Starting daemon — symbol=AAPL EMA10/20
```

If the WebSocket connects successfully, you will see no further output until a quote arrives. If you see a connection error, double-check credentials and that `api.cert.tastyworks.com` is reachable.

- [ ] **Step 4: Verify quotes are flowing**

Add a temporary print to `src/streamer.py` inside `_emit` before putting to the queue:

```python
print(f"Quote: {price_event}")
```

Restart the daemon. You should see `Quote: PriceEvent(...)` lines appearing as quotes arrive from the sandbox feed. Remove the print once confirmed.

- [ ] **Step 5: Verify signal detection**

Lower the threshold temporarily to trigger an `APPROACHING` or `CROSSED` signal sooner during testing. In `config/settings.toml`:

```toml
threshold = 10.0   # large value to force APPROACHING immediately
cooldown_seconds = 10
```

Add a temporary print inside `Strategy._on_price` after computing `short` and `long`:

```python
if short is not None and long is not None:
    print(f"EMA{self._ema_short._period}={short:.4f} EMA{self._ema_long._period}={long:.4f} gap={abs(short-long):.4f} state={self._state}")
```

This lets you watch the EMAs converge and verify the state transitions. Remove before production use.

- [ ] **Step 6: Verify order placement appears in TastyTrade portal**

When a `CROSSED` signal fires, you should see:
```json
{"event": "order_placed", "direction": "BULLISH", "symbol": "AAPL  240119C00150000", ...}
```

Log into the TastyTrade sandbox web portal and navigate to your paper trading account's order history. The order should appear there.

If the order is rejected, check:
- Account number is correct
- OCC symbol format is valid (21 chars, padded with spaces)
- The option expiration has not passed

- [ ] **Step 7: Restore config to normal values**

```toml
threshold = 0.05
cooldown_seconds = 300
```

Remove any debug prints added during testing.

- [ ] **Step 8: Run full test suite one final time**

```bash
pytest -v
```

Expected: All tests PASS.

- [ ] **Step 9: Final commit**

```bash
git add src/main.py
git commit -m "feat: add orchestrator and complete daemon"
```
