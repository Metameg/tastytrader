from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from dashboard.state import DashboardState
from dashboard.api import fetch_balance, fetch_positions, fetch_orders, fetch_quote_token
from src.models import PriceEvent


# --- DashboardState ---

def test_get_account_summary_returns_all_fields():
    state = DashboardState(
        account_number="5WX78966",
        net_liquidating_value="10525.00",
        buying_power="5000.00",
    )
    summary = state.get_account_summary()
    assert summary["account_number"] == "5WX78966"
    assert summary["net_liquidating_value"] == "10525.00"
    assert summary["buying_power"] == "5000.00"


def test_get_account_summary_defaults_to_dashes():
    state = DashboardState()
    summary = state.get_account_summary()
    assert summary["account_number"] == "—"
    assert summary["net_liquidating_value"] == "—"
    assert summary["buying_power"] == "—"


# --- fetch_balance ---

async def test_fetch_balance_normalises_fields():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "account-number": "5WX78966",
            "net-liquidating-value": "10525.00",
            "derivative-buying-power": "5000.00",
        }
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        balance = await fetch_balance(session_token="tok", account_number="5WX78966")

    assert balance["account_number"] == "5WX78966"
    assert balance["net_liquidating_value"] == "10525.00"
    assert balance["buying_power"] == "5000.00"


async def test_fetch_balance_sends_auth_header():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "account-number": "5WX78966",
            "net-liquidating-value": "0",
            "buying-power": "0",
        }
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await fetch_balance(session_token="my-token", account_number="5WX78966")

    _, kwargs = mock_client.get.call_args
    assert kwargs["headers"]["Authorization"] == "my-token"


# --- fetch_positions ---

async def test_fetch_positions_normalises_fields():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "items": [
                {
                    "symbol": "AAPL",
                    "instrument-type": "Equity",
                    "quantity": "10",
                    "average-open-price": "150.00",
                }
            ]
        }
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        positions = await fetch_positions(session_token="tok", account_number="5WX78966")

    assert len(positions) == 1
    pos = positions[0]
    assert pos["symbol"] == "AAPL"
    assert pos["instrument_type"] == "Equity"
    assert pos["quantity"] == 10
    assert pos["avg_cost"] == "150.00"


async def test_fetch_positions_returns_empty_list_when_no_positions():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"items": []}}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        positions = await fetch_positions(session_token="tok", account_number="5WX78966")

    assert positions == []


async def test_fetch_positions_sends_auth_header():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"items": []}}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await fetch_positions(session_token="my-token", account_number="5WX78966")

    _, kwargs = mock_client.get.call_args
    assert kwargs["headers"]["Authorization"] == "my-token"


# --- DashboardState broadcast / subscriber (Issue #4) ---

async def test_add_subscriber_returns_queue_that_receives_broadcasts():
    """add_subscriber() returns an asyncio.Queue; broadcasting an event
    places exactly one item on that queue with the correct event name and data."""
    state = DashboardState()

    queue = await state.add_subscriber()

    assert isinstance(queue, asyncio.Queue), (
        f"Expected asyncio.Queue from add_subscriber(), got {type(queue)}"
    )

    await state.broadcast("quote", {"symbol": "AAPL", "last": 100.0})

    assert not queue.empty(), "Queue should contain the broadcast event"
    item = queue.get_nowait()
    assert item["event"] == "quote"
    assert item["data"]["symbol"] == "AAPL"


async def test_remove_subscriber_stops_receiving_broadcasts():
    """After remove_subscriber(queue), subsequent broadcasts do NOT
    add anything to that queue."""
    state = DashboardState()

    queue = await state.add_subscriber()
    await state.remove_subscriber(queue)

    await state.broadcast("quote", {"symbol": "AAPL", "last": 100.0})

    assert queue.empty(), (
        "Queue should be empty after remove_subscriber() — broadcast should not reach it"
    )


# --- DashboardState on_quote / EMA (Issue #4) ---

def test_on_quote_updates_quotes_dict():
    """on_quote() must store the latest price data for the symbol in quotes dict."""
    state = DashboardState()
    event = PriceEvent(symbol="AAPL", last=100.0, bid=99.0, ask=101.0, timestamp=1.0)

    state.on_quote(event)

    assert state.quotes["AAPL"]["last"] == 100.0
    assert state.quotes["AAPL"]["bid"] == 99.0


def test_on_quote_broadcasts_quote_event():
    """on_quote() must place a quote event on each subscriber queue with
    the correct event name and symbol in data."""
    state = DashboardState()
    queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(queue)

    event = PriceEvent(symbol="AAPL", last=100.0, bid=99.0, ask=101.0, timestamp=1.0)
    state.on_quote(event)

    assert not queue.empty(), "Subscriber queue should contain the broadcast"
    item = queue.get_nowait()
    assert item["event"] == "quote"
    assert item["data"]["symbol"] == "AAPL"


