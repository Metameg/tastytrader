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


def test_on_quote_ema_short_seeded_from_first_tick():
    """ema_short must be non-None from the very first quote because DashboardState
    seeds each new EMACalculator with the first observed price so the detail panel
    always has a value to display."""
    state = DashboardState()

    for i in range(8):
        state.on_quote(PriceEvent(symbol="AAPL", last=float(100 + i), bid=99.0, ask=101.0, timestamp=float(i)))

    last_queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(last_queue)
    state.on_quote(PriceEvent(symbol="AAPL", last=108.0, bid=99.0, ask=101.0, timestamp=8.0))

    item = last_queue.get_nowait()
    assert isinstance(item["data"]["ema_short"], float), (
        f"ema_short should be a float on every tick (seeded from first price); got {item['data']['ema_short']}"
    )


def test_on_quote_both_emas_seeded_from_first_tick():
    """Both ema_short and ema_long must be non-None from the first quote onward.
    DashboardState seeds each new EMACalculator with the first observed price,
    so neither EMA goes through a None warm-up phase for display purposes."""
    state = DashboardState()

    for i in range(14):
        state.on_quote(PriceEvent(symbol="AAPL", last=float(100 + i), bid=99.0, ask=101.0, timestamp=float(i)))

    last_queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(last_queue)
    state.on_quote(PriceEvent(symbol="AAPL", last=114.0, bid=99.0, ask=101.0, timestamp=14.0))

    item = last_queue.get_nowait()
    assert isinstance(item["data"]["ema_short"], float), (
        "ema_short should be a float on every tick (seeded from first price)"
    )
    assert isinstance(item["data"]["ema_long"], float), (
        f"ema_long should be a float on every tick (seeded from first price); got {item['data']['ema_long']}"
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
    assert leg["quantity"] == "5"
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
    assert leg["quantity"] == "1"
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
    assert kwargs["json"]["legs"][0]["quantity"] == "7"


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


def test_on_quote_ema_keys_are_floats_from_first_tick():
    """Both EMA keys must hold a float from the very first tick.
    DashboardState seeds each new EMACalculator with the first price so the
    detail panel never shows a dash due to a warm-up gap."""
    state = DashboardState()
    event = PriceEvent(symbol="AAPL", last=150.0, bid=149.5, ask=150.5, timestamp=1.0)
    state.on_quote(event)
    q = state.quotes["AAPL"]
    assert isinstance(q["ema_short"], float)
    assert isinstance(q["ema_long"], float)


def test_on_quote_ema_short_populated_after_warmup():
    """After 10 ticks both EMAs are floats; ema_long is seeded from tick 1 and has
    been converging for 10 ticks by this point."""
    state = DashboardState()
    for i in range(10):
        state.on_quote(PriceEvent(symbol="AAPL", last=float(100 + i), bid=99.0, ask=101.0, timestamp=float(i)))
    q = state.quotes["AAPL"]
    assert isinstance(q["ema_short"], float)
    assert isinstance(q["ema_long"], float)


# --- Issue #7: DashboardState.on_candle accumulates history ---

def test_on_candle_accumulates_candles_for_symbol():
    """on_candle must store candle dicts so get_chart_data can return them.
    A candle with eventSymbol 'AAPL{=d}' must be stored under the plain key 'AAPL'."""
    state = DashboardState()
    candle = {
        "eventSymbol": "AAPL{=d}",
        "open": 150.0,
        "high": 155.0,
        "low": 148.0,
        "close": 153.0,
        "volume": 1_000_000,
    }
    state.on_candle(candle)

    data = state.get_chart_data("AAPL")
    assert len(data["close"]) == 1
    assert data["close"][0] == 153.0


def test_on_candle_normalizes_dxfeed_suffix_to_plain_symbol():
    """eventSymbol 'AAPL{=d}' must be stored under plain key 'AAPL'
    because clients fetch /api/chart/AAPL (no suffix)."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })

    # Must be retrievable under the plain symbol
    data = state.get_chart_data("AAPL")
    assert data["close"] != [], "Expected candle stored under plain symbol AAPL"

    # Must NOT be stored under the suffixed symbol
    data_suffixed = state.get_chart_data("AAPL{=d}")
    assert data_suffixed["close"] == [], "Suffixed symbol 'AAPL{=d}' must not be a valid key"


def test_on_candle_still_broadcasts_candle_event():
    """on_candle must continue to broadcast a 'candle' SSE event to subscribers
    so existing real-time behaviour is preserved."""
    state = DashboardState()
    queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(queue)

    candle = {
        "eventSymbol": "AAPL{=d}",
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    }
    state.on_candle(candle)

    assert not queue.empty(), "Subscriber queue must receive a 'candle' event"
    item = queue.get_nowait()
    assert item["event"] == "candle"


def test_on_candle_accumulates_multiple_candles_in_order():
    """Multiple on_candle calls must accumulate all candles; get_chart_data returns
    close prices in the order they were appended."""
    state = DashboardState()
    closes = [100.0, 101.0, 102.0, 103.0]
    for i, close_price in enumerate(closes):
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "open": close_price - 1,
            "high": close_price + 1,
            "low": close_price - 2,
            "close": close_price,
            "volume": 1_000_000,
        })

    data = state.get_chart_data("AAPL")
    assert data["close"] == closes


# --- Issue #7: DashboardState.get_chart_data ---

def test_get_chart_data_unknown_symbol_returns_empty_arrays():
    """Unknown symbol with no candles must return empty arrays for all keys.
    This allows the route to signal 'hide the chart' to the frontend."""
    state = DashboardState()
    data = state.get_chart_data("UNKNOWN")
    assert data == {"labels": [], "open": [], "high": [], "low": [], "close": [], "ema_short": [], "ema_long": []}


def test_get_chart_data_returns_required_keys():
    """get_chart_data must return a dict with exactly the keys labels, close,
    ema_short, ema_long (the shape the frontend Chart.js code expects)."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    data = state.get_chart_data("AAPL")
    for key in ("labels", "close", "ema_short", "ema_long"):
        assert key in data, f"Missing key '{key}' in get_chart_data result"


def test_get_chart_data_close_matches_stored_close_prices():
    """The 'close' array in get_chart_data must equal the close prices fed via
    on_candle in chronological order."""
    state = DashboardState()
    closes = [148.0, 150.0, 152.0, 151.0, 153.0]
    for close_price in closes:
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "open": close_price - 1, "high": close_price + 1, "low": close_price - 2,
            "close": close_price, "volume": 1_000_000,
        })

    data = state.get_chart_data("AAPL")
    assert data["close"] == closes


