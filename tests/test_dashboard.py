from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from dashboard.state import DashboardState
from dashboard.api import fetch_balance, fetch_positions, fetch_orders


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
            "buying-power": "5000.00",
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


# --- fetch_orders ---

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
