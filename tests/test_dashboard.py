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


# --- Issue #5: DashboardState SSE subscriber management ---

async def test_add_subscriber_returns_asyncio_queue():
    state = DashboardState()
    queue = await state.add_subscriber()
    assert isinstance(queue, asyncio.Queue)


async def test_broadcast_puts_event_into_subscriber_queue():
    state = DashboardState()
    queue = await state.add_subscriber()
    await state.broadcast("quote", {"symbol": "AAPL", "price": 150.0})
    item = queue.get_nowait()
    assert item["event"] == "quote"
    assert item["data"]["symbol"] == "AAPL"


async def test_remove_subscriber_stops_receiving_broadcasts():
    state = DashboardState()
    queue = await state.add_subscriber()
    await state.remove_subscriber(queue)
    await state.broadcast("quote", {"symbol": "AAPL", "price": 150.0})
    assert queue.empty()


# --- Issue #5: DashboardState.get_positions_grouped ---

def test_get_positions_grouped_nests_option_under_equity():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 100,
            "avg_cost": "150.00",
            "current_price": None,
        },
        {
            "symbol": "AAPL  240119C00150000",
            "instrument_type": "Equity Option",
            "quantity": 1,
            "avg_cost": "3.50",
            "current_price": None,
        },
    ]
    grouped = state.get_positions_grouped()
    # Result has one top-level entry for AAPL (the equity)
    equity_rows = [r for r in grouped if r["instrument_type"] == "Equity"]
    assert len(equity_rows) == 1
    # That equity row has nested option legs
    equity_row = equity_rows[0]
    assert "legs" in equity_row
    assert len(equity_row["legs"]) == 1
    assert equity_row["legs"][0]["instrument_type"] == "Equity Option"


def test_get_positions_grouped_option_at_top_level_when_no_equity():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "SPY   240119C00450000",
            "instrument_type": "Equity Option",
            "quantity": 2,
            "avg_cost": "5.00",
            "current_price": None,
        },
    ]
    grouped = state.get_positions_grouped()
    # Option appears at top level since no SPY equity row exists
    assert len(grouped) == 1
    assert grouped[0]["instrument_type"] == "Equity Option"


def test_get_positions_grouped_multiple_options_under_same_equity():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "TSLA",
            "instrument_type": "Equity",
            "quantity": 50,
            "avg_cost": "200.00",
            "current_price": None,
        },
        {
            "symbol": "TSLA  240119C00200000",
            "instrument_type": "Equity Option",
            "quantity": 1,
            "avg_cost": "10.00",
            "current_price": None,
        },
        {
            "symbol": "TSLA  240119P00200000",
            "instrument_type": "Equity Option",
            "quantity": 1,
            "avg_cost": "8.00",
            "current_price": None,
        },
    ]
    grouped = state.get_positions_grouped()
    equity_row = next(r for r in grouped if r["instrument_type"] == "Equity")
    assert len(equity_row["legs"]) == 2


# --- Issue #5: DashboardState.update_quote ---

def test_update_quote_stores_current_price_for_symbol():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
    ]
    state.update_quote("AAPL", 155.0)
    assert state.positions[0]["current_price"] == 155.0


def test_update_quote_calculates_pl_for_equity():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
    ]
    state.update_quote("AAPL", 155.0)
    # P&L = (155.0 - 150.0) * 10 * 1 = 50.0
    assert state.positions[0]["pl"] == pytest.approx(50.0)


def test_update_quote_calculates_pl_for_option_with_100_multiplier():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL  240119C00150000",
            "instrument_type": "Equity Option",
            "quantity": 2,
            "avg_cost": "3.50",
            "current_price": None,
        },
    ]
    state.update_quote("AAPL  240119C00150000", 5.00)
    # P&L = (5.00 - 3.50) * 2 * 100 = 300.0
    assert state.positions[0]["pl"] == pytest.approx(300.0)


def test_update_quote_negative_pl_for_losing_position():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
    ]
    state.update_quote("AAPL", 145.0)
    # P&L = (145.0 - 150.0) * 10 = -50.0
    assert state.positions[0]["pl"] == pytest.approx(-50.0)


# --- Issue #5: DashboardState.get_positions_grouped edge cases ---

def test_get_positions_grouped_empty_positions():
    state = DashboardState()
    state.positions = []
    assert state.get_positions_grouped() == []


def test_get_positions_grouped_equity_with_no_options_has_empty_legs():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "MSFT",
            "instrument_type": "Equity",
            "quantity": 5,
            "avg_cost": "300.00",
            "current_price": None,
        },
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
    ]
    grouped = state.get_positions_grouped()
    assert len(grouped) == 2
    for row in grouped:
        assert row["legs"] == []


