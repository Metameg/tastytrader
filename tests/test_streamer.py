"""London-school tests for DashboardStreamer (Issue #4).

These tests fail at collection or immediately at import because
dashboard/streamer.py is a stub.  That is intentional — the tests
describe the required behaviour so the implementation agent can make
them green.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import ANY, AsyncMock, MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Import under test — may raise ImportError/AttributeError because the module
# is a stub.  We catch that here so pytest reports an ImportError *failure*
# on each test rather than a collection-level error that skips the whole file.
# ---------------------------------------------------------------------------
try:
    from dashboard.streamer import DashboardStreamer
    _IMPORT_ERROR: Exception | None = None
except (ImportError, AttributeError) as exc:
    DashboardStreamer = None  # type: ignore[assignment,misc]
    _IMPORT_ERROR = exc

from src.models import PriceEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_ws():
    """Return a MagicMock that behaves like a websockets.WebSocketClientProtocol.

    - ``send`` is an AsyncMock
    - ``recv`` is an AsyncMock
    - The object supports ``async for raw in ws`` via __aiter__/__anext__
    """
    ws = MagicMock()
    ws.send = AsyncMock()
    ws.recv = AsyncMock()
    ws.__aiter__ = MagicMock(return_value=ws)
    ws.__anext__ = AsyncMock()
    return ws


def _handshake_responses(ws, extra_messages: list[str]) -> None:
    """Configure ws.__anext__ to deliver the DXLink handshake responses
    followed by *extra_messages*, then raise StopAsyncIteration.

    Handshake order expected by DashboardStreamer:
      SETUP → AUTH_STATE → CHANNEL_OPENED → FEED_CONFIG
    """
    responses = [
        json.dumps({"type": "SETUP"}),
        json.dumps({"type": "AUTH_STATE", "state": "AUTHORIZED"}),
        json.dumps({"type": "CHANNEL_OPENED", "channel": 1}),
        json.dumps({"type": "FEED_CONFIG", "channel": 1}),
    ] + extra_messages

    sentinel = StopAsyncIteration()
    side_effects = [json_str for json_str in responses] + [sentinel]
    ws.__anext__.side_effect = side_effects


def _make_connected_context(ws):
    """Return an async context manager mock that yields *ws*."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=ws)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


def _require_import(fn):
    """Decorator: skip test body and raise ImportError if import failed."""
    import functools

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        if _IMPORT_ERROR is not None:
            raise _IMPORT_ERROR
        return await fn(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# Test 1 — add_quote sends FEED_SUBSCRIPTION for Quote type
# ---------------------------------------------------------------------------

@_require_import
async def test_add_quote_sends_feed_subscription_message():
    """add_quote('AAPL') must send a FEED_SUBSCRIPTION message with
    {"type": "Quote", "symbol": "AAPL"} after the DXLink handshake."""
    ws = _make_mock_ws()
    _handshake_responses(ws, [])  # no data frames — just handshake then stop

    price_cb = AsyncMock()
    candle_cb = AsyncMock()

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=price_cb,
        candle_callback=candle_cb,
    )
    streamer.add_quote("AAPL")  # add before connect so it's queued

    cm = _make_connected_context(ws)
    with patch("dashboard.streamer.websockets.connect", return_value=cm):
        # run until StopAsyncIteration terminates the loop
        try:
            await streamer._connect_and_stream()
        except (StopAsyncIteration, Exception):
            pass

    # Gather all JSON strings sent to the WebSocket
    sent_payloads = [json.loads(c.args[0]) for c in ws.send.call_args_list]

    feed_sub_msgs = [
        p for p in sent_payloads if p.get("type") == "FEED_SUBSCRIPTION"
    ]
    assert feed_sub_msgs, "Expected at least one FEED_SUBSCRIPTION message"

    added = [item for msg in feed_sub_msgs for item in msg.get("add", [])]
    assert {"type": "Quote", "symbol": "AAPL"} in added, (
        f"Expected Quote/AAPL in FEED_SUBSCRIPTION add list; got: {added}"
    )


# ---------------------------------------------------------------------------
# Test 2 — add_candle sends subscription with Candle{=d} symbol
# ---------------------------------------------------------------------------

@_require_import
async def test_add_candle_sends_candle_subscription():
    """add_candle('AAPL', from_time=1234567890) must send a FEED_SUBSCRIPTION
    with event type 'Candle' and symbol 'AAPL{=d}' (daily period notation)."""
    ws = _make_mock_ws()
    _handshake_responses(ws, [])

    price_cb = AsyncMock()
    candle_cb = AsyncMock()

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=price_cb,
        candle_callback=candle_cb,
    )
    streamer.add_candle("AAPL", from_time=1_234_567_890)

    cm = _make_connected_context(ws)
    with patch("dashboard.streamer.websockets.connect", return_value=cm):
        try:
            await streamer._connect_and_stream()
        except (StopAsyncIteration, Exception):
            pass

    sent_payloads = [json.loads(c.args[0]) for c in ws.send.call_args_list]

    feed_sub_msgs = [
        p for p in sent_payloads if p.get("type") == "FEED_SUBSCRIPTION"
    ]
    assert feed_sub_msgs, "Expected at least one FEED_SUBSCRIPTION message"

    added = [item for msg in feed_sub_msgs for item in msg.get("add", [])]
    candle_entries = [item for item in added if item.get("type") == "Candle"]
    assert candle_entries, f"Expected Candle entry in FEED_SUBSCRIPTION; got: {added}"

    candle_symbols = [item.get("symbol", "") for item in candle_entries]
    assert any("AAPL{=d}" in sym for sym in candle_symbols), (
        f"Expected symbol containing 'AAPL{{=d}}'; got: {candle_symbols}"
    )


