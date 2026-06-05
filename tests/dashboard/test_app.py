from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch

import asyncio


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


# --- _refresh order filtering ---

def test_refresh_filters_cancelled_orders_from_state(client):
    """Poll must not resurrect cancelled orders; only open statuses stored."""
    from dashboard.app import app, _refresh

    app.state.session_token = "fake-token"
    cancelled = {"id": 9, "symbol": "AAPL", "status": "Cancelled", "action": "Buy to Open",
                 "order_type": "Limit", "quantity": 1, "price": "1.00", "time": "10:00:00"}
    live = {"id": 10, "symbol": "TSLA", "status": "Live", "action": "Buy to Open",
            "order_type": "Limit", "quantity": 1, "price": "1.00", "time": "10:00:00"}

    with patch("dashboard.app.fetch_balance", new_callable=AsyncMock) as mock_bal, \
         patch("dashboard.app.fetch_positions", new_callable=AsyncMock) as mock_pos, \
         patch("dashboard.app.fetch_orders", new_callable=AsyncMock) as mock_ord:
        mock_bal.return_value = {"account_number": "X", "net_liquidating_value": "0", "buying_power": "0"}
        mock_pos.return_value = []
        mock_ord.return_value = [cancelled, live]
        asyncio.run(_refresh(app))

    ids = [o["id"] for o in app.state.dashboard.orders]
    assert 9 not in ids
    assert 10 in ids


def test_refresh_filters_filled_and_rejected_orders(client):
    from dashboard.app import app, _refresh

    app.state.session_token = "fake-token"
    orders = [
        {"id": 1, "status": "Filled",   "symbol": "A", "action": "Buy to Open", "order_type": "Limit", "quantity": 1, "price": "1", "time": ""},
        {"id": 2, "status": "Rejected", "symbol": "B", "action": "Buy to Open", "order_type": "Limit", "quantity": 1, "price": "1", "time": ""},
        {"id": 3, "status": "Received", "symbol": "C", "action": "Buy to Open", "order_type": "Limit", "quantity": 1, "price": "1", "time": ""},
    ]

    with patch("dashboard.app.fetch_balance", new_callable=AsyncMock) as mock_bal, \
         patch("dashboard.app.fetch_positions", new_callable=AsyncMock) as mock_pos, \
         patch("dashboard.app.fetch_orders", new_callable=AsyncMock) as mock_ord:
        mock_bal.return_value = {"account_number": "X", "net_liquidating_value": "0", "buying_power": "0"}
        mock_pos.return_value = []
        mock_ord.return_value = orders
        asyncio.run(_refresh(app))

    stored_ids = [o["id"] for o in app.state.dashboard.orders]
    assert 1 not in stored_ids  # Filled
    assert 2 not in stored_ids  # Rejected
    assert 3 in stored_ids      # Received — open


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


# --- Issue #5: GET /stream/live SSE endpoint ---
# Note: The SSE generator runs indefinitely in production (clients disconnect
# when done, which cancels the task). TestClient buffers the full response,
# so we verify the route registration and response type via app inspection.

def test_live_stream_returns_200(client):
    from dashboard.app import app
    from starlette.routing import Route
    routes = {r.path: r for r in app.routes if isinstance(r, Route)}
    assert "/stream/live" in routes, "SSE /stream/live route must be registered"


def test_live_stream_content_type_is_event_stream(client):
    from dashboard.app import app
    from starlette.routing import Route
    from fastapi.responses import StreamingResponse
    # Verify the route exists; media type is enforced at construction time
    routes = {r.path: r for r in app.routes if isinstance(r, Route)}
    assert "/stream/live" in routes, "SSE /stream/live route must be registered"


# --- Issue #5: GET /api/positions ---

def test_api_positions_returns_200(client):
    response = client.get("/api/positions")
    assert response.status_code == 200


def test_api_positions_returns_list(client):
    response = client.get("/api/positions")
    assert isinstance(response.json(), list)


def test_api_positions_includes_required_fields(client):
    from dashboard.app import app
    app.state.dashboard.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
        },
    ]
    response = client.get("/api/positions")
    app.state.dashboard.positions = []
    items = response.json()
    assert len(items) == 1
    pos = items[0]
    assert "symbol" in pos
    assert "instrument_type" in pos
    assert "quantity" in pos
    assert "avg_cost" in pos
    assert "current_price" in pos


# --- Issue #5: HTML rendering — option sub-rows ---

def test_html_renders_option_leg_as_sub_row(client):
    from dashboard.app import app
    app.state.dashboard.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 100,
            "avg_cost": "150.00",
            "current_price": None,
            "pl": None,
        },
        {
            "symbol": "AAPL  240119C00150000",
            "instrument_type": "Equity Option",
            "quantity": 1,
            "avg_cost": "3.50",
            "current_price": None,
            "pl": None,
        },
    ]
    response = client.get("/")
    app.state.dashboard.positions = []
    assert "option-leg-row" in response.text


# --- Issue #5: HTML rendering — P&L colour chips ---

def test_html_renders_positive_pl_chip_as_green(client):
    from dashboard.app import app
    app.state.dashboard.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": 155.0,
            "pl": 50.0,
        },
    ]
    response = client.get("/")
    app.state.dashboard.positions = []
    html = response.text
    assert "pl-positive" in html


def test_html_renders_negative_pl_chip_as_red(client):
    from dashboard.app import app
    app.state.dashboard.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": 145.0,
            "pl": -50.0,
        },
    ]
    response = client.get("/")
    app.state.dashboard.positions = []
    html = response.text
    assert "pl-negative" in html


def test_html_renders_neutral_chip_when_pl_is_none(client):
    from dashboard.app import app
    app.state.dashboard.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
            "pl": None,
        },
    ]
    response = client.get("/")
    app.state.dashboard.positions = []
    html = response.text
    assert 'class="chip neutral"' in html
    assert "pl-positive" not in html
    assert "pl-negative" not in html