def test_get_chart_data_ema_arrays_same_length_as_close():
    """ema_short and ema_long arrays must have one value per close price so the
    Chart.js dataset aligns with the labels/close arrays."""
    state = DashboardState()
    closes = [float(100 + i) for i in range(25)]
    for close_price in closes:
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "open": close_price - 1, "high": close_price + 1, "low": close_price - 2,
            "close": close_price, "volume": 1_000_000,
        })

    data = state.get_chart_data("AAPL")
    assert len(data["ema_short"]) == len(closes), (
        f"ema_short length {len(data['ema_short'])} must equal close length {len(closes)}"
    )
    assert len(data["ema_long"]) == len(closes), (
        f"ema_long length {len(data['ema_long'])} must equal close length {len(closes)}"
    )


def test_get_chart_data_ema_final_value_matches_ema_calculator():
    """The final ema_short and ema_long values must match an independently-computed
    EMACalculator over the same close sequence (short period=10, long period=20).
    This pins the computation to real EMACalculator behaviour, not a reimplementation."""
    from src.strategy import EMACalculator

    state = DashboardState()
    closes = [float(100 + i) for i in range(30)]
    for close_price in closes:
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "open": close_price - 1, "high": close_price + 1, "low": close_price - 2,
            "close": close_price, "volume": 1_000_000,
        })

    data = state.get_chart_data("AAPL")

    # Independently compute expected final EMA values
    ema_short_ref = EMACalculator(10)
    ema_long_ref = EMACalculator(20)
    for c in closes:
        ema_short_ref.update(c)
        ema_long_ref.update(c)

    assert data["ema_short"][-1] == pytest.approx(ema_short_ref.value), (
        f"ema_short final value {data['ema_short'][-1]} does not match EMACalculator(10) "
        f"expected {ema_short_ref.value}"
    )
    assert data["ema_long"][-1] == pytest.approx(ema_long_ref.value), (
        f"ema_long final value {data['ema_long'][-1]} does not match EMACalculator(20) "
        f"expected {ema_long_ref.value}"
    )


# --- Issue #7: edge cases ---

def test_get_chart_data_ema_warm_up_none_when_fewer_candles_than_long_period():
    """With fewer candles than the long EMA period (5 < 20), all ema_long entries
    must be None (warm-up region).  All four arrays must be equal length."""
    state = DashboardState()
    closes = [float(150 + i) for i in range(5)]
    for i, close_price in enumerate(closes):
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "time": i,
            "open": close_price - 1, "high": close_price + 1, "low": close_price - 2,
            "close": close_price, "volume": 1_000_000,
        })

    data = state.get_chart_data("AAPL")

    # All four arrays must be the same length
    n = len(data["close"])
    assert n == 5
    assert len(data["labels"]) == n, "labels length must equal close length"
    assert len(data["ema_short"]) == n, "ema_short length must equal close length"
    assert len(data["ema_long"]) == n, "ema_long length must equal close length"

    # With only 5 data points both EMA warm-ups (period 10, 20) are incomplete
    assert all(v is None for v in data["ema_long"]), (
        "All ema_long entries must be None when candle count (5) < long period (20)"
    )
    assert all(v is None for v in data["ema_short"]), (
        "All ema_short entries must be None when candle count (5) < short period (10)"
    )


def test_get_chart_data_ema_long_none_during_warmup_short_resolves_after_period():
    """After exactly 10 candles ema_short resolves to a float but ema_long remains
    None (period=20 not yet reached).  Both arrays are still the same length as close."""
    state = DashboardState()
    for i in range(10):
        state.on_candle({
            "eventSymbol": "SPY{=d}",
            "time": i,
            "open": 450.0, "high": 455.0, "low": 448.0,
            "close": float(450 + i), "volume": 2_000_000,
        })

    data = state.get_chart_data("SPY")

    n = len(data["close"])
    assert n == 10
    assert len(data["ema_short"]) == n
    assert len(data["ema_long"]) == n
    # ema_short warm-up completes exactly at period=10 (last element is float)
    assert isinstance(data["ema_short"][-1], float), (
        "ema_short[-1] must be a float after 10 candles (period=10)"
    )
    # ema_long warm-up is not complete with only 10 candles (period=20)
    assert all(v is None for v in data["ema_long"]), (
        "All ema_long entries must be None when candle count (10) < long period (20)"
    )


def test_get_chart_data_out_of_order_candles_sorted_by_time():
    """Candles delivered out of chronological order must be returned sorted by 'time'.
    The close array and labels must reflect the sorted order."""
    state = DashboardState()
    # Feed candles out of order: time=300, 100, 200
    for time_val, close_val in [(300, 153.0), (100, 143.0), (200, 148.0)]:
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "time": time_val,
            "open": close_val - 1, "high": close_val + 1, "low": close_val - 2,
            "close": close_val, "volume": 1_000_000,
        })

    data = state.get_chart_data("AAPL")

    assert data["close"] == [143.0, 148.0, 153.0], (
        f"Expected closes sorted by time [143, 148, 153]; got {data['close']}"
    )
    assert data["labels"] == [100, 200, 300], (
        f"Expected labels sorted by time [100, 200, 300]; got {data['labels']}"
    )