# ---------------------------------------------------------------------------
# Test 3 — FEED_DATA Quote event triggers price_callback with PriceEvent
# ---------------------------------------------------------------------------

@_require_import
async def test_quote_feed_data_triggers_price_callback():
    """When a FEED_DATA message with a Quote event arrives, price_callback
    must be called with a PriceEvent where bid=100.0, ask=102.0,
    last=101.0 (midpoint), symbol='AAPL'."""
    # Real DXLink FULL data format: `data` is a flat list of event objects,
    # each tagged with its eventType (matches what the live server sends).
    feed_data_msg = json.dumps(
        {
            "type": "FEED_DATA",
            "channel": 1,
            "data": [
                {
                    "eventType": "Quote",
                    "eventSymbol": "AAPL",
                    "bidPrice": 100.0,
                    "askPrice": 102.0,
                }
            ],
        }
    )

    ws = _make_mock_ws()
    _handshake_responses(ws, [feed_data_msg])

    price_cb = MagicMock()
    candle_cb = MagicMock()

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=price_cb,
        candle_callback=candle_cb,
    )

    cm = _make_connected_context(ws)
    with patch("dashboard.streamer.websockets.connect", return_value=cm):
        try:
            await streamer._connect_and_stream()
        except (StopAsyncIteration, Exception):
            pass

    price_cb.assert_called_once()
    event: PriceEvent = price_cb.call_args.args[0]
    assert event.symbol == "AAPL"
    assert event.bid == 100.0
    assert event.ask == 102.0
    assert event.last == 101.0


# ---------------------------------------------------------------------------
# Test 4 — FEED_DATA Candle event triggers candle_callback with OHLC dict
# ---------------------------------------------------------------------------

@_require_import
async def test_candle_feed_data_triggers_candle_callback():
    """When a FEED_DATA message with a Candle event arrives, candle_callback
    must be called with a dict containing OHLC fields."""
    # Real DXLink FULL data format: flat list of event objects tagged by eventType.
    feed_data_msg = json.dumps(
        {
            "type": "FEED_DATA",
            "channel": 1,
            "data": [
                {
                    "eventType": "Candle",
                    "eventSymbol": "AAPL{=d}",
                    "open": 150.0,
                    "high": 155.0,
                    "low": 148.0,
                    "close": 153.0,
                    "volume": 1_000_000,
                }
            ],
        }
    )

    ws = _make_mock_ws()
    _handshake_responses(ws, [feed_data_msg])

    price_cb = MagicMock()
    candle_cb = MagicMock()

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=price_cb,
        candle_callback=candle_cb,
    )

    cm = _make_connected_context(ws)
    with patch("dashboard.streamer.websockets.connect", return_value=cm):
        try:
            await streamer._connect_and_stream()
        except (StopAsyncIteration, Exception):
            pass

    candle_cb.assert_called_once()
    candle_dict: dict = candle_cb.call_args.args[0]
    assert candle_dict.get("open") == 150.0
    assert candle_dict.get("high") == 155.0
    assert candle_dict.get("low") == 148.0
    assert candle_dict.get("close") == 153.0


# ---------------------------------------------------------------------------
# Test 5 — Reconnect resubscribes all previously-added symbols
# ---------------------------------------------------------------------------

