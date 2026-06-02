import httpx
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(scope="module")
def client():
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


# --- DELETE /api/orders/{order_id} ---

def test_delete_order_returns_200_on_success(client):
    with patch("dashboard.app.cancel_order", new_callable=AsyncMock):
        response = client.delete("/api/orders/123")
    assert response.status_code == 200


def test_delete_order_removes_order_from_state_optimistically(client):
    from dashboard.app import app
    app.state.dashboard.orders = [
        {"id": 123, "symbol": "AAPL", "action": "Buy", "order_type": "Limit",
         "quantity": 1, "price": "150.00", "status": "Live", "time": "10:00:00"},
    ]
    with patch("dashboard.app.cancel_order", new_callable=AsyncMock):
        client.delete("/api/orders/123")
    assert not any(str(o["id"]) == "123" for o in app.state.dashboard.orders)


def test_delete_order_returns_error_when_api_rejects(client):
    mock_api_response = MagicMock()
    mock_api_response.status_code = 422
    mock_api_response.text = "Order cannot be cancelled"
    with patch("dashboard.app.cancel_order", new_callable=AsyncMock) as mock_cancel:
        mock_cancel.side_effect = httpx.HTTPStatusError(
            "422",
            request=MagicMock(),
            response=mock_api_response,
        )
        response = client.delete("/api/orders/123")
    assert response.status_code >= 400


# --- Cancel button visibility in orders table ---

def test_cancel_button_shown_for_received_order(client):
    from dashboard.app import app
    app.state.dashboard.orders = [
        {"id": 111, "symbol": "AAPL", "action": "Buy", "order_type": "Limit",
         "quantity": 1, "price": "150.00", "status": "Received", "time": "10:00:00"},
    ]
    response = client.get("/")
    app.state.dashboard.orders = []
    assert 'data-order-id="111"' in response.text


def test_cancel_button_shown_for_routed_order(client):
    from dashboard.app import app
    app.state.dashboard.orders = [
        {"id": 222, "symbol": "AAPL", "action": "Buy", "order_type": "Limit",
         "quantity": 1, "price": "150.00", "status": "Routed", "time": "10:00:00"},
    ]
    response = client.get("/")
    app.state.dashboard.orders = []
    assert 'data-order-id="222"' in response.text


def test_cancel_button_shown_for_live_order(client):
    from dashboard.app import app
    app.state.dashboard.orders = [
        {"id": 333, "symbol": "AAPL", "action": "Buy", "order_type": "Limit",
         "quantity": 1, "price": "150.00", "status": "Live", "time": "10:00:00"},
    ]
    response = client.get("/")
    app.state.dashboard.orders = []
    assert 'data-order-id="333"' in response.text


def test_cancel_button_absent_for_filled_order(client):
    from dashboard.app import app
    app.state.dashboard.orders = [
        {"id": 444, "symbol": "AAPL", "action": "Buy", "order_type": "Limit",
         "quantity": 1, "price": "150.00", "status": "Filled", "time": "10:00:00"},
    ]
    response = client.get("/")
    app.state.dashboard.orders = []
    assert 'data-order-id="444"' in response.text          # row still rendered
    assert 'class="cancel-btn" data-order-id="444"' not in response.text  # button absent


def test_cancel_button_absent_for_cancelled_order(client):
    from dashboard.app import app
    app.state.dashboard.orders = [
        {"id": 555, "symbol": "AAPL", "action": "Buy", "order_type": "Limit",
         "quantity": 1, "price": "150.00", "status": "Cancelled", "time": "10:00:00"},
    ]
    response = client.get("/")
    app.state.dashboard.orders = []
    assert 'data-order-id="555"' in response.text          # row still rendered
    assert 'class="cancel-btn" data-order-id="555"' not in response.text  # button absent


# --- POST /api/orders ---

