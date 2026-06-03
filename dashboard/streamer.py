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
        "Quote": ["eventSymbol", "bidPrice", "askPrice"],
        "Candle": ["eventSymbol", "open", "high", "low", "close", "volume"],
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

    async def _send_subscription(self, add_list: list) -> None:
        if self._ws is not None:
            await self._ws.send(json.dumps({
                "type": "FEED_SUBSCRIPTION", "channel": 1, "add": add_list
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
            await ws.send(json.dumps({
                "type": "FEED_SUBSCRIPTION", "channel": 1, "add": add_list
            }))

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
        for entry in msg.get("data", []):
            if not isinstance(entry, list) or len(entry) < 2:
                continue
            event_type, events = entry[0], entry[1]
            if isinstance(events, list):
                for ev in events:
                    if event_type == "Quote":
                        self._dispatch_quote(ev)
                    elif event_type == "Candle":
                        self._dispatch_candle(ev)

    def _dispatch_quote(self, ev: dict) -> None:
        bid = ev.get("bidPrice", 0.0)
        ask = ev.get("askPrice", 0.0)
        if bid <= 0 or ask <= 0:
            return
        price_event = PriceEvent(
            symbol=ev.get("eventSymbol", ""),
            last=(bid + ask) / 2,
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