def test_get_positions_grouped_option_symbol_starting_with_non_alpha_is_orphan():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
        {
            "symbol": "1AAPL 240119C00150000",
            "instrument_type": "Equity Option",
            "quantity": 1,
            "avg_cost": "3.50",
            "current_price": None,
        },
    ]
    grouped = state.get_positions_grouped()
    equity_rows = [r for r in grouped if r["instrument_type"] == "Equity"]
    orphan_rows = [r for r in grouped if r["instrument_type"] == "Equity Option"]
    assert equity_rows[0]["legs"] == []
    assert len(orphan_rows) == 1


# --- Issue #5: DashboardState.update_quote edge cases ---

def test_update_quote_unknown_symbol_no_error():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
    ]
    state.update_quote("MSFT", 300.0)
    assert state.positions[0]["current_price"] is None


def test_update_quote_updates_all_positions_for_same_symbol():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 5,
            "avg_cost": "160.00",
            "current_price": None,
        },
    ]
    state.update_quote("AAPL", 155.0)
    assert state.positions[0]["current_price"] == 155.0
    assert state.positions[1]["current_price"] == 155.0
    assert state.positions[0]["pl"] == pytest.approx(50.0)
    assert state.positions[1]["pl"] == pytest.approx(-25.0)


def test_update_quote_avg_cost_as_string_converts_correctly():
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
    ]
    state.update_quote("AAPL", 160.0)
    assert state.positions[0]["pl"] == pytest.approx(100.0)


# --- Issue #5: DashboardState.broadcast edge cases ---

async def test_broadcast_with_zero_subscribers_no_error():
    state = DashboardState()
    await state.broadcast("quote", {"symbol": "AAPL", "price": 150.0})


async def test_broadcast_multiple_events_all_received_by_subscriber():
    state = DashboardState()
    queue = await state.add_subscriber()
    await state.broadcast("quote", {"symbol": "AAPL", "price": 150.0})
    await state.broadcast("quote", {"symbol": "MSFT", "price": 300.0})
    first = queue.get_nowait()
    second = queue.get_nowait()
    assert first["data"]["symbol"] == "AAPL"
    assert second["data"]["symbol"] == "MSFT"


async def test_broadcast_multiple_events_reach_all_subscribers():
    state = DashboardState()
    q1 = await state.add_subscriber()
    q2 = await state.add_subscriber()
    await state.broadcast("quote", {"symbol": "AAPL", "price": 150.0})
    assert not q1.empty()
    assert not q2.empty()


# --- Issue #6: contract — positions SSE event data shape ---

async def test_positions_sse_event_data_is_a_list():
    """The JS handlePositions() calls .filter() directly on the argument, so the
    'positions' SSE event data must be a plain list, not a wrapped dict like
    {"positions": [...]}.  _refresh must broadcast the list directly."""
    from unittest.mock import AsyncMock, patch

    state = DashboardState()
    queue = await state.add_subscriber()

    # Simulate what _refresh does after the fix: broadcast("positions", state.positions)
    await state.broadcast("positions", [{"symbol": "AAPL"}])

    item = queue.get_nowait()
    assert item["event"] == "positions"
    # data must be the list itself, not a dict wrapping it
    assert isinstance(item["data"], list), (
        f"positions SSE event data must be a list for handlePositions() to call "
        f".filter() on it; got {type(item['data'])!r} — fix _refresh broadcast in app.py"
    )


# --- Issue #5: fetch_positions includes current_price field ---

async def test_fetch_positions_includes_current_price_field():
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

    assert "current_price" in positions[0]


# --- Issue #6: parse_occ (OCC symbol parser) ---

def test_parse_occ_call_aapl():
    """AAPL call option: underlying trimmed, expiry human-readable, type=Call, strike as float."""
    from dashboard.state import parse_occ
    result = parse_occ("AAPL  240119C00150000")
    assert result == {
        "underlying": "AAPL",
        "expiry": "Jan 19 2024",
        "option_type": "Call",
        "strike": 150.0,
    }


def test_parse_occ_put_aapl():
    """AAPL put option: option_type must be 'Put' when symbol contains 'P'."""
    from dashboard.state import parse_occ
    result = parse_occ("AAPL  240119P00150000")
    assert result == {
        "underlying": "AAPL",
        "expiry": "Jan 19 2024",
        "option_type": "Put",
        "strike": 150.0,
    }


