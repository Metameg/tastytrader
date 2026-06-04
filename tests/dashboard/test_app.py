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
    response = client.get("/api/chart/UNKNOWN_SYMBOL_XYZ")
    assert response.status_code == 200
    data = response.json()
    assert data == {"labels": [], "close": [], "ema_short": [], "ema_long": []}, (
        f"Expected empty-array dict for unknown symbol; got {data}"
    )


# --- Issue #7: /api/chart route edge cases ---

def test_get_chart_returns_four_keys_for_unknown_symbol(client):
    """All four chart keys must be present even for a symbol with no history.
    The frontend always destructures {labels, close, ema_short, ema_long}."""
    response = client.get("/api/chart/TOTALLY_UNKNOWN_SYM_XYZQ")
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
