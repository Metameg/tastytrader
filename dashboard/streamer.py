"""DashboardStreamer — multi-symbol DXLink WebSocket client (Issue #4)."""
from __future__ import annotations
from typing import Callable, Awaitable


class DashboardStreamer:
    def __init__(
        self,
        session_token: str,
        on_quote: Callable,
        on_candle: Callable | None = None,
    ) -> None:
        raise NotImplementedError

    async def subscribe(self, symbols: list[str]) -> None:
        raise NotImplementedError

    async def run(self) -> None:
        raise NotImplementedError