def test_broadcast_to_multiple_subscribers():
    """broadcast() must deliver the same event to every subscriber queue."""
    state = DashboardState()
    queue_a: asyncio.Queue = asyncio.Queue()
    queue_b: asyncio.Queue = asyncio.Queue()
    state.subscribers.extend([queue_a, queue_b])

    event = PriceEvent(symbol="TSLA", last=200.0, bid=199.0, ask=201.0, timestamp=2.0)
    state.on_quote(event)

    assert not queue_a.empty(), "First subscriber should receive the broadcast"
    assert not queue_b.empty(), "Second subscriber should receive the broadcast"
    assert queue_a.get_nowait()["data"]["symbol"] == "TSLA"
    assert queue_b.get_nowait()["data"]["symbol"] == "TSLA"


def test_on_quote_ema_short_none_before_warmup():
    """ema_short must be None until 10 quotes have been processed (EMA warmup period).
    The 9th quote is still below the period=10 threshold, so ema_short stays None."""
    state = DashboardState()

    for i in range(8):
        state.on_quote(PriceEvent(symbol="AAPL", last=float(100 + i), bid=99.0, ask=101.0, timestamp=float(i)))

    last_queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(last_queue)
    state.on_quote(PriceEvent(symbol="AAPL", last=108.0, bid=99.0, ask=101.0, timestamp=8.0))

    item = last_queue.get_nowait()
    assert item["data"]["ema_short"] is None, (
        f"ema_short should be None before 10 quotes (period=10 warmup); got {item['data']['ema_short']}"
    )


def test_on_quote_ema_long_none_before_20_warmup():
    """After 15 quotes, ema_short (period=10) is populated but ema_long (period=20)
    is still None — it requires 20 quotes to warm up."""
    state = DashboardState()

    for i in range(14):
        state.on_quote(PriceEvent(symbol="AAPL", last=float(100 + i), bid=99.0, ask=101.0, timestamp=float(i)))

    last_queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(last_queue)
    state.on_quote(PriceEvent(symbol="AAPL", last=114.0, bid=99.0, ask=101.0, timestamp=14.0))

    item = last_queue.get_nowait()
    assert item["data"]["ema_short"] is not None, (
        "ema_short should be populated after 15 quotes (period=10 warmup complete)"
    )
    assert item["data"]["ema_long"] is None, (
        f"ema_long should still be None after only 15 quotes; got {item['data']['ema_long']}"
    )


# --- fetch_quote_token ---

async def test_fetch_quote_token_returns_token_and_url():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "token": "quote-tok-123",
            "dxlink-url": "wss://tasty-openapi-ws.dxfeed.com/realtime",
        }
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_quote_token(session_token="sess-tok")

    assert result["token"] == "quote-tok-123"
    assert result["dxlink_url"] == "wss://tasty-openapi-ws.dxfeed.com/realtime"


async def test_fetch_quote_token_sends_auth_header():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {"token": "t", "dxlink-url": "wss://example.com"}
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await fetch_quote_token(session_token="my-session-token")

    _, kwargs = mock_client.get.call_args
    assert kwargs["headers"]["Authorization"] == "my-session-token"
    assert kwargs.get("headers") or mock_client.get.call_args[1]["headers"]
    # verify endpoint
    url_called = mock_client.get.call_args[0][0]
    assert url_called.endswith("/api-quote-tokens")


# --- fetch_orders (Issue #10) ---

async def test_fetch_orders_includes_order_id():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "items": [
                {
                    "id": 12345,
                    "underlying-symbol": "AAPL",
                    "order-type": "Limit",
                    "price": "150.00",
                    "status": "Live",
                    "received-at": "2026-05-28T10:00:00.000Z",
                    "legs": [{"symbol": "AAPL", "action": "Buy to Open", "quantity": "1"}],
                }
            ]
        }
    }
    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        orders = await fetch_orders(session_token="tok", account_number="5WX78966")

    assert orders[0]["id"] == 12345


# --- cancel_order ---

async def test_cancel_order_sends_delete_to_correct_endpoint():
    from dashboard.api import cancel_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {}}

    mock_client = AsyncMock()
    mock_client.delete.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await cancel_order(session_token="tok", account_number="5WX78966", order_id="abc123")

    args, _ = mock_client.delete.call_args
    assert args[0] == "https://api.cert.tastyworks.com/accounts/5WX78966/orders/abc123"


async def test_cancel_order_sends_auth_header():
    from dashboard.api import cancel_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {}}

    mock_client = AsyncMock()
    mock_client.delete.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await cancel_order(session_token="my-token", account_number="5WX78966", order_id="abc123")

    _, kwargs = mock_client.delete.call_args
    assert kwargs["headers"]["Authorization"] == "my-token"


