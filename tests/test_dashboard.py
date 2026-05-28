from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dashboard.state import DashboardState
from dashboard.api import fetch_balance, fetch_positions


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