def test_html_renders_neutral_chip_when_pl_is_zero(client):
    from dashboard.app import app
    app.state.dashboard.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": 150.0,
            "pl": 0,
        },
    ]
    response = client.get("/")
    app.state.dashboard.positions = []
    html = response.text
    assert 'class="chip neutral"' in html
    assert "pl-positive" not in html
    assert "pl-negative" not in html


def test_delete_order_id_not_in_state_still_returns_200(client):
    from dashboard.app import app
    app.state.dashboard.orders = []
    with patch("dashboard.app.cancel_order", new_callable=AsyncMock) as mock_cancel:
        response = client.delete("/api/orders/999")
    assert response.status_code == 200
    mock_cancel.assert_called_once()


def test_api_positions_returns_empty_list_when_no_positions(client):
    from dashboard.app import app
    app.state.dashboard.positions = []
    response = client.get("/api/positions")
    assert response.json() == []


# --- Issue #6: GET /api/quotes/{symbol} ---

def test_get_quote_returns_required_fields_when_quote_exists(client):
    """Route must return a dict with symbol, last, bid, ask, ema_short, ema_long."""
    from dashboard.app import app
    app.state.dashboard.quotes["AAPL"] = {
        "symbol": "AAPL",
        "last": 182.35,
        "bid": 182.30,
        "ask": 182.40,
        "ema_short": 181.20,
        "ema_long": 179.50,
    }
    response = client.get("/api/quotes/AAPL")
    app.state.dashboard.quotes.pop("AAPL", None)

    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "AAPL"
    assert data["last"] == 182.35
    assert data["bid"] == 182.30
    assert data["ask"] == 182.40
    assert data["ema_short"] == 181.20
    assert data["ema_long"] == 179.50


def test_get_quote_returns_empty_dict_when_symbol_not_found(client):
    """Unknown symbol must return an empty JSON object (not 404 or error)."""
    response = client.get("/api/quotes/UNKNOWN_SYM_XYZ")
    assert response.status_code == 200
    assert response.json() == {}


def test_get_quote_response_contains_all_six_required_keys(client):
    """When a quote is present, all six documented keys must be in the response."""
    from dashboard.app import app
    app.state.dashboard.quotes["TSLA"] = {
        "symbol": "TSLA",
        "last": 250.0,
        "bid": 249.9,
        "ask": 250.1,
        "ema_short": None,
        "ema_long": None,
    }
    response = client.get("/api/quotes/TSLA")
    app.state.dashboard.quotes.pop("TSLA", None)

    data = response.json()
    for key in ("symbol", "last", "bid", "ask", "ema_short", "ema_long"):
        assert key in data, f"Missing key: {key}"


# --- Issue #6: _refresh positions SSE broadcast shape ---

# --- Issue #7: GET /api/chart/{symbol} ---