def test_on_candle_different_symbols_stored_separately():
    """Candles for AAPL and SPY must accumulate in separate buckets.
    Retrieving one symbol must not include candles from the other."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 100,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    state.on_candle({
        "eventSymbol": "SPY{=d}", "time": 100,
        "open": 450.0, "high": 455.0, "low": 448.0, "close": 451.0, "volume": 5_000_000,
    })
    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 200,
        "open": 152.0, "high": 157.0, "low": 150.0, "close": 155.0, "volume": 1_000_000,
    })

    aapl_data = state.get_chart_data("AAPL")
    spy_data = state.get_chart_data("SPY")

    assert aapl_data["close"] == [153.0, 155.0], (
        f"AAPL must have only its own candles; got {aapl_data['close']}"
    )
    assert spy_data["close"] == [451.0], (
        f"SPY must have only its own candle; got {spy_data['close']}"
    )


def test_on_candle_spy_suffix_normalized_not_retrievable_with_suffix():
    """SPY{=d} must be stored under the plain key 'SPY', confirming the suffix
    normalization works for symbols other than AAPL."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "SPY{=d}", "time": 100,
        "open": 450.0, "high": 455.0, "low": 448.0, "close": 451.0, "volume": 5_000_000,
    })

    # Retrievable via plain symbol
    data_plain = state.get_chart_data("SPY")
    assert data_plain["close"] == [451.0], (
        "SPY{=d} candle must be accessible via plain key 'SPY'"
    )

    # NOT retrievable via suffixed key
    data_suffixed = state.get_chart_data("SPY{=d}")
    assert data_suffixed["close"] == [], (
        "Suffixed key 'SPY{=d}' must return empty arrays"
    )


# --- Issue #7: data-contract — candle event key shape vs FEED_SETUP acceptEventFields ---

def test_on_candle_reads_eventSymbol_key_as_sent_by_real_streamer():
    """The streamer's _dispatch_candle forwards the raw FEED_DATA event dict verbatim
    to on_candle.  FEED_SETUP requests 'eventSymbol' for Candle events, so on_candle
    must normalize via ohlc.get('eventSymbol'), not any other key name.
    Uses exactly the keys that FEED_SETUP acceptEventFields['Candle'] requests."""
    state = DashboardState()
    real_streamer_event = {
        "eventType": "Candle",
        "eventSymbol": "MSFT{=d}",
        "open": 420.0,
        "high": 425.0,
        "low": 418.0,
        "close": 422.0,
        "volume": 2_000_000,
    }
    state.on_candle(real_streamer_event)

    data = state.get_chart_data("MSFT")
    assert len(data["close"]) == 1, (
        "on_candle must read 'eventSymbol' (the key FEED_SETUP requests for Candle) "
        "to normalize the symbol; got no data under plain key 'MSFT'"
    )
    assert data["close"][0] == 422.0


def test_dispatch_candle_forwards_raw_event_to_on_candle():
    """DashboardStreamer._dispatch_candle must forward the raw event dict to
    candle_callback without modification.  The dict received by on_candle must
    contain the same keys the FEED_DATA message carried — specifically 'eventSymbol'
    and 'close' — so state.get_chart_data can process them correctly."""
    from dashboard.streamer import DashboardStreamer

    received: list[dict] = []

    def capture_candle(ev: dict) -> None:
        received.append(ev)

    streamer = DashboardStreamer(
        quote_token="tok",
        streamer_url="wss://mock",
        price_callback=lambda e: None,
        candle_callback=capture_candle,
    )

    raw_event = {
        "eventType": "Candle",
        "eventSymbol": "AAPL{=d}",
        "open": 150.0,
        "high": 155.0,
        "low": 148.0,
        "close": 153.0,
        "volume": 1_000_000,
    }
    streamer._dispatch_candle(raw_event)

    assert len(received) == 1, "_dispatch_candle must call candle_callback exactly once"
    ev = received[0]
    assert ev.get("eventSymbol") == "AAPL{=d}", (
        "_dispatch_candle must forward 'eventSymbol' unchanged so on_candle can strip suffix"
    )
    assert ev.get("close") == 153.0, (
        "_dispatch_candle must forward 'close' unchanged so get_chart_data can read it"
    )


def test_feed_setup_candle_accepteventfields_includes_time():
    """FEED_SETUP acceptEventFields for Candle must now include 'time' so that
    get_chart_data can sort candles chronologically and produce real timestamp labels.
    (Deliberate contract change — Defect 2 fix: 'time' was previously absent, causing
    sort to be a no-op and labels to fall back to integer position indices.)"""
    from dashboard.streamer import _FEED_SETUP

    candle_fields = _FEED_SETUP["acceptEventFields"]["Candle"]
    assert "time" in candle_fields, (
        "FEED_SETUP acceptEventFields['Candle'] must include 'time' so real DXLink "
        "candle events carry a sortable timestamp for chronological chart rendering."
    )


# --- Issue #7 (phase-4 fix): Defect 1 — malformed-candle crash guard ---

