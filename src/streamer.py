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
