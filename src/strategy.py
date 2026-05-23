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