def test_get_chart_data_skips_candles_missing_close_without_raising():
    """get_chart_data must NOT raise when an accumulated candle is missing 'close'.
    A partial OHLC candle from DXLink (e.g. market-close edge case) must be silently
    skipped; the returned arrays must reflect only the valid candle(s), and all four
    arrays (labels, close, ema_short, ema_long) must be equal-length."""
    state = DashboardState()

    # Accumulate a valid candle
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 100,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    # Accumulate a malformed candle missing the 'close' key entirely
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 200,
        "open": 151.0, "high": 156.0, "low": 149.0,
        # 'close' deliberately absent
        "volume": 1_000_000,
    })

    # Must NOT raise — was crashing with KeyError: 'close'
    data = state.get_chart_data("AAPL")

    # Only the valid candle must survive
    assert data["close"] == [153.0], (
        f"Only the valid candle must be in close; got {data['close']}"
    )
    # All four arrays must be equal-length
    n = len(data["close"])
    assert len(data["labels"]) == n, "labels length must equal close length"
    assert len(data["ema_short"]) == n, "ema_short length must equal close length"
    assert len(data["ema_long"]) == n, "ema_long length must equal close length"


def test_get_chart_data_skips_candles_with_none_close():
    """get_chart_data must skip candles where close is explicitly None.
    All surviving arrays must be equal-length and only contain valid candles."""
    state = DashboardState()

    # Valid candle
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 100,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    # Candle with close=None
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 200,
        "open": 151.0, "high": 156.0, "low": 149.0, "close": None, "volume": 1_000_000,
    })

    data = state.get_chart_data("AAPL")

    assert data["close"] == [153.0], (
        f"Candle with close=None must be filtered out; got {data['close']}"
    )
    n = len(data["close"])
    assert len(data["labels"]) == n
    assert len(data["ema_short"]) == n
    assert len(data["ema_long"]) == n


def test_get_chart_data_labels_are_indices_when_candles_have_no_time_field():
    """When candles do not carry a 'time' field (as the real DXLink FEED_DATA delivers
    given current FEED_SETUP), get_chart_data must fall back to integer position indices
    for labels (c.get('time', i) returns i).  This confirms the fallback path works
    without KeyError and the chart renders with index labels."""
    state = DashboardState()
    for close_price in [100.0, 101.0, 102.0]:
        state.on_candle({
            "eventType": "Candle",
            "eventSymbol": "AAPL{=d}",
            "open": close_price - 1,
            "high": close_price + 1,
            "low": close_price - 2,
            "close": close_price,
            "volume": 1_000_000,
            # Deliberately NO "time" key — matches real FEED_DATA with current FEED_SETUP
        })

    data = state.get_chart_data("AAPL")
    assert data["labels"] == [0, 1, 2], (
        "Without 'time' field, labels must be integer position indices [0, 1, 2]; "
        f"got {data['labels']}"
    )
    assert data["close"] == [100.0, 101.0, 102.0]


# --- FIX 3 (security L2): defensive float parsing in get_chart_data ---

def test_get_chart_data_skips_candle_with_nan_string_close():
    """A candle with close='NaN' must be silently skipped — no exception, no nan in output.
    All four result arrays must remain equal-length and contain only valid candles."""
    state = DashboardState()

    # Valid candle
    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 100,
        "open": 149.0, "high": 154.0, "low": 147.0, "close": 150.0, "volume": 1_000_000,
    })
    # Candle with non-finite close string
    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 200,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": "NaN", "volume": 1_000_000,
    })
    # Another valid candle
    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 300,
        "open": 151.0, "high": 156.0, "low": 149.0, "close": 152.0, "volume": 1_000_000,
    })

    # Must not raise
    data = state.get_chart_data("AAPL")

    assert data["close"] == [150.0, 152.0], (
        f"Candle with close='NaN' must be skipped; got {data['close']}"
    )
    n = len(data["close"])
    assert len(data["labels"]) == n, "labels must equal close length"
    assert len(data["ema_short"]) == n, "ema_short must equal close length"
    assert len(data["ema_long"]) == n, "ema_long must equal close length"


def test_get_chart_data_skips_candle_with_non_numeric_close_string():
    """A candle with close='garbage' (non-numeric string) must be silently skipped."""
    state = DashboardState()

    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 100,
        "close": 148.0, "open": 147.0, "high": 150.0, "low": 146.0, "volume": 1_000_000,
    })
    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 200,
        "close": "not-a-number", "open": 148.0, "high": 151.0, "low": 147.0, "volume": 1_000_000,
    })

    data = state.get_chart_data("AAPL")

    assert data["close"] == [148.0], (
        f"Non-numeric close must be skipped; got {data['close']}"
    )
    n = len(data["close"])
    assert len(data["labels"]) == n
    assert len(data["ema_short"]) == n
    assert len(data["ema_long"]) == n


def test_get_chart_data_skips_candle_with_infinity_close():
    """A candle with close='Infinity' must be skipped — math.isfinite rejects it."""
    state = DashboardState()

    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 100,
        "close": 148.0, "open": 147.0, "high": 150.0, "low": 146.0, "volume": 1_000_000,
    })
    state.on_candle({
        "eventSymbol": "AAPL{=d}", "time": 200,
        "close": "Infinity", "open": 148.0, "high": 151.0, "low": 147.0, "volume": 1_000_000,
    })

    data = state.get_chart_data("AAPL")

    assert data["close"] == [148.0], (
        f"Infinity close must be skipped; got {data['close']}"
    )


# --- FIX 2 (security M2): bound per-symbol candle history to 90 entries ---

def test_on_candle_caps_history_at_90_entries():
    """After accumulating more than 90 candles for a symbol, get_chart_data must
    return at most 90 closes (the most recent ones, in time order)."""
    state = DashboardState()
    # Feed 100 candles with increasing time and close values
    for i in range(100):
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "time": i,
            "open": float(100 + i), "high": float(102 + i),
            "low": float(98 + i), "close": float(100 + i),
            "volume": 1_000_000,
        })

    data = state.get_chart_data("AAPL")
    assert len(data["close"]) <= 90, (
        f"get_chart_data must return at most 90 closes; got {len(data['close'])}"
    )