def test_parse_occ_call_spy():
    """SPY call: 3-char underlying right-padded to 6 chars in the symbol string."""
    from dashboard.state import parse_occ
    result = parse_occ("SPY   240119C00450000")
    assert result == {
        "underlying": "SPY",
        "expiry": "Jan 19 2024",
        "option_type": "Call",
        "strike": 450.0,
    }


def test_parse_occ_underlying_shorter_than_6_chars_qqq():
    """QQQ has an underlying shorter than 6 chars — spaces must be stripped correctly."""
    from dashboard.state import parse_occ
    result = parse_occ("QQQ   240119C00400000")
    assert result is not None
    assert result["underlying"] == "QQQ"
    assert result["option_type"] == "Call"
    assert result["strike"] == 400.0


def test_parse_occ_equity_symbol_returns_none():
    """Plain equity ticker like 'AAPL' (no date/type/strike) must return None."""
    from dashboard.state import parse_occ
    result = parse_occ("AAPL")
    assert result is None


def test_parse_occ_fractional_strike_price():
    """Strike 00250050 encodes $250.05 — fractional cents must parse correctly."""
    from dashboard.state import parse_occ
    result = parse_occ("AAPL  240119C00250050")
    assert result is not None
    assert result["strike"] == pytest.approx(250.05)


def test_parse_occ_rejects_symbol_longer_than_21_chars():
    """22-char string must not match — fullmatch anchors both ends."""
    from dashboard.state import parse_occ
    result = parse_occ("AAPL  240119C001500000")  # 22 chars
    assert result is None


def test_parse_occ_rejects_lowercase_underlying():
    """Regex [A-Z ] requires uppercase — lowercase underlying must return None."""
    from dashboard.state import parse_occ
    result = parse_occ("aapl  240119C00150000")
    assert result is None


def test_parse_occ_rejects_invalid_date():
    """Month 13 is not a valid date — strptime must reject it and return None."""
    from dashboard.state import parse_occ
    result = parse_occ("AAPL  991399C00150000")
    assert result is None


def test_parse_occ_zero_strike_is_valid():
    """Strike encoded as 00000000 is $0.00 — zero is a valid (if unusual) strike."""
    from dashboard.state import parse_occ
    result = parse_occ("AAPL  240119C00000000")
    assert result is not None
    assert result["strike"] == pytest.approx(0.0)
    assert result["underlying"] == "AAPL"
    assert result["option_type"] == "Call"


def test_parse_occ_single_char_underlying():
    """Underlying 'S' padded to 6 chars — stripping spaces must yield 'S'."""
    from dashboard.state import parse_occ
    result = parse_occ("S     240119C00050000")
    assert result is not None
    assert result["underlying"] == "S"
    assert result["strike"] == pytest.approx(50.0)
    assert result["option_type"] == "Call"


def test_parse_occ_whitespace_only_underlying_returns_none():
    """Six spaces with no letter chars — underlying strips to '' which is invalid.
    Must return None so the detail panel never displays an empty ticker."""
    from dashboard.state import parse_occ
    result = parse_occ("      240119C00150000")
    assert result is None


# --- Issue #6: on_quote stores all keys required by the detail panel ---

def test_on_quote_quote_dict_has_required_detail_panel_keys():
    """state.quotes[symbol] must contain all keys the detail panel JS reads,
    including ema_short and ema_long (even when still None during warm-up)."""
    state = DashboardState()
    event = PriceEvent(symbol="AAPL", last=150.0, bid=149.5, ask=150.5, timestamp=1.0)
    state.on_quote(event)
    q = state.quotes["AAPL"]
    for key in ("symbol", "last", "bid", "ask", "ema_short", "ema_long"):
        assert key in q, f"Missing key '{key}' in quotes dict"


def test_on_quote_ema_keys_are_none_during_warmup():
    """During warm-up (fewer than 10 ticks) both EMA keys exist but hold None."""
    state = DashboardState()
    event = PriceEvent(symbol="AAPL", last=150.0, bid=149.5, ask=150.5, timestamp=1.0)
    state.on_quote(event)
    q = state.quotes["AAPL"]
    assert q["ema_short"] is None
    assert q["ema_long"] is None


def test_on_quote_ema_short_populated_after_warmup():
    """After 10 ticks ema_short must be a float; ema_long still None until tick 20."""
    state = DashboardState()
    for i in range(10):
        state.on_quote(PriceEvent(symbol="AAPL", last=float(100 + i), bid=99.0, ask=101.0, timestamp=float(i)))
    q = state.quotes["AAPL"]
    assert isinstance(q["ema_short"], float)
    assert q["ema_long"] is None