async def test_cancel_order_raises_on_non_200_response():
    from dashboard.api import cancel_order

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "422 Unprocessable Entity",
        request=MagicMock(),
        response=MagicMock(),
    )

    mock_client = AsyncMock()
    mock_client.delete.return_value = mock_response

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        with pytest.raises(httpx.HTTPStatusError):
            await cancel_order(session_token="tok", account_number="5WX78966", order_id="abc123")


# --- place_order ---

async def test_place_order_builds_correct_body_for_equity():
    from dashboard.api import place_order, BASE_URL

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-001"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await place_order(
            session_token="tok",
            account_number="5WX78966",
            symbol="AAPL",
            instrument_type="Equity",
            action="Buy to Open",
            quantity=5,
            limit_price=150.0,
        )

    args, kwargs = mock_client.post.call_args
    assert args[0] == f"{BASE_URL}/accounts/5WX78966/orders"
    body = kwargs["json"]
    assert body["order-type"] == "Limit"
    assert body["time-in-force"] == "Day"
    assert body["price"] == "150.00"
    leg = body["legs"][0]
    assert leg["instrument-type"] == "Equity"
    assert leg["symbol"] == "AAPL"
    assert leg["quantity"] == 5
    assert leg["action"] == "Buy to Open"


async def test_place_order_builds_correct_body_for_equity_option():
    from dashboard.api import place_order, BASE_URL

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-002"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await place_order(
            session_token="tok",
            account_number="5WX78966",
            symbol="AAPL  260117C00150000",
            instrument_type="Equity Option",
            action="Sell to Close",
            quantity=1,
            limit_price=2.50,
        )

    _, kwargs = mock_client.post.call_args
    leg = kwargs["json"]["legs"][0]
    assert leg["instrument-type"] == "Equity Option"
    assert leg["symbol"] == "AAPL  260117C00150000"
    assert leg["quantity"] == 1
    assert leg["action"] == "Sell to Close"


async def test_place_order_sets_price_effect_debit_for_buy_to_open():
    from dashboard.api import place_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-003"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await place_order(
            session_token="tok",
            account_number="5WX78966",
            symbol="AAPL",
            instrument_type="Equity",
            action="Buy to Open",
            quantity=1,
            limit_price=100.0,
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["price-effect"] == "Debit"


async def test_place_order_sets_price_effect_credit_for_sell_to_close():
    from dashboard.api import place_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-004"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await place_order(
            session_token="tok",
            account_number="5WX78966",
            symbol="AAPL",
            instrument_type="Equity",
            action="Sell to Close",
            quantity=1,
            limit_price=100.0,
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["price-effect"] == "Credit"


async def test_place_order_sends_auth_header():
    from dashboard.api import place_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-005"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await place_order(
            session_token="my-secret-token",
            account_number="5WX78966",
            symbol="AAPL",
            instrument_type="Equity",
            action="Buy to Open",
            quantity=1,
            limit_price=150.0,
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["Authorization"] == "my-secret-token"


async def test_place_order_returns_order_id_on_success():
    from dashboard.api import place_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-999"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        order_id = await place_order(
            session_token="tok",
            account_number="5WX78966",
            symbol="AAPL",
            instrument_type="Equity",
            action="Buy to Open",
            quantity=1,
            limit_price=150.0,
        )

    assert order_id == "ORD-999"


async def test_place_order_formats_price_with_two_decimal_places_for_whole_number():
    from dashboard.api import place_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-A"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await place_order(
            session_token="tok",
            account_number="5WX78966",
            symbol="AAPL",
            instrument_type="Equity",
            action="Buy to Open",
            quantity=1,
            limit_price=150,
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["price"] == "150.00"


async def test_place_order_formats_price_with_two_decimal_places_for_one_decimal():
    from dashboard.api import place_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-B"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await place_order(
            session_token="tok",
            account_number="5WX78966",
            symbol="AAPL",
            instrument_type="Equity",
            action="Buy to Open",
            quantity=1,
            limit_price=150.5,
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["price"] == "150.50"


async def test_place_order_puts_quantity_value_into_leg():
    from dashboard.api import place_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"order": {"id": "ORD-C"}}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await place_order(
            session_token="tok",
            account_number="5WX78966",
            symbol="AAPL",
            instrument_type="Equity",
            action="Buy to Open",
            quantity=7,
            limit_price=100.0,
        )

    _, kwargs = mock_client.post.call_args
    assert kwargs["json"]["legs"][0]["quantity"] == 7


async def test_place_order_raises_on_non_2xx_response():
    from dashboard.api import place_order

    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "422 Unprocessable Entity",
        request=MagicMock(),
        response=MagicMock(),
    )

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        with pytest.raises(httpx.HTTPStatusError):
            await place_order(
                session_token="tok",
                account_number="5WX78966",
                symbol="AAPL",
                instrument_type="Equity",
                action="Buy to Open",
                quantity=1,
                limit_price=150.0,
            )
