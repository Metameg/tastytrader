import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.auth import Auth
from src.config import ExecutionConfig
from src.executor import Executor
from src.models import Direction, PriceEvent, TradeSignal


def _cfg() -> ExecutionConfig:
    return ExecutionConfig(
        account_number="TEST123",
        call_symbol="AAPL  240119C00150000",
        put_symbol="AAPL  240119P00150000",
        quantity=1,
    )


def _auth() -> Auth:
    return Auth(session_token="sess-tok", remember_token="rem-tok")


def _signal(direction: Direction, bid: float = 149.90, ask: float = 150.10) -> TradeSignal:
    return TradeSignal(
        direction=direction,
        price_event=PriceEvent(
            symbol="AAPL", last=150.0, bid=bid, ask=ask, timestamp=0.0
        ),
    )


async def _make_executor() -> tuple[Executor, asyncio.Queue]:
    q: asyncio.Queue = asyncio.Queue()
    ex = Executor(config=_cfg(), auth=_auth(), signal_queue=q)
    return ex, q


async def test_bullish_places_call_order():
    ex, _ = await _make_executor()
    signal = _signal(Direction.BULLISH)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "ORD001"}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.executor.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ex._place_order(signal)

    args, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["legs"][0]["symbol"] == "AAPL  240119C00150000"
    assert body["legs"][0]["action"] == "Buy to Open"


async def test_bearish_places_put_order():
    ex, _ = await _make_executor()
    signal = _signal(Direction.BEARISH)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "ORD002"}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.executor.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ex._place_order(signal)

    args, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["legs"][0]["symbol"] == "AAPL  240119P00150000"


async def test_limit_price_is_bid_ask_midpoint():
    ex, _ = await _make_executor()
    signal = _signal(Direction.BULLISH, bid=149.90, ask=150.10)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "ORD003"}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.executor.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ex._place_order(signal)

    args, kwargs = mock_client.post.call_args
    body = kwargs["json"]
    assert body["price"] == "150.00"


async def test_auth_header_sent():
    ex, _ = await _make_executor()
    signal = _signal(Direction.BULLISH)

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"id": "ORD004"}}

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp

    with patch("src.executor.httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__.return_value = mock_client
        await ex._place_order(signal)

    args, kwargs = mock_client.post.call_args
    assert kwargs["headers"]["Authorization"] == "sess-tok"