def test_on_candle_caps_history_keeps_most_recent_entries():
    """When capped at 90, the returned closes must be the last 90 fed (highest time
    values), not the first 90.  Confirms candles are trimmed from the oldest end."""
    state = DashboardState()
    for i in range(100):
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "time": i,
            "close": float(100 + i),
            "open": float(99 + i), "high": float(101 + i), "low": float(98 + i),
            "volume": 1_000_000,
        })

    data = state.get_chart_data("AAPL")
    # The 90 most recent closes are those with time 10..99, i.e. close 110.0..199.0
    assert data["close"][0] == pytest.approx(110.0), (
        f"First close after cap should be 110.0 (oldest of last-90); got {data['close'][0]}"
    )
    assert data["close"][-1] == pytest.approx(199.0), (
        f"Last close after cap should be 199.0 (newest); got {data['close'][-1]}"
    )
# --- fetch_greeks (Issue #8) ---

# OCC symbol used across greeks tests: AAPL, expiry 2025-01-17, Call, $150
_OPTION_SYMBOL = "AAPL  250117C00150000"
_UNDERLYING = "AAPL"

# Canonical full API response shape expected from /option-chains/<underlying>
_GREEKS_API_RESPONSE = {
    "data": {
        "items": [
            {
                "symbol": _OPTION_SYMBOL,
                "delta": "0.42",
                "gamma": "0.03",
                "theta": "-0.05",
                "vega": "0.12",
                "implied-volatility": "0.28",
            }
        ]
    }
}

# Expected normalised dict returned by fetch_greeks when greeks are present
_EXPECTED_GREEKS = {
    "delta": "0.42",
    "gamma": "0.03",
    "theta": "-0.05",
    "vega": "0.12",
    "iv": "0.28",
}

_DASH = "—"


async def test_fetch_greeks_hits_option_chain_endpoint_with_underlying():
    """fetch_greeks must call /option-chains/<UNDERLYING> where UNDERLYING is
    derived from the OCC symbol via parse_occ.  URL must contain the correct path."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _GREEKS_API_RESPONSE

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    call_args, call_kwargs = mock_client.get.call_args
    url = call_args[0] if call_args else call_kwargs.get("url", "")
    assert f"/option-chains/{_UNDERLYING}" in url, (
        f"Expected URL to contain /option-chains/{_UNDERLYING}, got: {url}"
    )


async def test_fetch_greeks_sends_auth_header():
    """fetch_greeks must pass Authorization: <session_token> header."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _GREEKS_API_RESPONSE

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await fetch_greeks(session_token="my-secret-token", symbol=_OPTION_SYMBOL)

    _, kwargs = mock_client.get.call_args
    assert kwargs["headers"]["Authorization"] == "my-secret-token", (
        "Authorization header must equal the session_token passed in"
    )


async def test_fetch_greeks_returns_all_five_greek_keys_when_contract_found():
    """When a matching OCC contract with full greeks is found, fetch_greeks must
    return a dict with exactly delta, gamma, theta, vega, iv keys and their values."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = _GREEKS_API_RESPONSE

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert key in result, f"Expected key '{key}' in result dict, got: {result.keys()}"
    assert result == _EXPECTED_GREEKS


async def test_fetch_greeks_returns_dashes_when_items_list_is_empty():
    """When data.items is an empty list, fetch_greeks must return all five greeks
    as the em-dash sentinel '—' and must NOT raise."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"items": []}}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == _DASH, (
            f"Expected '—' for key '{key}' when items list is empty, got: {result[key]!r}"
        )


async def test_fetch_greeks_returns_dashes_when_occ_symbol_not_in_items():
    """When the API returns items but none match the requested OCC symbol,
    fetch_greeks must return all five greeks as '—' and must NOT raise."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "items": [
                {
                    "symbol": "AAPL  250117C00200000",  # different strike
                    "delta": "0.10",
                    "gamma": "0.01",
                    "theta": "-0.02",
                    "vega": "0.05",
                    "implied-volatility": "0.22",
                }
            ]
        }
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == _DASH, (
            f"Expected '—' for '{key}' when symbol not found in items, got: {result[key]!r}"
        )


async def test_fetch_greeks_returns_dashes_when_greeks_fields_missing_from_contract():
    """When the matching contract exists but lacks greeks fields (cert sandbox
    returning no greeks), fetch_greeks must return all five as '—' without raising."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "items": [
                {
                    "symbol": _OPTION_SYMBOL,
                    # No delta/gamma/theta/vega/implied-volatility fields
                    "underlying-symbol": "AAPL",
                }
            ]
        }
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == _DASH, (
            f"Expected '—' for '{key}' when greeks fields absent, got: {result[key]!r}"
        )


async def test_fetch_greeks_returns_dashes_on_http_error():
    """When httpx raises an HTTP error (e.g. 401/500), fetch_greeks must return
    all five greeks as '—' and must NOT propagate the exception."""
    from dashboard.api import fetch_greeks

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.HTTPStatusError(
        "401 Unauthorized",
        request=MagicMock(),
        response=MagicMock(status_code=401),
    )

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="bad-token", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == _DASH, (
            f"Expected '—' for '{key}' on HTTP error, got: {result[key]!r}"
        )


async def test_fetch_greeks_returns_dashes_on_network_error():
    """When httpx raises a network-level error (ConnectError), fetch_greeks must
    return all five greeks as '—' and must NOT propagate the exception."""
    from dashboard.api import fetch_greeks

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.ConnectError("connection refused")

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == _DASH, (
            f"Expected '—' for '{key}' on network error, got: {result[key]!r}"
        )


