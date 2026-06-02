from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from dashboard.state import DashboardState
from dashboard.api import fetch_balance, fetch_positions, fetch_quote_token
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
