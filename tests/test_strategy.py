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
