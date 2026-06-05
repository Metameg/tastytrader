"""DashboardStreamer — multi-symbol DXLink WebSocket client (Issue #4)."""
from __future__ import annotations
import asyncio
import json
import time
from typing import Callable

import websockets

from src.models import PriceEvent

_SETUP = {
    "type": "SETUP", "channel": 0,
    "keepaliveTimeout": 60, "acceptKeepaliveTimeout": 60,
    "version": "0.1-DXF-JS/0.3.0",
}
_CHANNEL_REQUEST = {
    "type": "CHANNEL_REQUEST", "channel": 1,
    "service": "FEED", "parameters": {"contract": "AUTO"},
}
_FEED_SETUP = {
    "type": "FEED_SETUP", "channel": 1,
    "acceptAggregationPeriod": 0.1, "acceptDataFormat": "FULL",
    "acceptEventFields": {
        # eventType is requested so each event object in the FULL-format
        # FEED_DATA payload self-identifies as Quote vs Candle.
        "Quote": ["eventType", "eventSymbol", "bidPrice", "askPrice"],
        "Candle": ["eventType", "eventSymbol", "time", "open", "high", "low", "close", "volume"],
    },
}


class DashboardStreamer:
    def __init__(
        self,
        quote_token: str,
        streamer_url: str,
        price_callback: Callable[[PriceEvent], None],
        candle_callback: Callable[[dict], None],
    ) -> None:
        self._quote_token = quote_token
        self._streamer_url = streamer_url
        self._price_callback = price_callback
        self._candle_callback = candle_callback
        self._quote_symbols: set[str] = set()
        self._candle_symbols: dict[str, float] = {}
        self._ws = None
        self._backoff = 5.0

    def add_quote(self, symbol: str) -> None:
        self._quote_symbols.add(symbol)
        if self._ws is not None:
            asyncio.create_task(self._send_subscription([{"type": "Quote", "symbol": symbol}]))

    def add_candle(self, symbol: str, from_time: float) -> None:
        self._candle_symbols[symbol] = from_time
        if self._ws is not None:
            asyncio.create_task(self._send_subscription([
                {"type": "Candle", "symbol": f"{symbol}{{=d}}", "fromTime": int(from_time)}
            ]))

    def remove_candle(self, symbol: str) -> None:
        """Unsubscribe from daily candles for the given symbol.

        No-op if symbol is not subscribed. Drops the symbol from the internal map
        so it is not re-subscribed on reconnect. Sends a FEED_SUBSCRIPTION remove
        message only when the WebSocket is connected.
        """
        if symbol not in self._candle_symbols:
            return
        del self._candle_symbols[symbol]
        if self._ws is not None:
            asyncio.create_task(self._send_subscription_remove([
                {"type": "Candle", "symbol": f"{symbol}{{=d}}"}
            ]))

    async def _send_subscription(self, add_list: list) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps({
                "type": "FEED_SUBSCRIPTION", "channel": 1, "add": add_list
            }))

    async def _send_subscription_remove(self, remove_list: list) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps({
                "type": "FEED_SUBSCRIPTION", "channel": 1, "remove": remove_list
            }))

    async def _connect_and_stream(self) -> None:
        async with websockets.connect(self._streamer_url) as ws:
            self._backoff = 5.0
            await self._handshake(ws)
            self._ws = ws          # assign AFTER handshake so add_quote fires only on live channel
            await self._subscribe_all(ws)
            async for raw in ws:
                msg = json.loads(raw)
                await self._handle(msg, ws)
        self._ws = None

    async def _handshake(self, ws) -> None:
        await ws.send(json.dumps(_SETUP))
        await self._wait_for(ws, "SETUP")
        await ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": self._quote_token}))
        await self._wait_for(ws, "AUTH_STATE")
        await ws.send(json.dumps(_CHANNEL_REQUEST))
        await self._wait_for(ws, "CHANNEL_OPENED")
        await ws.send(json.dumps(_FEED_SETUP))
        await self._wait_for(ws, "FEED_CONFIG")

    async def _subscribe_all(self, ws) -> None:
        add_list = []
        for sym in self._quote_symbols:
            add_list.append({"type": "Quote", "symbol": sym})
        for sym, from_time in self._candle_symbols.items():
            add_list.append({"type": "Candle", "symbol": f"{sym}{{=d}}", "fromTime": int(from_time)})
        if add_list:
            print(f"[DXLink] subscribing to {len(add_list)} feed(s): {[e['symbol'] for e in add_list]}")
            await ws.send(json.dumps({
                "type": "FEED_SUBSCRIPTION", "channel": 1, "add": add_list
            }))
        else:
            print("[DXLink] _subscribe_all called but no symbols to subscribe yet")

    async def _wait_for(self, ws, expected_type: str, timeout: float = 10.0) -> dict:
        async with asyncio.timeout(timeout):
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get("type") == "KEEPALIVE":
                    await ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
                elif msg.get("type") == expected_type:
                    return msg
        raise ConnectionError(f"Closed before {expected_type}")

    async def _handle(self, msg: dict, ws) -> None:
        msg_type = msg.get("type")
        if msg_type == "KEEPALIVE":
            await ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))
            return
        if msg_type != "FEED_DATA" or msg.get("channel") != 1:
            return
        print(f"[DXLink] FEED_DATA received: {msg}")
        # FULL data format: `data` is a flat list of event objects (dicts).
        for ev in msg.get("data", []):
            if not isinstance(ev, dict):
                continue
            event_type = self._classify(ev)
            if event_type == "Quote":
                self._dispatch_quote(ev)
            elif event_type == "Candle":
                self._dispatch_candle(ev)

    @staticmethod
    def _classify(ev: dict) -> str | None:
        """Identify the event type of a FULL-format event object.

        Prefers the explicit ``eventType`` field (requested in FEED_SETUP);
        falls back to field presence so a missing eventType never silently
        drops an event the way the old nested-format parser did.
        """
        et = ev.get("eventType")
        if et in ("Quote", "Candle"):
            return et
        if "bidPrice" in ev or "askPrice" in ev:
            return "Quote"
        if "close" in ev or "open" in ev:
            return "Candle"
        return None

    def _dispatch_quote(self, ev: dict) -> None:
        bid = ev.get("bidPrice", 0.0)
        ask = ev.get("askPrice", 0.0)
        sym = ev.get("eventSymbol", "")
        if bid <= 0 or ask <= 0:
            print(f"[DXLink] quote dropped (zero bid/ask) — {sym} bid={bid} ask={ask}")
            return
        last = (bid + ask) / 2
        print(f"[DXLink] quote dispatched — {sym} bid={bid} ask={ask} last={last:.4f}")
        price_event = PriceEvent(
            symbol=sym,
            last=last,
            bid=bid,
            ask=ask,
            timestamp=time.time(),
        )
        self._price_callback(price_event)

    def _dispatch_candle(self, ev: dict) -> None:
        self._candle_callback(ev)

    async def run(self) -> None:
        while True:
            try:
                await self._connect_and_stream()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                print(f"DashboardStreamer error: {exc!r} — reconnecting in {self._backoff}s")
                await asyncio.sleep(self._backoff)
                self._backoff = min(self._backoff * 2, 60.0)
