from __future__ import annotations
import asyncio
import re
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

    def get_positions_grouped(self) -> list[dict]:
        equity_symbols: set[str] = {
            pos["symbol"]
            for pos in self.positions
            if pos.get("instrument_type") != "Equity Option"
        }

        options_by_parent: dict[str, list[dict]] = {}
        orphan_options: list[dict] = []

        for pos in self.positions:
            if pos.get("instrument_type") == "Equity Option":
                parent = re.match(r"([A-Z]+)", pos["symbol"].strip())
                parent_sym = parent.group(1) if parent else None
                if parent_sym and parent_sym in equity_symbols:
                    options_by_parent.setdefault(parent_sym, []).append(pos)
                else:
                    orphan_options.append(pos)

        result: list[dict] = []
        for pos in self.positions:
            if pos.get("instrument_type") == "Equity Option":
                continue
            row = dict(pos)
            row["legs"] = options_by_parent.get(pos["symbol"], [])
            result.append(row)

        result.extend(orphan_options)
        return result

    def update_quote(self, symbol: str, price: float) -> None:
        for pos in self.positions:
            if pos["symbol"] == symbol:
                pos["current_price"] = price
                try:
                    avg_cost = float(pos["avg_cost"])
                except (ValueError, TypeError):
                    continue
                multiplier = 100 if pos.get("instrument_type") == "Equity Option" else 1
                pos["pl"] = (price - avg_cost) * pos["quantity"] * multiplier


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
    if not underlying:
        return None
    date_str = m.group(2)
    opt_char = m.group(3)
    strike_raw = m.group(4)

    try:
        expiry_dt = datetime.strptime(date_str, "%y%m%d")
    except ValueError:
        return None

    return {
        "underlying": underlying,
        "expiry": expiry_dt.strftime("%b %-d %Y"),
        "option_type": "Call" if opt_char == "C" else "Put",
        "strike": int(strike_raw) / 1000,
    }