# --- Edge-case tests (Phase 4) ---


async def test_fetch_greeks_preserves_zero_string_value():
    """A greek that is legitimately "0" (string) must NOT be replaced by the
    sentinel.  This is a regression guard for the _val() fix: v not in (None,
    "", "0") was the broken form; v is not None and v != "" is correct."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "items": [
                {
                    "symbol": _OPTION_SYMBOL,
                    "delta": "0",
                    "gamma": "0",
                    "theta": "0",
                    "vega": "0",
                    "implied-volatility": "0",
                }
            ]
        }
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == "0", (
            f"Expected '0' for '{key}' when greek value is zero string, "
            f"got {result[key]!r} — zero values must be preserved, not sentinelled"
        )


async def test_fetch_greeks_preserves_integer_zero_value():
    """A greek returned as the integer 0 (not the string "0") must also be
    preserved.  The API may return numeric types; str(0) == "0", not "—"."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "items": [
                {
                    "symbol": _OPTION_SYMBOL,
                    "delta": 0,
                    "gamma": 0,
                    "theta": 0,
                    "vega": 0,
                    "implied-volatility": 0,
                }
            ]
        }
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == "0", (
            f"Expected '0' for '{key}' when greek value is integer 0, "
            f"got {result[key]!r} — integer zero must not be treated as missing"
        )


async def test_fetch_greeks_partial_greeks_present_others_dashes():
    """When only some greek fields are present on the matched contract, the
    present ones must be returned as-is and the absent ones must be '—'."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "data": {
            "items": [
                {
                    "symbol": _OPTION_SYMBOL,
                    "delta": "0.55",
                    # gamma, theta, vega, implied-volatility intentionally absent
                }
            ]
        }
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    assert result["delta"] == "0.55", (
        f"Expected delta='0.55' (present in contract), got {result['delta']!r}"
    )
    for key in ("gamma", "theta", "vega", "iv"):
        assert result[key] == _DASH, (
            f"Expected '—' for absent field '{key}', got {result[key]!r}"
        )


async def test_fetch_greeks_returns_dashes_on_request_error_base_class():
    """httpx.RequestError (the base class for all network errors, e.g. a
    ReadTimeout) must also result in all-dashes — not just ConnectError."""
    from dashboard.api import fetch_greeks

    mock_client = AsyncMock()
    mock_client.get.side_effect = httpx.TimeoutException("timed out")

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == _DASH, (
            f"Expected '—' for '{key}' on TimeoutException, got: {result[key]!r}"
        )


async def test_fetch_greeks_returns_dashes_when_data_has_no_items_key():
    """Contract assumption guard: fetch_greeks expects data["items"] (a list).
    If the real /option-chains endpoint returns {"data": [...]} directly
    (no "items" wrapper), the KeyError is caught and all-dashes are returned
    rather than raising.  This test documents the shape assumption and confirms
    graceful degradation if the assumption is wrong."""
    from dashboard.api import fetch_greeks

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    # Simulate a response where "data" is a list directly, not {"items": [...]}
    mock_resp.json.return_value = {
        "data": [
            {
                "symbol": _OPTION_SYMBOL,
                "delta": "0.42",
                "gamma": "0.03",
                "theta": "-0.05",
                "vega": "0.12",
                "implied-volatility": "0.28",
            }
        ]
    }

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp

    with patch("dashboard.api.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        result = await fetch_greeks(session_token="tok", symbol=_OPTION_SYMBOL)

    for key in ("delta", "gamma", "theta", "vega", "iv"):
        assert result[key] == _DASH, (
            f"Expected '—' for '{key}' when data has no items key, got: {result[key]!r} — "
            f"if this fails it means the parser now handles list-direct data, "
            f"which would be a behaviour change worth reviewing"
        )


# =============================================================================
# Issue #22 — FAILING tests (RED phase)
# =============================================================================

# --- Issue #22 / Behavior 1: get_chart_data OHLC arrays ---


def test_get_chart_data_returns_open_key():
    """get_chart_data must return an 'open' key in the result dict."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    data = state.get_chart_data("AAPL")
    assert "open" in data, "get_chart_data must include 'open' key for candlestick rendering"


def test_get_chart_data_returns_high_key():
    """get_chart_data must return a 'high' key in the result dict."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    data = state.get_chart_data("AAPL")
    assert "high" in data, "get_chart_data must include 'high' key for candlestick rendering"


def test_get_chart_data_returns_low_key():
    """get_chart_data must return a 'low' key in the result dict."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    data = state.get_chart_data("AAPL")
    assert "low" in data, "get_chart_data must include 'low' key for candlestick rendering"


def test_get_chart_data_ohlc_arrays_equal_length_as_close():
    """open/high/low must each be the same length as close and labels."""
    state = DashboardState()
    closes = [150.0, 151.0, 152.0]
    for i, c in enumerate(closes):
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "time": i,
            "open": c - 1.0, "high": c + 2.0, "low": c - 2.0, "close": c,
            "volume": 1_000_000,
        })
    data = state.get_chart_data("AAPL")
    n = len(data["close"])
    assert len(data["open"]) == n, (
        f"open length {len(data['open'])} must equal close length {n}"
    )
    assert len(data["high"]) == n, (
        f"high length {len(data['high'])} must equal close length {n}"
    )
    assert len(data["low"]) == n, (
        f"low length {len(data['low'])} must equal close length {n}"
    )


