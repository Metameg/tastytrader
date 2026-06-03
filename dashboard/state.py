from __future__ import annotations
import asyncio
from dataclasses import dataclass, field

from src.models import PriceEvent
from src.strategy import EMACalculator


@dataclass
class DashboardState:
    account_number: str = "—"
    net_liquidating_value: str = "—"
    buying_power: str = "—"
    positions: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    subscribers: list = field(default_factory=list)
    quotes: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._ema_short: dict = {}
        self._ema_long: dict = {}

    def get_account_summary(self) -> dict:
        return {
            "account_number": self.account_number,
            "net_liquidating_value": self.net_liquidating_value,
            "buying_power": self.buying_power,
        }

    async def add_subscriber(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers.append(q)
        return q

    async def remove_subscriber(self, q: asyncio.Queue) -> None:
        if q in self.subscribers:
            self.subscribers.remove(q)

    async def broadcast(self, event_name: str, data: dict) -> None:
        payload = {"event": event_name, "data": data}
        for q in self.subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def on_quote(self, price_event: PriceEvent) -> None:
        s = price_event.symbol
        if s not in self._ema_short:
            self._ema_short[s] = EMACalculator(10)
            self._ema_long[s] = EMACalculator(20)
        ema_s = self._ema_short[s].update(price_event.last)
        ema_l = self._ema_long[s].update(price_event.last)
        self.quotes[s] = {
            "symbol": s,
            "last": price_event.last,
            "bid": price_event.bid,
            "ask": price_event.ask,
            "ema_short": ema_s,
            "ema_long": ema_l,
        }
        payload = {"event": "quote", "data": self.quotes[s]}
        for q in self.subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    def on_candle(self, ohlc: dict) -> None:
        payload = {"event": "candle", "data": ohlc}
        for q in self.subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
