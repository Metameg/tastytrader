from __future__ import annotations
import asyncio

from src.config import MarketConfig
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


class Strategy:
    def __init__(
        self,
        config: MarketConfig,
        price_queue: asyncio.Queue,
        signal_queue: asyncio.Queue,
    ) -> None:
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