@_require_import
async def test_reconnect_resubscribes_symbols():
    """After a WebSocket disconnect, the second connection must re-send the
    FEED_SUBSCRIPTION for symbols that were added before the disconnect."""
    # First connection raises an exception to simulate disconnect
    first_ws = _make_mock_ws()
    first_ws.__aenter__ = AsyncMock(side_effect=ConnectionError("disconnected"))
    first_ws.__aexit__ = AsyncMock(return_value=False)

    # Second connection succeeds and delivers normal handshake
    second_ws = _make_mock_ws()
    _handshake_responses(second_ws, [])

    first_cm = MagicMock()
    first_cm.__aenter__ = AsyncMock(side_effect=ConnectionError("disconnected"))
    first_cm.__aexit__ = AsyncMock(return_value=False)

    second_cm = _make_connected_context(second_ws)

    price_cb = MagicMock()
    candle_cb = MagicMock()

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=price_cb,
        candle_callback=candle_cb,
    )
    streamer.add_quote("AAPL")

    connect_results = iter([first_cm, second_cm])

    with patch(
        "dashboard.streamer.websockets.connect",
        side_effect=lambda *a, **kw: next(connect_results),
    ):
        with patch("dashboard.streamer.asyncio.sleep", new_callable=AsyncMock):
            # run two iterations of the reconnect loop
            # We stop after the second connection's StopAsyncIteration
            iteration_count = 0

            original_connect_and_stream = streamer._connect_and_stream

            async def limited_run():
                nonlocal iteration_count
                for _ in range(2):
                    try:
                        await streamer._connect_and_stream()
                    except (StopAsyncIteration, ConnectionError):
                        pass
                    iteration_count += 1

            await limited_run()

    # Verify the second connection sent FEED_SUBSCRIPTION for AAPL
    sent_payloads = [json.loads(c.args[0]) for c in second_ws.send.call_args_list]
    feed_sub_msgs = [
        p for p in sent_payloads if p.get("type") == "FEED_SUBSCRIPTION"
    ]
    assert feed_sub_msgs, (
        "Expected FEED_SUBSCRIPTION to be re-sent on second (reconnect) connection"
    )
    added = [item for msg in feed_sub_msgs for item in msg.get("add", [])]
    assert {"type": "Quote", "symbol": "AAPL"} in added, (
        f"Expected Quote/AAPL in re-subscription; got: {added}"
    )


# ---------------------------------------------------------------------------
# Test 6 — FEED_SETUP includes Candle in acceptEventFields
# ---------------------------------------------------------------------------

@_require_import
async def test_feed_setup_includes_candle_fields():
    """The FEED_SETUP message sent during the handshake must include 'Candle'
    in acceptEventFields so the server delivers candle data."""
    ws = _make_mock_ws()
    _handshake_responses(ws, [])

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=MagicMock(),
        candle_callback=MagicMock(),
    )

    cm = _make_connected_context(ws)
    with patch("dashboard.streamer.websockets.connect", return_value=cm):
        try:
            await streamer._connect_and_stream()
        except (StopAsyncIteration, Exception):
            pass

    sent_payloads = [json.loads(c.args[0]) for c in ws.send.call_args_list]
    feed_setup_msgs = [p for p in sent_payloads if p.get("type") == "FEED_SETUP"]
    assert feed_setup_msgs, "Expected at least one FEED_SETUP message"

    accept_fields = feed_setup_msgs[0].get("acceptEventFields", {})
    assert "Candle" in accept_fields, (
        f"Expected 'Candle' in acceptEventFields; got keys: {list(accept_fields.keys())}"
    )


# ---------------------------------------------------------------------------
# Test 7 — add_quote before connect: subscribed on first connect
# ---------------------------------------------------------------------------

@_require_import
async def test_add_quote_before_connect_subscribed_on_connect():
    """add_quote() called before _connect_and_stream() must result in the
    FEED_SUBSCRIPTION being sent as part of the initial connection handshake."""
    ws = _make_mock_ws()
    _handshake_responses(ws, [])

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=MagicMock(),
        candle_callback=MagicMock(),
    )
    streamer.add_quote("TSLA")

    cm = _make_connected_context(ws)
    with patch("dashboard.streamer.websockets.connect", return_value=cm):
        try:
            await streamer._connect_and_stream()
        except (StopAsyncIteration, Exception):
            pass

    sent_payloads = [json.loads(c.args[0]) for c in ws.send.call_args_list]
    feed_sub_msgs = [p for p in sent_payloads if p.get("type") == "FEED_SUBSCRIPTION"]
    assert feed_sub_msgs, "Expected at least one FEED_SUBSCRIPTION message"

    added = [item for msg in feed_sub_msgs for item in msg.get("add", [])]
    assert {"type": "Quote", "symbol": "TSLA"} in added, (
        f"Expected Quote/TSLA in FEED_SUBSCRIPTION add list; got: {added}"
    )


# ---------------------------------------------------------------------------
# Test 8 — Quote with zero bid does not trigger price_callback
# ---------------------------------------------------------------------------

@_require_import
async def test_quote_with_zero_bid_does_not_call_callback():
    """A Quote FEED_DATA event with bidPrice=0.0 must NOT trigger price_callback.
    The implementation filters out zero/invalid bids to avoid bad price data."""
    # Real DXLink FULL data format: flat list of event objects tagged by eventType.
    feed_data_msg = json.dumps(
        {
            "type": "FEED_DATA",
            "channel": 1,
            "data": [
                {
                    "eventType": "Quote",
                    "eventSymbol": "AAPL",
                    "bidPrice": 0.0,
                    "askPrice": 100.0,
                }
            ],
        }
    )

    ws = _make_mock_ws()
    _handshake_responses(ws, [feed_data_msg])

    price_cb = MagicMock()
    candle_cb = MagicMock()

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=price_cb,
        candle_callback=candle_cb,
    )

    cm = _make_connected_context(ws)
    with patch("dashboard.streamer.websockets.connect", return_value=cm):
        try:
            await streamer._connect_and_stream()
        except (StopAsyncIteration, Exception):
            pass

    price_cb.assert_not_called()