def test_post_api_orders_returns_200_and_order_id(client):
    with patch("dashboard.app.place_order", new_callable=AsyncMock) as mock_place:
        mock_place.return_value = "ORD-42"
        response = client.post(
            "/api/orders",
            json={
                "symbol": "AAPL",
                "instrument_type": "Equity",
                "action": "Buy to Open",
                "quantity": 2,
                "limit_price": 155.50,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["order_id"] == "ORD-42"


def test_post_api_orders_returns_error_when_api_rejects(client):
    mock_api_response = MagicMock()
    mock_api_response.status_code = 422
    mock_api_response.text = "Order rejected by exchange"
    with patch("dashboard.app.place_order", new_callable=AsyncMock) as mock_place:
        mock_place.side_effect = httpx.HTTPStatusError(
            "422",
            request=MagicMock(),
            response=mock_api_response,
        )
        response = client.post(
            "/api/orders",
            json={
                "symbol": "AAPL",
                "instrument_type": "Equity",
                "action": "Buy to Open",
                "quantity": 1,
                "limit_price": 150.0,
            },
        )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_post_api_orders_response_contains_order_id_key(client):
    """Success response must include the documented 'order_id' key."""
    with patch("dashboard.app.place_order", new_callable=AsyncMock) as mock_place:
        mock_place.return_value = "ORD-77"
        response = client.post(
            "/api/orders",
            json={
                "symbol": "TSLA",
                "instrument_type": "Equity",
                "action": "Buy to Open",
                "quantity": 10,
                "limit_price": 200.0,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "order_id" in data
    assert data["order_id"] == "ORD-77"


def test_post_api_orders_coerces_string_quantity_to_int(client):
    """Form sends fields as strings; route must cast quantity to int for place_order."""
    with patch("dashboard.app.place_order", new_callable=AsyncMock) as mock_place:
        mock_place.return_value = "ORD-88"
        response = client.post(
            "/api/orders",
            json={
                "symbol": "AAPL",
                "instrument_type": "Equity",
                "action": "Buy to Open",
                "quantity": "3",
                "limit_price": "155.00",
            },
        )
    assert response.status_code == 200
    _, kwargs = mock_place.call_args
    assert kwargs["quantity"] == 3
    assert isinstance(kwargs["quantity"], int)


def test_post_api_orders_returns_400_when_body_missing_required_field(client):
    """Missing fields must not crash the server (no 500). Must return a 4xx with error."""
    response = client.post(
        "/api/orders",
        json={"symbol": "AAPL"},
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_post_api_orders_returns_400_on_empty_body(client):
    """An empty body must not crash the server. Must return a 4xx with error."""
    response = client.post(
        "/api/orders",
        json={},
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


# --- Input validation allow-list tests ---

def test_post_api_orders_rejects_invalid_action(client):
    """action not in allow-list must return 400."""
    response = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "action": "Buy to Close",
            "quantity": 1,
            "limit_price": 150.0,
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_post_api_orders_rejects_invalid_instrument_type(client):
    """instrument_type not in allow-list must return 400."""
    response = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL",
            "instrument_type": "Future",
            "action": "Buy to Open",
            "quantity": 1,
            "limit_price": 150.0,
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_post_api_orders_rejects_zero_quantity(client):
    """quantity of 0 must return 400."""
    response = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "action": "Buy to Open",
            "quantity": 0,
            "limit_price": 150.0,
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_post_api_orders_rejects_negative_quantity(client):
    """negative quantity must return 400."""
    response = client.post(
        "/api/orders",
        json={
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "action": "Buy to Open",
            "quantity": -5,
            "limit_price": 150.0,
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_post_api_orders_rejects_missing_symbol(client):
    """A body missing 'symbol' must return 400 (not 500)."""
    response = client.post(
        "/api/orders",
        json={
            "instrument_type": "Equity",
            "action": "Buy to Open",
            "quantity": 1,
            "limit_price": 150.0,
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_post_api_orders_rejects_blank_symbol(client):
    """A blank/whitespace 'symbol' must return 400."""
    response = client.post(
        "/api/orders",
        json={
            "symbol": "   ",
            "instrument_type": "Equity",
            "action": "Buy to Open",
            "quantity": 1,
            "limit_price": 150.0,
        },
    )
    assert response.status_code == 400
    data = response.json()
    assert "error" in data


def test_post_api_orders_returns_502_on_network_error(client):
    """httpx.RequestError from place_order must return 502 (not 500)."""
    with patch("dashboard.app.place_order", new_callable=AsyncMock) as mock_place:
        mock_place.side_effect = httpx.RequestError("connection refused")
        response = client.post(
            "/api/orders",
            json={
                "symbol": "AAPL",
                "instrument_type": "Equity",
                "action": "Buy to Open",
                "quantity": 1,
                "limit_price": 150.0,
            },
        )
    assert response.status_code == 502
    data = response.json()
    assert "error" in data
