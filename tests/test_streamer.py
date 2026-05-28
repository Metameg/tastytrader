"""Failing tests for DashboardStreamer (issue #4) — RED until implemented."""
import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from dashboard.streamer import DashboardStreamer


# Minimal DXLink handshake responses required to progress past each _wait_for.
_HANDSHAKE = [
    json.dumps({"type": "SETUP", "channel": 0}),
    json.dumps({"type": "AUTH_STATE", "channel": 0, "state": "AUTHORIZED"}),
    json.dumps({"type": "CHANNEL_OPENED", "channel": 1}),
    json.dumps({"type": "FEED_CONFIG", "channel": 1}),
]


class _MockWS:
    """Async-iterable WebSocket stub that yields pre-configured messages and records sends."""

    def __init__(self, responses: list[str]) -> None:
        self._iter = iter(responses)
        self.sent: list[dict] = []

    async def send(self, data: str) -> None:
        self.sent.append(json.loads(data))

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _ws_factory(*extra_messages: str):
    """Return a callable that produces a fresh _MockWS on each WebSocket connect call."""
    calls: list[_MockWS] = []

    def factory(url):
        ws = _MockWS(_HANDSHAKE + list(extra_messages))
        calls.append(ws)
        return ws

    factory.calls = calls  # type: ignore[attr-defined]
    return factory


async def _run(streamer: DashboardStreamer, factory, timeout: float = 0.5) -> None:
    with patch("dashboard.streamer.websockets.connect", side_effect=factory):
        try:
            await asyncio.wait_for(streamer.run(), timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            pass


# --- DashboardStreamer ---

async def test_subscribe_sends_feed_subscription_message():
    streamer = DashboardStreamer(session_token="tok", on_quote=AsyncMock())
    await streamer.subscribe(["AAPL"])

    factory = _ws_factory()
    await _run(streamer, factory)

    ws = factory.calls[0]
    sub_msgs = [m for m in ws.sent if m.get("type") == "FEED_SUBSCRIPTION"]
    assert sub_msgs, "No FEED_SUBSCRIPTION message was sent"
    symbols_sent = [item["symbol"] for m in sub_msgs for item in m.get("add", [])]
    assert "AAPL" in symbols_sent


async def test_quote_event_triggers_price_callback_with_correct_fields():
    on_quote = AsyncMock()
    streamer = DashboardStreamer(session_token="tok", on_quote=on_quote)
    await streamer.subscribe(["AAPL"])

    quote_msg = json.dumps({
        "type": "FEED_DATA",
        "channel": 1,
        "data": [["Quote", [{"eventSymbol": "AAPL", "bidPrice": 149.9, "askPrice": 150.1}]]],
    })
    factory = _ws_factory(quote_msg)
    await _run(streamer, factory)

    on_quote.assert_called_once()
    symbol, payload = on_quote.call_args.args
    assert symbol == "AAPL"
    assert payload["bid"] == 149.9
    assert payload["ask"] == 150.1
    assert "last" in payload


async def test_candle_event_triggers_candle_callback():
    on_candle = AsyncMock()
    streamer = DashboardStreamer(
        session_token="tok", on_quote=AsyncMock(), on_candle=on_candle
    )
    await streamer.subscribe(["AAPL"])

    candle_msg = json.dumps({
        "type": "FEED_DATA",
        "channel": 1,
        "data": [["Candle", [{"eventSymbol": "AAPL{=5m}", "open": 149.0, "close": 150.0, "high": 151.0, "low": 148.0}]]],
    })
    factory = _ws_factory(candle_msg)
    await _run(streamer, factory)

    on_candle.assert_called_once()
    symbol, payload = on_candle.call_args.args
    assert symbol == "AAPL{=5m}"
    assert payload["close"] == 150.0


async def test_reconnect_replays_all_subscriptions():
    streamer = DashboardStreamer(session_token="tok", on_quote=AsyncMock())
    await streamer.subscribe(["AAPL", "SPY"])

    factory = _ws_factory()  # each call yields a fresh _MockWS with just the handshake
    with patch("dashboard.streamer.asyncio.sleep", new=AsyncMock()):
        await _run(streamer, factory)

    assert len(factory.calls) >= 2, "Streamer did not attempt a reconnect"
    second_ws = factory.calls[1]
    sub_msgs = [m for m in second_ws.sent if m.get("type") == "FEED_SUBSCRIPTION"]
    symbols_resent = {item["symbol"] for m in sub_msgs for item in m.get("add", [])}
    assert {"AAPL", "SPY"} <= symbols_resent, (
        f"Reconnect did not replay all subscriptions; got {symbols_resent}"
    )