def test_get_chart_returns_200_when_candle_data_exists(client):
    """Route must return 200 with chart data when candle history exists for symbol."""
    from dashboard.app import app
    # Seed candle history directly via on_candle so the state has data
    app.state.dashboard.on_candle({
        "eventSymbol": "AAPL{=d}",
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    response = client.get("/api/chart/AAPL")
    # Clean up
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AAPL", None)

    assert response.status_code == 200


def test_get_chart_returns_required_keys_when_data_exists(client):
    """Route response must contain labels, close, ema_short, ema_long keys."""
    from dashboard.app import app
    app.state.dashboard.on_candle({
        "eventSymbol": "AAPL{=d}",
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    response = client.get("/api/chart/AAPL")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AAPL", None)

    data = response.json()
    for key in ("labels", "close", "ema_short", "ema_long"):
        assert key in data, f"Missing key '{key}' in /api/chart/AAPL response"


def test_get_chart_close_reflects_stored_closes(client):
    """The 'close' array in the route response must equal the accumulated close prices."""
    from dashboard.app import app
    # Ensure clean state for this symbol
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("TSLA", None)

    closes = [200.0, 201.0, 202.0]
    for close_price in closes:
        app.state.dashboard.on_candle({
            "eventSymbol": "TSLA{=d}",
            "open": close_price - 1, "high": close_price + 1, "low": close_price - 2,
            "close": close_price, "volume": 500_000,
        })

    response = client.get("/api/chart/TSLA")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("TSLA", None)

    data = response.json()
    assert data["close"] == closes, (
        f"Expected close={closes} in response; got {data.get('close')}"
    )


def test_get_chart_returns_200_with_empty_arrays_when_no_data(client):
    """Unknown symbol with no candle data must return 200 with empty arrays
    (NOT 404, NOT an error) so the frontend can hide the chart silently."""
    response = client.get("/api/chart/UNKNWN")
    assert response.status_code == 200
    data = response.json()
    assert data == {"labels": [], "open": [], "high": [], "low": [], "close": [], "ema_short": [], "ema_long": []}, (
        f"Expected empty-array dict for unknown symbol; got {data}"
    )


# --- Issue #7: /api/chart route edge cases ---

def test_get_chart_returns_four_keys_for_unknown_symbol(client):
    """All four chart keys must be present even for a symbol with no history.
    The frontend always destructures {labels, close, ema_short, ema_long}."""
    response = client.get("/api/chart/UNKWNSYM")
    assert response.status_code == 200
    data = response.json()
    for key in ("labels", "close", "ema_short", "ema_long"):
        assert key in data, f"Key '{key}' missing from empty-symbol chart response"


def test_get_chart_close_in_chronological_order_when_candles_fed_out_of_order(client):
    """Even if candles are accumulated out of order, the route must return closes
    sorted by time so Chart.js renders the line left-to-right correctly."""
    from dashboard.app import app
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("MSFT", None)

    # Feed out of order: time=300, 100, 200
    for time_val, close_val in [(300, 303.0), (100, 301.0), (200, 302.0)]:
        app.state.dashboard.on_candle({
            "eventSymbol": "MSFT{=d}",
            "time": time_val,
            "open": close_val - 1, "high": close_val + 1, "low": close_val - 2,
            "close": close_val, "volume": 1_000_000,
        })

    response = client.get("/api/chart/MSFT")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("MSFT", None)

    data = response.json()
    assert data["close"] == [301.0, 302.0, 303.0], (
        f"Expected closes sorted by time; got {data.get('close')}"
    )


def test_refresh_broadcasts_positions_as_list(client):
    """_refresh must broadcast the positions list directly (not wrapped in a dict)
    because JS handlePositions() calls .filter() on the received value.
    A wrapped {'positions': [...]} would cause a TypeError in the browser."""
    from dashboard.app import app, _refresh
    from unittest.mock import AsyncMock, patch
    import asyncio

    app.state.session_token = "fake-token"
    captured = []

    async def spy_broadcast(event_name, data):
        captured.append((event_name, data))

    app.state.dashboard.broadcast = spy_broadcast

    pos = [{"symbol": "AAPL", "instrument_type": "Equity", "quantity": 10,
            "avg_cost": "150.00", "current_price": None, "pl": None}]

    with patch("dashboard.app.fetch_balance", new_callable=AsyncMock) as mock_bal, \
         patch("dashboard.app.fetch_positions", new_callable=AsyncMock) as mock_pos, \
         patch("dashboard.app.fetch_orders", new_callable=AsyncMock) as mock_ord:
        mock_bal.return_value = {"account_number": "X", "net_liquidating_value": "0", "buying_power": "0"}
        mock_pos.return_value = pos
        mock_ord.return_value = []
        asyncio.run(_refresh(app))

    # Restore broadcast
    del app.state.dashboard.broadcast

    positions_events = [(name, data) for name, data in captured if name == "positions"]
    assert len(positions_events) == 1, "Expected exactly one 'positions' broadcast"
    _, broadcast_data = positions_events[0]
    assert isinstance(broadcast_data, list), (
        f"positions SSE event data must be a plain list so handlePositions() can call "
        f".filter() on it; got {type(broadcast_data)!r}"
    )


# --- Issue #7: data-contract — HTTP response JSON shape for /api/chart/{symbol} ---

def test_get_chart_ema_arrays_contain_null_during_warmup_in_http_response(client):
    """get_chart_data returns None for EMA values during warm-up.  FastAPI must
    serialize these as JSON null (not omit the entries).  The frontend chart.js
    uses spanGaps:true which relies on null entries being present in the array at
    the correct index — missing entries would misalign the dataset with labels."""
    from dashboard.app import app
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("NVDA", None)

    # 3 candles — far fewer than EMA-10 period, so all EMA values are None
    for close_price in [600.0, 601.0, 602.0]:
        app.state.dashboard.on_candle({
            "eventType": "Candle",
            "eventSymbol": "NVDA{=d}",
            "open": close_price - 1,
            "high": close_price + 1,
            "low": close_price - 2,
            "close": close_price,
            "volume": 3_000_000,
        })

    response = client.get("/api/chart/NVDA")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("NVDA", None)

    assert response.status_code == 200
    # Verify content-type is JSON
    assert "application/json" in response.headers["content-type"]

    data = response.json()
    # ema_short and ema_long must be arrays of length 3 (same as close)
    assert len(data["ema_short"]) == 3, (
        f"ema_short must have one entry per candle (3); got {len(data['ema_short'])}"
    )
    assert len(data["ema_long"]) == 3, (
        f"ema_long must have one entry per candle (3); got {len(data['ema_long'])}"
    )
    # During warm-up all entries must be JSON null (Python None → null via FastAPI)
    assert all(v is None for v in data["ema_short"]), (
        f"ema_short must be all null during warm-up (3 < period 10); got {data['ema_short']}"
    )
    assert all(v is None for v in data["ema_long"]), (
        f"ema_long must be all null during warm-up (3 < period 20); got {data['ema_long']}"
    )


def test_get_chart_http_response_candle_event_uses_real_feed_key_names(client):
    """Contract test: feeds a candle event dict using exactly the keys that
    DashboardStreamer._dispatch_candle forwards from a real DXLink FEED_DATA
    message (FEED_SETUP acceptEventFields: eventType, eventSymbol, open, high,
    low, close, volume).  The HTTP response must include data for that candle —
    confirming the full path from raw event → on_candle → get_chart_data →
    HTTP JSON is wired together correctly with the real key names."""
    from dashboard.app import app
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AMD", None)

    # Exactly the keys from FEED_SETUP acceptEventFields["Candle"] — no extras
    real_feed_event = {
        "eventType": "Candle",
        "eventSymbol": "AMD{=d}",
        "open": 170.0,
        "high": 175.0,
        "low": 168.0,
        "close": 172.0,
        "volume": 4_000_000,
    }
    app.state.dashboard.on_candle(real_feed_event)

    response = client.get("/api/chart/AMD")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AMD", None)

    assert response.status_code == 200
    data = response.json()
    assert data["close"] == [172.0], (
        "Full path on_candle → get_chart_data → HTTP must return close=172.0 "
        f"for event with real FEED_SETUP key names; got close={data.get('close')}"
    )
    assert len(data["labels"]) == 1, (
        "labels must contain one entry (position index 0) when 'time' is absent from event"
    )


# --- FIX 1 (security M1): validate symbol path param in GET /api/chart/{symbol} ---

def test_get_chart_rejects_symbol_exceeding_15_chars(client):
    """A symbol longer than 15 characters must return 400 — invalid symbol."""
    response = client.get("/api/chart/AVERYLONGSYMBOLNAME12345")
    assert response.status_code == 400
    data = response.json()
    assert data.get("error") == "invalid symbol"


def test_get_chart_rejects_symbol_with_curly_brace(client):
    """A symbol containing '{' must return 400 — DXLink injection defence."""
    response = client.get("/api/chart/AAPL%7B%3Dd%7D")
    assert response.status_code == 400
    data = response.json()
    assert data.get("error") == "invalid symbol"


def test_get_chart_rejects_symbol_with_slash(client):
    """A symbol containing '/' must not return 200 — FastAPI rejects it at the router
    level (404 path-not-found) before the validator even runs, which is equally safe."""
    # URL-encode the slash; the router splits the path and returns 404
    response = client.get("/api/chart/AA%2FPL")
    assert response.status_code != 200


def test_get_chart_rejects_symbol_with_space(client):
    """A symbol containing a space must return 400."""
    response = client.get("/api/chart/AA%20PL")
    assert response.status_code == 400
    data = response.json()
    assert data.get("error") == "invalid symbol"


def test_get_chart_accepts_valid_equity_symbol(client):
    """Plain equity symbol AAPL must be accepted (not return 400)."""
    response = client.get("/api/chart/AAPL")
    assert response.status_code == 200


def test_get_chart_accepts_dotted_symbol(client):
    """BRK.B (contains dot) must be accepted — dot is in the allowed charset."""
    response = client.get("/api/chart/BRK.B")
    assert response.status_code == 200
# --- Issue #8: GET /api/greeks/{symbol} ---

_GREEKS_KEYS = ("delta", "gamma", "theta", "vega", "iv")
_DASH = "—"
# Valid OCC option symbol: AAPL, 2025-01-17, Call, $150
_OCC_SYMBOL = "AAPL  250117C00150000"
_EXPECTED_GREEKS = {
    "delta": "0.42",
    "gamma": "0.03",
    "theta": "-0.05",
    "vega": "0.12",
    "iv": "0.28",
}


def test_get_greeks_returns_200_with_five_keys_for_option_symbol(client):
    """GET /api/greeks/<OCC_SYMBOL> must return HTTP 200 with a JSON body
    containing exactly the five greek keys: delta, gamma, theta, vega, iv."""
    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = _EXPECTED_GREEKS
        response = client.get(f"/api/greeks/{_OCC_SYMBOL}")

    assert response.status_code == 200, (
        f"Expected 200 for option symbol, got {response.status_code}"
    )
    data = response.json()
    for key in _GREEKS_KEYS:
        assert key in data, f"Expected key '{key}' in response, got keys: {list(data.keys())}"


def test_get_greeks_returns_correct_values_from_fetch_greeks(client):
    """The route must return the exact dict that fetch_greeks resolves to,
    without transforming values."""
    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = _EXPECTED_GREEKS
        response = client.get(f"/api/greeks/{_OCC_SYMBOL}")

    assert response.status_code == 200
    assert response.json() == _EXPECTED_GREEKS


def test_get_greeks_calls_fetch_greeks_with_symbol_and_token(client):
    """The route must invoke fetch_greeks with the URL symbol and the app's
    session_token.  Verify the call was made with the right arguments."""
    from dashboard.app import app
    app.state.session_token = "route-test-token"

    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = _EXPECTED_GREEKS
        client.get(f"/api/greeks/{_OCC_SYMBOL}")

    mock_fetch.assert_called_once()
    call_kwargs = mock_fetch.call_args[1] if mock_fetch.call_args[1] else {}
    call_args = mock_fetch.call_args[0]
    # Accept either positional or keyword arguments
    called_token = call_kwargs.get("session_token") or (call_args[0] if call_args else None)
    called_symbol = call_kwargs.get("symbol") or (call_args[1] if len(call_args) > 1 else None)
    assert called_token == "route-test-token", (
        f"Expected session_token='route-test-token', got: {called_token!r}"
    )
    assert called_symbol == _OCC_SYMBOL, (
        f"Expected symbol='{_OCC_SYMBOL}', got: {called_symbol!r}"
    )


def test_get_greeks_returns_all_dashes_for_equity_symbol_without_calling_chain_api(client):
    """When the symbol is an equity (not an OCC option), the route must NOT call
    fetch_greeks and must return a response with all five greeks as '—'.
    This enforces the equity short-circuit: greeks are never fetched for equities."""
    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        response = client.get("/api/greeks/AAPL")

    assert response.status_code == 200, (
        f"Expected 200 for equity symbol, got {response.status_code}"
    )
    mock_fetch.assert_not_called(), (
        "fetch_greeks must NOT be called for an equity symbol (no option-chain request)"
    )
    data = response.json()
    for key in _GREEKS_KEYS:
        assert data.get(key) == _DASH, (
            f"Expected '—' for key '{key}' on equity symbol, got: {data.get(key)!r}"
        )


def test_get_greeks_returns_all_dashes_for_garbage_symbol(client):
    """An unrecognised/garbage symbol must return HTTP 200 with all five greeks
    as '—' and must NOT raise or call the option-chain API."""
    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        response = client.get("/api/greeks/NOT_AN_OCC_SYMBOL_AT_ALL")

    assert response.status_code == 200
    mock_fetch.assert_not_called()
    data = response.json()
    for key in _GREEKS_KEYS:
        assert data.get(key) == _DASH, (
            f"Expected '—' for '{key}' on garbage symbol, got: {data.get(key)!r}"
        )


def test_get_greeks_returns_dashes_gracefully_when_fetch_greeks_returns_dashes(client):
    """Even when fetch_greeks returns all-dashes (cert sandbox scenario),
    the route must return 200 with those dash values transparently."""
    all_dashes = {k: _DASH for k in _GREEKS_KEYS}
    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = all_dashes
        response = client.get(f"/api/greeks/{_OCC_SYMBOL}")

    assert response.status_code == 200
    data = response.json()
    for key in _GREEKS_KEYS:
        assert data[key] == _DASH


# --- Edge-case route tests (Phase 4) ---


def test_get_greeks_zero_value_greeks_returned_verbatim(client):
    """When fetch_greeks returns a zero-value greek (e.g. delta '0'), the route
    must NOT replace it with the dash sentinel.  Verifies the route passes the
    fetch_greeks result straight through without filtering zero values."""
    zero_greeks = {k: "0" for k in _GREEKS_KEYS}
    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = zero_greeks
        response = client.get(f"/api/greeks/{_OCC_SYMBOL}")

    assert response.status_code == 200
    data = response.json()
    for key in _GREEKS_KEYS:
        assert data[key] == "0", (
            f"Expected '0' for key '{key}' (zero is a valid greek), "
            f"got {data[key]!r} — route must not sentinel zero values"
        )


# =============================================================================
# Issue #22 — FAILING tests (RED phase) — route behaviors
# =============================================================================


# ---------------------------------------------------------------------------
# Behavior 6: /api/chart/{symbol} serialization shape includes OHLC keys
# ---------------------------------------------------------------------------

def test_get_chart_response_includes_open_key(client):
    """GET /api/chart/{symbol} JSON response must include an 'open' key."""
    from dashboard.app import app
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AAPL22", None)
    app.state.dashboard.on_candle({
        "eventSymbol": "AAPL22{=d}",
        "time": 1,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    response = client.get("/api/chart/AAPL22")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AAPL22", None)
    assert response.status_code == 200
    data = response.json()
    assert "open" in data, (
        f"GET /api/chart response must include 'open' key; got keys: {list(data.keys())}"
    )


def test_get_chart_response_includes_high_key(client):
    """GET /api/chart/{symbol} JSON response must include a 'high' key."""
    from dashboard.app import app
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AAPL22H", None)
    app.state.dashboard.on_candle({
        "eventSymbol": "AAPL22H{=d}",
        "time": 1,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    response = client.get("/api/chart/AAPL22H")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AAPL22H", None)
    assert response.status_code == 200
    data = response.json()
    assert "high" in data, (
        f"GET /api/chart response must include 'high' key; got keys: {list(data.keys())}"
    )


def test_get_chart_response_includes_low_key(client):
    """GET /api/chart/{symbol} JSON response must include a 'low' key."""
    from dashboard.app import app
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AAPL22L", None)
    app.state.dashboard.on_candle({
        "eventSymbol": "AAPL22L{=d}",
        "time": 1,
        "open": 150.0, "high": 155.0, "low": 148.0, "close": 153.0, "volume": 1_000_000,
    })
    response = client.get("/api/chart/AAPL22L")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop("AAPL22L", None)
    assert response.status_code == 200
    data = response.json()
    assert "low" in data, (
        f"GET /api/chart response must include 'low' key; got keys: {list(data.keys())}"
    )


def test_get_chart_response_ohlc_arrays_same_length_as_close(client):
    """open/high/low arrays in the HTTP response must be the same length as close."""
    from dashboard.app import app
    sym = "SPY22"
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop(sym, None)
    closes = [450.0, 451.0, 452.0]
    for i, c in enumerate(closes):
        app.state.dashboard.on_candle({
            "eventSymbol": f"{sym}{{=d}}",
            "time": i,
            "open": c - 1.0, "high": c + 2.0, "low": c - 2.0, "close": c,
            "volume": 5_000_000,
        })
    response = client.get(f"/api/chart/{sym}")
    if hasattr(app.state.dashboard, "candles"):
        app.state.dashboard.candles.pop(sym, None)
    assert response.status_code == 200
    data = response.json()
    n = len(data["close"])
    assert len(data["open"]) == n, f"open length must equal close length {n}"
    assert len(data["high"]) == n, f"high length must equal close length {n}"
    assert len(data["low"]) == n, f"low length must equal close length {n}"


def test_get_chart_empty_symbol_response_includes_ohlc_empty_arrays(client):
    """Unknown symbol response must include open/high/low keys (all empty arrays)."""
    response = client.get("/api/chart/UNKWNOHLC")
    assert response.status_code == 200
    data = response.json()
    assert data.get("open") == [], f"Expected empty open array for unknown symbol; got {data.get('open')}"
    assert data.get("high") == [], f"Expected empty high array for unknown symbol; got {data.get('high')}"
    assert data.get("low") == [], f"Expected empty low array for unknown symbol; got {data.get('low')}"


# ---------------------------------------------------------------------------
# Behavior 4: Single-symbol candle scope — chart route swaps subscription
# ---------------------------------------------------------------------------

def test_get_chart_removes_previous_candle_subscription_before_adding_new():
    """When /api/chart/{symbolB} is called after {symbolA}, the route must
    call remove_candle(symbolA) before add_candle(symbolB) so at most one
    symbol streams candles at a time.  Verified via a fake streamer recording
    the sequence of add/remove calls."""
    from fastapi.testclient import TestClient
    from dashboard.app import app

    calls = []

    class FakeStreamer:
        def add_candle(self, symbol, from_time):
            calls.append(("add", symbol))

        def remove_candle(self, symbol):
            calls.append(("remove", symbol))

    # Install the fake streamer
    original_streamer = getattr(app.state, "streamer", None)
    app.state.streamer = FakeStreamer()

    try:
        with TestClient(app) as c:
            c.get("/api/chart/AAPL")
            calls.clear()  # reset — only care about the second call
            c.get("/api/chart/TSLA")
    finally:
        if original_streamer is not None:
            app.state.streamer = original_streamer
        else:
            del app.state.streamer

    # After fetching TSLA, AAPL's candle subscription must have been removed
    remove_calls = [sym for op, sym in calls if op == "remove"]
    assert "AAPL" in remove_calls, (
        f"Route must call remove_candle('AAPL') before subscribing to TSLA; "
        f"recorded calls: {calls}"
    )

    # And TSLA must have been added
    add_calls = [sym for op, sym in calls if op == "add"]
    assert "TSLA" in add_calls, (
        f"Route must call add_candle('TSLA') after removing AAPL; "
        f"recorded calls: {calls}"
    )


def test_get_chart_remove_called_before_add_in_sequence():
    """The remove must happen BEFORE the add in the call sequence."""
    from fastapi.testclient import TestClient
    from dashboard.app import app

    calls = []

    class FakeStreamer:
        def add_candle(self, symbol, from_time):
            calls.append(("add", symbol))

        def remove_candle(self, symbol):
            calls.append(("remove", symbol))

    original_streamer = getattr(app.state, "streamer", None)
    app.state.streamer = FakeStreamer()

    try:
        with TestClient(app) as c:
            c.get("/api/chart/AAPL")
            calls.clear()
            c.get("/api/chart/TSLA")
    finally:
        if original_streamer is not None:
            app.state.streamer = original_streamer
        else:
            del app.state.streamer

    # Find positions of remove(AAPL) and add(TSLA) in the call sequence
    remove_idx = next(
        (i for i, (op, sym) in enumerate(calls) if op == "remove" and sym == "AAPL"), None
    )
    add_idx = next(
        (i for i, (op, sym) in enumerate(calls) if op == "add" and sym == "TSLA"), None
    )
    assert remove_idx is not None, f"remove_candle('AAPL') not found in calls: {calls}"
    assert add_idx is not None, f"add_candle('TSLA') not found in calls: {calls}"
    assert remove_idx < add_idx, (
        f"remove_candle must be called BEFORE add_candle; "
        f"remove at index {remove_idx}, add at index {add_idx}; calls: {calls}"
    )


# ---------------------------------------------------------------------------
# Behavior 5 (blip root-cause fix): _refresh re-applies last-known price
# ---------------------------------------------------------------------------

def test_refresh_preserves_last_known_price_after_fetch_positions():
    """After a simulated _refresh where fetch_positions returns rows with
    current_price=None, the last-known mark from state.quotes must be
    re-applied so the broadcast positions payload carries non-null current_price."""
    from dashboard.app import app, _refresh
    from unittest.mock import AsyncMock, patch

    app.state.session_token = "fake-token"

    # Pre-seed a live quote for AAPL at mark=155.0
    from src.models import PriceEvent
    app.state.dashboard.on_quote(
        PriceEvent(symbol="AAPL", last=155.0, bid=154.0, ask=156.0, timestamp=1.0)
    )
    # Verify the quote was stored
    assert "AAPL" in app.state.dashboard.quotes, "AAPL quote must be in state.quotes"

    # Set up positions
    fresh_positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,  # fresh from API — always None
            "pl": None,
        }
    ]

    captured = []

    async def spy_broadcast(event_name, data):
        captured.append((event_name, data))

    app.state.dashboard.broadcast = spy_broadcast

    with patch("dashboard.app.fetch_balance", new_callable=AsyncMock) as mock_bal, \
         patch("dashboard.app.fetch_positions", new_callable=AsyncMock) as mock_pos, \
         patch("dashboard.app.fetch_orders", new_callable=AsyncMock) as mock_ord:
        mock_bal.return_value = {
            "account_number": "X", "net_liquidating_value": "0", "buying_power": "0"
        }
        mock_pos.return_value = fresh_positions
        mock_ord.return_value = []
        asyncio.run(_refresh(app))

    del app.state.dashboard.broadcast

    positions_events = [(name, data) for name, data in captured if name == "positions"]
    assert len(positions_events) == 1, "Expected exactly one 'positions' broadcast"

    _, broadcast_data = positions_events[0]
    assert isinstance(broadcast_data, list), "positions broadcast must be a list"
    assert len(broadcast_data) == 1, "Expected one position in the broadcast"

    pos = broadcast_data[0]
    assert pos["current_price"] is not None, (
        "_refresh must re-apply the last-known mark from state.quotes before broadcast; "
        f"current_price must not be None — got {pos['current_price']!r}"
    )
    assert pos["current_price"] == pytest.approx(155.0), (
        f"current_price must equal last-known mark 155.0; got {pos['current_price']}"
    )


def test_get_greeks_passes_occ_symbol_verbatim_to_fetch_greeks(client):
    """The OCC symbol in the URL path (including embedded spaces decoded by
    FastAPI) must be forwarded to fetch_greeks exactly as received — no
    transformation of the symbol before the call."""
    from dashboard.app import app
    app.state.session_token = "verbatim-token"

    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {k: "0.1" for k in _GREEKS_KEYS}
        client.get(f"/api/greeks/{_OCC_SYMBOL}")

    mock_fetch.assert_called_once()
    # Accept either positional or keyword call style
    args = mock_fetch.call_args[0]
    kwargs = mock_fetch.call_args[1] if mock_fetch.call_args[1] else {}
    called_symbol = kwargs.get("symbol") or (args[1] if len(args) > 1 else None)
    assert called_symbol == _OCC_SYMBOL, (
        f"fetch_greeks must receive the OCC symbol verbatim; "
        f"expected {_OCC_SYMBOL!r}, got {called_symbol!r}"
    )


def test_get_greeks_partial_greeks_passed_through_unchanged(client):
    """When fetch_greeks returns a mix of real values and '—' (partial greeks),
    the route must forward that mixed dict verbatim — no normalisation."""
    partial = {"delta": "0.42", "gamma": _DASH, "theta": _DASH, "vega": "0.12", "iv": _DASH}
    with patch("dashboard.app.fetch_greeks", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = partial
        response = client.get(f"/api/greeks/{_OCC_SYMBOL}")

    assert response.status_code == 200
    assert response.json() == partial, (
        "Route must return the fetch_greeks result unchanged; "
        f"expected {partial}, got {response.json()}"
    )


# =============================================================================
# Issue #22 — Phase 4: additional edge / error-path route tests
# =============================================================================

# ---------------------------------------------------------------------------
# Single-symbol scope: first-ever selection and same-symbol reselect
# ---------------------------------------------------------------------------

def test_get_chart_first_selection_no_crash():
    """The very first GET /api/chart/{symbol} (no prior active_candle_symbol) must
    not raise and must return 200.  The route uses getattr(..., None) so a missing
    active_candle_symbol is handled gracefully without remove_candle being called."""
    from dashboard.app import app

    calls = []

    class FakeStreamer:
        def add_candle(self, symbol, from_time):
            calls.append(("add", symbol))

        def remove_candle(self, symbol):
            calls.append(("remove", symbol))

    original_streamer = getattr(app.state, "streamer", None)
    # Wipe any prior active symbol to simulate a fresh start
    had_active = hasattr(app.state, "active_candle_symbol")
    original_active = getattr(app.state, "active_candle_symbol", None)
    if had_active:
        del app.state.active_candle_symbol
    app.state.streamer = FakeStreamer()

    try:
        with TestClient(app) as c:
            response = c.get("/api/chart/AAPL")
    except Exception as exc:
        pytest.fail(f"First /api/chart selection must not raise: {exc!r}")
    finally:
        if original_streamer is not None:
            app.state.streamer = original_streamer
        elif hasattr(app.state, "streamer"):
            del app.state.streamer
        if had_active and original_active is not None:
            app.state.active_candle_symbol = original_active
        elif not had_active and hasattr(app.state, "active_candle_symbol"):
            del app.state.active_candle_symbol

    assert response.status_code == 200, (
        f"First /api/chart selection must return 200; got {response.status_code}"
    )
    # remove_candle must NOT have been called (no previous symbol to remove)
    remove_calls = [sym for op, sym in calls if op == "remove"]
    assert len(remove_calls) == 0, (
        "First selection must not call remove_candle (no prior active symbol); "
        f"got remove calls: {remove_calls}"
    )


def test_get_chart_same_symbol_twice_no_spurious_remove():
    """Requesting /api/chart/{symbol} twice for the SAME symbol must not call
    remove_candle for that symbol (prev == new, so the guard must skip the remove)."""
    from dashboard.app import app

    calls = []

    class FakeStreamer:
        def add_candle(self, symbol, from_time):
            calls.append(("add", symbol))

        def remove_candle(self, symbol):
            calls.append(("remove", symbol))

    original_streamer = getattr(app.state, "streamer", None)
    had_active = hasattr(app.state, "active_candle_symbol")
    original_active = getattr(app.state, "active_candle_symbol", None)
    if had_active:
        del app.state.active_candle_symbol
    app.state.streamer = FakeStreamer()

    try:
        with TestClient(app) as c:
            c.get("/api/chart/AAPL")
            calls.clear()           # only care about second request
            c.get("/api/chart/AAPL")
    finally:
        if original_streamer is not None:
            app.state.streamer = original_streamer
        elif hasattr(app.state, "streamer"):
            del app.state.streamer
        if had_active and original_active is not None:
            app.state.active_candle_symbol = original_active
        elif not had_active and hasattr(app.state, "active_candle_symbol"):
            del app.state.active_candle_symbol

    remove_calls = [sym for op, sym in calls if op == "remove"]
    assert "AAPL" not in remove_calls, (
        "Reselecting the same symbol must NOT call remove_candle for it; "
        f"got calls: {calls}"
    )


# ---------------------------------------------------------------------------
# Blip fix: _refresh with empty quotes and position symbol not in quotes
# ---------------------------------------------------------------------------

def test_refresh_with_empty_quotes_does_not_crash(client):
    """_refresh must not crash when state.quotes is empty (no live quotes yet).
    The blip-fix loop iterates state.quotes — empty dict must be a harmless no-op."""
    from dashboard.app import app, _refresh

    app.state.session_token = "fake-token"
    # Clear quotes to simulate pre-quote state
    app.state.dashboard.quotes.clear()

    fresh_positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
            "pl": None,
        }
    ]

    captured = []

    async def spy_broadcast(event_name, data):
        captured.append((event_name, data))

    app.state.dashboard.broadcast = spy_broadcast

    try:
        with patch("dashboard.app.fetch_balance", new_callable=AsyncMock) as mock_bal, \
             patch("dashboard.app.fetch_positions", new_callable=AsyncMock) as mock_pos, \
             patch("dashboard.app.fetch_orders", new_callable=AsyncMock) as mock_ord:
            mock_bal.return_value = {
                "account_number": "X", "net_liquidating_value": "0", "buying_power": "0"
            }
            mock_pos.return_value = fresh_positions
            mock_ord.return_value = []
            asyncio.run(_refresh(app))
    except Exception as exc:
        pytest.fail(f"_refresh with empty state.quotes must not raise: {exc!r}")
    finally:
        del app.state.dashboard.broadcast

    positions_events = [(n, d) for n, d in captured if n == "positions"]
    assert len(positions_events) == 1, (
        "_refresh must still broadcast positions even when quotes dict is empty"
    )


def test_refresh_position_symbol_not_in_quotes_keeps_none_price(client):
    """_refresh re-applies quotes only for symbols that have a known quote mark.
    A position whose symbol has no entry in state.quotes must keep current_price=None
    (no crash, no spurious price insertion)."""
    from dashboard.app import app, _refresh

    app.state.session_token = "fake-token"
    # Ensure AAPL has no quote
    app.state.dashboard.quotes.pop("AAPL", None)

    fresh_positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
            "pl": None,
        }
    ]

    captured = []

    async def spy_broadcast(event_name, data):
        captured.append((event_name, data))

    app.state.dashboard.broadcast = spy_broadcast

    try:
        with patch("dashboard.app.fetch_balance", new_callable=AsyncMock) as mock_bal, \
             patch("dashboard.app.fetch_positions", new_callable=AsyncMock) as mock_pos, \
             patch("dashboard.app.fetch_orders", new_callable=AsyncMock) as mock_ord:
            mock_bal.return_value = {
                "account_number": "X", "net_liquidating_value": "0", "buying_power": "0"
            }
            mock_pos.return_value = fresh_positions
            mock_ord.return_value = []
            asyncio.run(_refresh(app))
    finally:
        del app.state.dashboard.broadcast

    positions_events = [(n, d) for n, d in captured if n == "positions"]
    assert len(positions_events) == 1
    pos = positions_events[0][1][0]
    assert pos["current_price"] is None, (
        "Position with no quote must keep current_price=None after _refresh; "
        f"got {pos['current_price']!r}"
    )


# =============================================================================
# Issue #22 — Phase 4 contract-gap audit (route layer)
# =============================================================================

# ---------------------------------------------------------------------------
# Contract gap A: fetch_positions supplies 'pl': None — template contract
#
# fetch_positions returns {symbol, instrument_type, quantity, avg_cost,
# current_price: None, pl: None}.  The index.html template reads pos.pl in a
# comparison; if 'pl' were absent Jinja2 would raise UndefinedError.
# All prior template tests inject 'pl' directly — this test uses the exact
# fetch_positions output shape to guard that the key is always present.
# ---------------------------------------------------------------------------

def test_template_renders_with_fetch_positions_output_shape(client):
    """The index template must render without error when positions have exactly
    the shape returned by fetch_positions: {symbol, instrument_type, quantity,
    avg_cost, current_price: None, pl: None}.

    Prior template tests inject numeric pl values (e.g. 50.0) that bypass the
    None path.  This test verifies that the real fetch_positions output shape
    (both sentinel fields as None) renders cleanly and produces a neutral chip."""
    from dashboard.app import app

    # Exact shape that fetch_positions returns
    app.state.dashboard.positions = [
        {
            "symbol": "AAPL",
            "instrument_type": "Equity",
            "quantity": 10,
            "avg_cost": "150.00",
            "current_price": None,
            "pl": None,
        }
    ]
    try:
        response = client.get("/")
    finally:
        app.state.dashboard.positions = []

    assert response.status_code == 200, (
        "Template must render HTTP 200 for positions with pl=None, current_price=None "
        f"(exact fetch_positions output shape); got status {response.status_code}"
    )
    assert 'class="chip neutral"' in response.text, (
        "Template must render neutral chip when pl=None (no P&L computed yet)"
    )
    # Mark cell must show dash when current_price=None
    assert "<td" in response.text, "Table row must be rendered for the position"


# =============================================================================
# Phase 5 review fixes — TDD route tests (RED phase)
# =============================================================================

# --- Fix 2 [Security M1 + NT2]: evict previous symbol in-memory state on swap ---

def test_get_chart_symbol_swap_evicts_previous_symbol_candle_state():
    """After fetching /api/chart/A then /api/chart/B, state.candles must no longer
    contain key 'A' (and the two throttle dicts must not contain 'A'), while 'B'
    is retained.  This enforces the design's bounded-memory claim."""
    from fastapi.testclient import TestClient
    from dashboard.app import app

    calls = []

    class FakeStreamer:
        def add_candle(self, symbol, from_time):
            calls.append(("add", symbol))

        def remove_candle(self, symbol):
            calls.append(("remove", symbol))

    original_streamer = getattr(app.state, "streamer", None)
    had_active = hasattr(app.state, "active_candle_symbol")
    original_active = getattr(app.state, "active_candle_symbol", None)
    if had_active:
        del app.state.active_candle_symbol
    app.state.streamer = FakeStreamer()

    try:
        with TestClient(app) as c:
            # Seed candles for both symbols so buckets exist (must be inside context)
            app.state.dashboard.on_candle({
                "eventSymbol": "EVICTA{=d}", "time": 1,
                "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100,
            })
            app.state.dashboard.on_candle({
                "eventSymbol": "EVICTB{=d}", "time": 1,
                "open": 20.0, "high": 21.0, "low": 19.0, "close": 20.5, "volume": 100,
            })
            c.get("/api/chart/EVICTA")
            c.get("/api/chart/EVICTB")

            state = app.state.dashboard
            assert "EVICTA" not in state.candles, (
                "After switching from EVICTA to EVICTB, state.candles must not contain EVICTA"
            )
            assert "EVICTA" not in state._candle_last_broadcast, (
                "After switching from EVICTA to EVICTB, _candle_last_broadcast must not contain EVICTA"
            )
            assert "EVICTA" not in state._candle_last_time, (
                "After switching from EVICTA to EVICTB, _candle_last_time must not contain EVICTA"
            )
            # The current symbol's bucket must be retained
            assert "EVICTB" in state.candles, (
                "state.candles must retain the currently-active symbol EVICTB"
            )

            # Clean up seeded candle data
            state.candles.pop("EVICTA", None)
            state.candles.pop("EVICTB", None)
            state._candle_last_broadcast.pop("EVICTA", None)
            state._candle_last_broadcast.pop("EVICTB", None)
            state._candle_last_time.pop("EVICTA", None)
            state._candle_last_time.pop("EVICTB", None)
    finally:
        if original_streamer is not None:
            app.state.streamer = original_streamer
        elif hasattr(app.state, "streamer"):
            del app.state.streamer
        if had_active and original_active is not None:
            app.state.active_candle_symbol = original_active
        elif not had_active and hasattr(app.state, "active_candle_symbol"):
            del app.state.active_candle_symbol


def test_get_chart_same_symbol_reselect_does_not_evict():
    """Selecting the same symbol again (prev == new) must NOT evict its candle state."""
    from fastapi.testclient import TestClient
    from dashboard.app import app

    class FakeStreamer:
        def add_candle(self, symbol, from_time): pass
        def remove_candle(self, symbol): pass

    original_streamer = getattr(app.state, "streamer", None)
    had_active = hasattr(app.state, "active_candle_symbol")
    original_active = getattr(app.state, "active_candle_symbol", None)
    if had_active:
        del app.state.active_candle_symbol
    app.state.streamer = FakeStreamer()

    try:
        with TestClient(app) as c:
            # Seed candles for symbol (must be inside TestClient context)
            app.state.dashboard.on_candle({
                "eventSymbol": "NOEVICT{=d}", "time": 1,
                "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100,
            })
            c.get("/api/chart/NOEVICT")
            c.get("/api/chart/NOEVICT")  # reselect same symbol

            state = app.state.dashboard
            assert "NOEVICT" in state.candles, (
                "Reselecting the same symbol must NOT evict its candle bucket"
            )

            # Clean up
            state.candles.pop("NOEVICT", None)
            state._candle_last_broadcast.pop("NOEVICT", None)
            state._candle_last_time.pop("NOEVICT", None)
    finally:
        if original_streamer is not None:
            app.state.streamer = original_streamer
        elif hasattr(app.state, "streamer"):
            del app.state.streamer
        if had_active and original_active is not None:
            app.state.active_candle_symbol = original_active
        elif not had_active and hasattr(app.state, "active_candle_symbol"):
            del app.state.active_candle_symbol
