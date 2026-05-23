from __future__ import annotations
import asyncio
import json

import httpx

from src.auth import Auth
from src.config import ExecutionConfig
from src.models import Direction, TradeSignal

BASE_URL = "https://api.cert.tastyworks.com"


class Executor:
    def __init__(
        self,
        config: ExecutionConfig,
        auth: Auth,
        signal_queue: asyncio.Queue,
    ) -> None:
        self._config = config
        self._auth = auth
        self._signal_queue = signal_queue

    async def _place_order(self, signal: TradeSignal) -> dict:
        symbol = (
            self._config.call_symbol
            if signal.direction == Direction.BULLISH
            else self._config.put_symbol
        )
        mid = (signal.price_event.bid + signal.price_event.ask) / 2
        body = {
            "order-type": "Limit",
            "time-in-force": "Day",
            "price": f"{mid:.2f}",
            "legs": [
                {
                    "instrument-type": "Equity Option",
                    "symbol": symbol,
                    "quantity": self._config.quantity,
                    "action": "Buy to Open",
                }
            ],
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{BASE_URL}/accounts/{self._config.account_number}/orders",
                json=body,
                headers={"Authorization": self._auth.session_token},
            )
            resp.raise_for_status()
            result = resp.json()

        print(
            json.dumps(
                {
                    "event": "order_placed",
                    "direction": signal.direction.value,
                    "symbol": symbol,
                    "price": mid,
                    "order_id": result.get("data", {}).get("id"),
                }
            )
        )
        return result

    async def run(self) -> None:
        while True:
            signal = await self._signal_queue.get()
            await self._place_order(signal)
