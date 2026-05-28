from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.auth import Auth


def _mock_config():
    cfg = MagicMock()
    cfg.username = "testuser"
    cfg.password = "testpass"
    cfg.execution.account_number = "5WX78966"
    return cfg


@pytest.fixture(scope="module")
def client():
    mock_config = _mock_config()
    mock_auth = Auth(session_token="test-token", remember_token="test-remember")
    mock_balance = AsyncMock(return_value={
        "account_number": "5WX78966",
        "net_liquidating_value": "10000.00",
        "buying_power": "5000.00",
    })

    with patch("dashboard.app.load_config", return_value=mock_config), \
         patch("dashboard.app.login", new=AsyncMock(return_value=mock_auth)), \
         patch("dashboard.app.fetch_balance", new=mock_balance), \
         patch("dashboard.app.fetch_positions", new=AsyncMock(return_value=[])), \
         patch("dashboard.app.fetch_orders", new=AsyncMock(return_value=[])):
        from dashboard.app import app
        with TestClient(app) as c:
            yield c


def test_root_returns_200_html(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_html_links_to_tokens_css(client):
    response = client.get("/")
    assert "/static/css/tokens.css" in response.text


def test_html_links_to_layout_css(client):
    response = client.get("/")
    assert "/static/css/layout.css" in response.text


def test_html_links_to_components_css(client):
    response = client.get("/")
    assert "/static/css/components.css" in response.text


def test_html_has_no_inline_styles(client):
    response = client.get("/")
    assert 'style="' not in response.text


def test_static_tokens_css_served(client):
    response = client.get("/static/css/tokens.css")
    assert response.status_code == 200


def test_static_layout_css_served(client):
    response = client.get("/static/css/layout.css")
    assert response.status_code == 200


def test_static_components_css_served(client):
    response = client.get("/static/css/components.css")
    assert response.status_code == 200


def test_app_has_config_loaded(client):
    from dashboard.app import app
    assert app.state.config is not None
    assert app.state.config.execution.account_number == "5WX78966"