def test_get_chart_data_ohlc_values_match_candle_fields():
    """open/high/low arrays must reflect the per-candle OHLC values."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1,
        "open": 149.0, "high": 156.0, "low": 147.0, "close": 153.0, "volume": 1_000_000,
    })
    data = state.get_chart_data("AAPL")
    assert data["open"][0] == 149.0, f"Expected open=149.0, got {data['open'][0]}"
    assert data["high"][0] == 156.0, f"Expected high=156.0, got {data['high'][0]}"
    assert data["low"][0] == 147.0, f"Expected low=147.0, got {data['low'][0]}"


def test_get_chart_data_missing_open_falls_back_to_close():
    """A candle with missing 'open' must fall back to that candle's close value."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1,
        # 'open' deliberately absent
        "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    data = state.get_chart_data("AAPL")
    assert len(data["open"]) == 1, "open array must contain one entry"
    assert data["open"][0] == 153.0, (
        f"Missing open must fall back to close=153.0, got {data['open'][0]}"
    )


def test_get_chart_data_none_high_falls_back_to_close():
    """A candle with high=None must fall back to that candle's close value."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1,
        "open": 150.0, "high": None, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    data = state.get_chart_data("AAPL")
    assert data["high"][0] == 153.0, (
        f"None high must fall back to close=153.0, got {data['high'][0]}"
    )


def test_get_chart_data_non_finite_low_falls_back_to_close():
    """A candle with low='NaN' must fall back to close — non-finite OHLC field."""
    state = DashboardState()
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1,
        "open": 150.0, "high": 155.0, "low": "NaN", "close": 153.0, "volume": 1_000_000,
    })
    data = state.get_chart_data("AAPL")
    assert data["low"][0] == 153.0, (
        f"Non-finite low must fall back to close=153.0, got {data['low'][0]}"
    )


def test_get_chart_data_unknown_symbol_includes_ohlc_empty_arrays():
    """Unknown symbol must return empty arrays for open/high/low/close (all new keys empty)."""
    state = DashboardState()
    data = state.get_chart_data("UNKNOWN")
    assert data.get("open") == [], f"Expected empty open array, got {data.get('open')}"
    assert data.get("high") == [], f"Expected empty high array, got {data.get('high')}"
    assert data.get("low") == [], f"Expected empty low array, got {data.get('low')}"


def test_get_chart_data_never_raises_on_partial_ohlc():
    """get_chart_data must not raise even with completely garbage OHLC fields."""
    state = DashboardState()
    # Candle with all non-finite / garbage OHLC except valid close
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1,
        "open": "garbage", "high": float("inf"), "low": None, "close": 153.0,
        "volume": 1_000_000,
    })
    # Must not raise
    try:
        data = state.get_chart_data("AAPL")
    except Exception as exc:
        pytest.fail(f"get_chart_data raised unexpectedly: {exc!r}")
    # All OHLC arrays must be length 1 (falling back to close)
    assert len(data["open"]) == 1
    assert len(data["high"]) == 1
    assert len(data["low"]) == 1


# --- Issue #22 / Behavior 2: on_candle throttle ---
#
# Clock hook assumption:
#   DashboardState.on_candle reads the current time via a module-level attribute
#   `dashboard.state._now` (a callable, defaulting to `time.time`).  Tests replace
#   it via monkeypatch:
#       monkeypatch.setattr("dashboard.state._now", lambda: <fixed_float>)
#   The implementation must call `dashboard.state._now()` (not `time.time()`
#   directly) when deciding whether to broadcast.  This is the single hook the
#   implementer MUST match.


def test_on_candle_throttle_same_time_broadcasts_only_once_per_interval(monkeypatch):
    """Rapid candles with the SAME candle time broadcast at most once per throttle
    interval (~1.0 s).  Multiple ticks within the interval must produce at most
    one SSE broadcast, though all are still stored in candle history.

    Clock hook: implementation must expose dashboard.state._now (a callable,
    default time.time) so tests can deterministically control time.
    """
    import dashboard.state as state_mod

    # Verify the clock hook exists — fail clearly if not yet implemented
    assert hasattr(state_mod, "_now"), (
        "dashboard.state must expose a '_now' callable (e.g. `_now = time.time`) "
        "so the throttle logic can be deterministically tested via monkeypatching"
    )

    # Freeze the wall clock at t=1000.0 for ALL rapid candles
    monkeypatch.setattr(state_mod, "_now", lambda: 1000.0)

    state = DashboardState()
    queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(queue)

    candle_time = 1_700_000_000  # fixed candle timestamp (same-day candle)

    # Send 5 rapid ticks for the SAME candle time
    for _ in range(5):
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "time": candle_time,
            "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0,
            "volume": 1_000_000,
        })

    # All 5 must be in history
    assert len(state.candles["AAPL"]) == 5, (
        f"All 5 candles must accumulate in history; got {len(state.candles['AAPL'])}"
    )

    # Only 1 SSE broadcast should have occurred (throttled)
    broadcasts = []
    while not queue.empty():
        broadcasts.append(queue.get_nowait())
    assert len(broadcasts) == 1, (
        f"Throttle must emit at most 1 broadcast for same-candle-time rapid ticks; "
        f"got {len(broadcasts)}"
    )


def test_on_candle_throttle_new_candle_time_broadcasts_immediately(monkeypatch):
    """A candle with a NEW time (day rollover / first candle) broadcasts IMMEDIATELY
    regardless of the throttle interval."""
    import dashboard.state as state_mod

    assert hasattr(state_mod, "_now"), (
        "dashboard.state must expose a '_now' callable for deterministic throttle testing"
    )

    # Wall clock starts at t=1000.0; previous broadcast recorded at 999.5 (just now)
    call_count = 0
    times = [999.9, 1000.0]  # second call still within 1s window

    def mock_now():
        nonlocal call_count
        t = times[min(call_count, len(times) - 1)]
        call_count += 1
        return t

    monkeypatch.setattr(state_mod, "_now", mock_now)

    state = DashboardState()
    queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(queue)

    # First candle at time=1 (establishes last broadcast time)
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1_700_000_000,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    # Drain queue
    while not queue.empty():
        queue.get_nowait()

    # Now send a candle with a DIFFERENT (newer) time — must broadcast immediately
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": 1_700_086_400,  # next day
        "open": 154.0, "high": 159.0, "low": 152.0, "close": 157.0, "volume": 1_200_000,
    })

    assert not queue.empty(), (
        "A new-day (new candle time) candle must broadcast immediately "
        "regardless of the throttle interval"
    )


def test_on_candle_throttle_accumulates_all_history_regardless_of_throttle(monkeypatch):
    """Even when throttled, ALL candles must be appended to state.candles history."""
    import dashboard.state as state_mod

    assert hasattr(state_mod, "_now"), (
        "dashboard.state must expose a '_now' callable for deterministic throttle testing"
    )

    monkeypatch.setattr(state_mod, "_now", lambda: 5000.0)

    state = DashboardState()
    candle_time = 1_700_000_000

    for i in range(10):
        state.on_candle({
            "eventSymbol": "AAPL{=d}",
            "time": candle_time,
            "open": 150.0, "high": 155.0, "low": 148.0, "close": float(150 + i),
            "volume": 1_000_000,
        })

    assert len(state.candles["AAPL"]) == 10, (
        f"All 10 candles must be in history even when broadcast is throttled; "
        f"got {len(state.candles['AAPL'])}"
    )


def test_on_candle_throttle_after_interval_broadcasts_again(monkeypatch):
    """After the throttle interval has passed, the next candle with the same time
    should broadcast again."""
    import dashboard.state as state_mod

    assert hasattr(state_mod, "_now"), (
        "dashboard.state must expose a '_now' callable for deterministic throttle testing"
    )

    tick = [1000.0]

    def mock_now():
        return tick[0]

    monkeypatch.setattr(state_mod, "_now", mock_now)

    state = DashboardState()
    queue: asyncio.Queue = asyncio.Queue()
    state.subscribers.append(queue)

    candle_time = 1_700_000_000

    # First broadcast at t=1000.0
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": candle_time,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    while not queue.empty():
        queue.get_nowait()

    # Advance clock by more than 1.0s to exceed the throttle interval
    tick[0] = 1001.5

    # Same candle time but throttle interval elapsed — should broadcast again
    state.on_candle({
        "eventSymbol": "AAPL{=d}",
        "time": candle_time,
        "open": 150.0, "high": 156.0, "low": 148.0, "close": 154.0, "volume": 2_000_000,
    })

    assert not queue.empty(), (
        "After the throttle interval has passed (1.5s > 1.0s), "
        "on_candle must broadcast again for the same candle time"
    )


# --- Issue #22 / Behavior 5: on_quote persists live mark (blip root-cause fix) ---


def test_on_quote_persists_mark_into_positions_current_price():
    """on_quote must call update_quote so state.positions current_price is kept live.
    After receiving a quote, positions[0]['current_price'] must be non-None."""
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
            "pl": None,
        }
    ]
    event = PriceEvent(symbol="AAPL", last=155.0, bid=154.5, ask=155.5, timestamp=1.0)
    state.on_quote(event)

    assert state.positions[0]["current_price"] is not None, (
        "on_quote must persist the mark into state.positions via update_quote; "
        "current_price must not remain None after receiving a quote"
    )


def test_on_quote_persists_correct_mark_value_into_positions():
    """on_quote must persist the mid-price mark (bid+ask)/2 via update_quote.
    The positions entry's current_price must equal the computed mark."""
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
            "pl": None,
        }
    ]
    # mark = (154.0 + 156.0) / 2 = 155.0
    event = PriceEvent(symbol="AAPL", last=155.0, bid=154.0, ask=156.0, timestamp=1.0)
    state.on_quote(event)

    assert state.positions[0]["current_price"] == pytest.approx(155.0), (
        f"on_quote must persist mark=(bid+ask)/2=155.0 into positions; "
        f"got {state.positions[0]['current_price']}"
    )


