from __future__ import annotations
import asyncio
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

_now = time.time
_CANDLE_BROADCAST_INTERVAL: float = 1.0

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
        self.candles: dict[str, list[dict]] = {}
        self._candle_last_broadcast: dict[str, float] = {}
        self._candle_last_time: dict[str, int | None] = {}

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
            ema_short = EMACalculator(10)
            ema_long = EMACalculator(20)
            ema_short.seed(price_event.last)
            ema_long.seed(price_event.last)
            self._ema_short[s] = ema_short
            self._ema_long[s] = ema_long
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
        # Persist live mark into state.positions (blip root-cause fix — AC8).
        self.update_quote(s, price_event.last)
        payload = {"event": "quote", "data": self.quotes[s]}
        n = len(self.subscribers)
        print(f"[SSE] quote for {s} → broadcasting to {n} subscriber(s)")
        for q in self.subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                print(f"[SSE] queue full — dropping quote for {s}")

    _MAX_CANDLES: int = 90

    def on_candle(self, ohlc: dict) -> None:
        # Normalize eventSymbol: strip {=d} suffix to get plain symbol
        raw_sym: str = ohlc.get("eventSymbol", "")
        plain_sym = raw_sym.split("{")[0] if "{" in raw_sym else raw_sym
        if plain_sym:
            bucket = self.candles.setdefault(plain_sym, [])
            bucket.append(ohlc)
            # Cap history to the most recent _MAX_CANDLES entries to bound memory usage
            if len(bucket) > self._MAX_CANDLES:
                del bucket[: len(bucket) - self._MAX_CANDLES]
        # Throttled broadcast: at most once per _CANDLE_BROADCAST_INTERVAL per symbol;
        # bypass throttle when candle time changes (new day / first candle).
        candle_time = ohlc.get("time")
        now = _now()
        last_broadcast = self._candle_last_broadcast.get(plain_sym, 0.0)
        last_time = self._candle_last_time.get(plain_sym)
        is_new_day = candle_time is not None and candle_time != last_time
        elapsed = now - last_broadcast
        should_broadcast = is_new_day or elapsed >= _CANDLE_BROADCAST_INTERVAL
        if should_broadcast:
            self._candle_last_broadcast[plain_sym] = now
            self._candle_last_time[plain_sym] = candle_time
            payload = {"event": "candle", "data": ohlc}
            for q in self.subscribers:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    pass

    def get_chart_data(self, symbol: str) -> dict:
        """Return chart data for Chart.js: sorted OHLC prices + EMA-10/20 arrays.

        Returns empty arrays for all keys if symbol is unknown or has no candle history.
        """
        candles = self.candles.get(symbol)
        if not candles:
            return {"labels": [], "open": [], "high": [], "low": [], "close": [], "ema_short": [], "ema_long": []}

        sorted_candles = sorted(candles, key=lambda c: c.get("time", 0))
        # Filter out candles missing or having None close — partial events from DXLink
        # (e.g. incomplete OHLC at market close) would otherwise crash with KeyError/TypeError.
        # Also skip candles whose close can't be parsed to a finite float (e.g. "NaN",
        # "Infinity", or non-numeric strings) to avoid ValueError / inf/nan propagation.
        valid_candles = []
        for c in sorted_candles:
            raw_close = c.get("close")
            if raw_close is None:
                continue
            try:
                close_val = float(raw_close)
            except (ValueError, TypeError):
                continue
            if not math.isfinite(close_val):
                continue
            valid_candles.append((c, close_val))
        if not valid_candles:
            return {"labels": [], "open": [], "high": [], "low": [], "close": [], "ema_short": [], "ema_long": []}

        def _coerce_ohlc_field(raw: object, fallback: float) -> float:
            """Coerce an OHLC field to float; fall back to close if missing or non-finite."""
            if raw is None:
                return fallback
            try:
                val = float(raw)
            except (ValueError, TypeError):
                return fallback
            return val if math.isfinite(val) else fallback

        closes = [cv for _, cv in valid_candles]
        valid_candle_dicts = [c for c, _ in valid_candles]
        labels = [c.get("time", i) for i, c in enumerate(valid_candle_dicts)]
        opens = [_coerce_ohlc_field(c.get("open"), cv) for c, cv in valid_candles]
        highs = [_coerce_ohlc_field(c.get("high"), cv) for c, cv in valid_candles]
        lows = [_coerce_ohlc_field(c.get("low"), cv) for c, cv in valid_candles]

        ema_s = EMACalculator(10)
        ema_l = EMACalculator(20)
        ema_short_vals = [ema_s.update(p) for p in closes]
        ema_long_vals = [ema_l.update(p) for p in closes]

        return {
            "labels": labels,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "ema_short": ema_short_vals,
            "ema_long": ema_long_vals,
        }

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
