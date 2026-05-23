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
    await s._on_price(_event(99.0, ts=22.0))
    await s._on_price(_event(105.0, ts=23.0))

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

    # Feed prices after cooldown expires (21 + 10 = 31, use ts=32)
    await s._on_price(_event(105.0, ts=32.0))  # cooldown expired
    await s._on_price(_event(80.0, ts=33.0))   # EMA10 drops below EMA20
    await s._on_price(_event(105.0, ts=34.0))  # crosses back up

    assert not q.empty()