def test_on_quote_persists_pl_into_positions_for_equity():
    """on_quote must recompute and store pl in state.positions for an equity position."""
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
            "pl": None,
        }
    ]
    event = PriceEvent(symbol="AAPL", last=155.0, bid=154.0, ask=156.0, timestamp=1.0)
    state.on_quote(event)

    # P&L = (155.0 - 150.0) * 10 = 50.0
    assert state.positions[0]["pl"] == pytest.approx(50.0), (
        f"on_quote must compute pl=(mark-avg_cost)*qty=50.0; "
        f"got {state.positions[0]['pl']}"
    )


def test_on_quote_persists_pl_for_option_with_100_multiplier():
    """on_quote must apply the 100x multiplier for Equity Option positions."""
    state = DashboardState()
    state.positions = [
        {
            "symbol": "AAPL  240119C00150000",
            "instrument_type": "Equity Option",
            "quantity": 2,
            "avg_cost": "3.50",
            "current_price": None,
            "pl": None,
        }
    ]
    # mark = (4.8 + 5.2) / 2 = 5.0
    event = PriceEvent(
        symbol="AAPL  240119C00150000", last=5.0, bid=4.8, ask=5.2, timestamp=1.0
    )
    state.on_quote(event)

    # P&L = (5.0 - 3.50) * 2 * 100 = 300.0
    assert state.positions[0]["pl"] == pytest.approx(300.0), (
        f"on_quote must use 100x multiplier for options; "
        f"got {state.positions[0]['pl']}"
    )
