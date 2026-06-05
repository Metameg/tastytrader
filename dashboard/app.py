from __future__ import annotations
import asyncio
import json
import re as _re
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.auth import login
from src.config import load_config
from dashboard.api import cancel_order, fetch_balance, fetch_greeks, fetch_positions, fetch_orders, fetch_quote_token, place_order
from dashboard.state import DashboardState, parse_occ
from dashboard.streamer import DashboardStreamer

_VALID_ACTIONS: frozenset[str] = frozenset({"Buy to Open", "Sell to Close"})
_VALID_INSTRUMENT_TYPES: frozenset[str] = frozenset({"Equity", "Equity Option"})
_OPEN_ORDER_STATUSES: frozenset[str] = frozenset({"Received", "Routed", "Live"})

_BASE = Path(__file__).parent
_POLL_INTERVAL = 15


async def _refresh(app: FastAPI) -> None:
    state: DashboardState = app.state.dashboard
    token: str = app.state.session_token
    if not token:
        return
    acct = app.state.config.execution.account_number
    try:
        balance = await fetch_balance(token, acct)
        state.account_number = balance["account_number"]
        state.net_liquidating_value = balance["net_liquidating_value"]
        state.buying_power = balance["buying_power"]
        state.positions = await fetch_positions(token, acct)
        # Re-apply last-known mark so the 15s rebuild doesn't wipe live prices to None
        # (root-cause fix for mark/P&L blip — AC8).
        for pos in state.positions:
            sym = pos["symbol"]
            if sym in state.quotes:
                mark = state.quotes[sym].get("last")
                if mark is not None:
                    state.update_quote(sym, mark)
        all_orders = await fetch_orders(token, acct)
        state.orders = [o for o in all_orders if o.get("status") in _OPEN_ORDER_STATUSES]
        await state.broadcast("account", state.get_account_summary())
        await state.broadcast("positions", state.positions)
        await state.broadcast("orders", {"orders": state.orders})
        if hasattr(app.state, "streamer"):
            for pos in state.positions:
                app.state.streamer.add_quote(pos["symbol"])
    except Exception:
        pass


async def _poll(app: FastAPI) -> None:
    while True:
        await asyncio.sleep(_POLL_INTERVAL)
        await _refresh(app)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.config = load_config()
    app.state.dashboard = DashboardState()
    app.state.session_token = ""
    streamer_task = None
    try:
        auth = await login(app.state.config.username, app.state.config.password)
        app.state.session_token = auth.session_token
        qt = await fetch_quote_token(auth.session_token)
        streamer = DashboardStreamer(
            quote_token=qt["token"],
            streamer_url=qt["dxlink_url"],
            price_callback=app.state.dashboard.on_quote,
            candle_callback=app.state.dashboard.on_candle,
        )
        app.state.streamer = streamer
        await _refresh(app)
        streamer_task = asyncio.create_task(streamer.run())
    except Exception:
        pass
    poll_task = asyncio.create_task(_poll(app))
    try:
        yield
    finally:
        poll_task.cancel()
        if streamer_task:
            streamer_task.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=_BASE / "static"), name="static")
_templates = Jinja2Templates(directory=_BASE / "templates")


def _fmt_dollar(value: object) -> str:
    try:
        return f"${float(str(value).replace(',', '')):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pnl(value: object) -> str:
    try:
        n = float(str(value).replace(",", ""))
        return f"{'+' if n >= 0 else '-'}${abs(n):,.2f}"
    except (TypeError, ValueError):
        return "—"


_templates.env.filters["fmt_dollar"] = _fmt_dollar
_templates.env.filters["fmt_pnl"] = _fmt_pnl


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    state: DashboardState = request.app.state.dashboard
    summary = state.get_account_summary()
    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "account_number": summary["account_number"],
            "net_liquidating_value": summary["net_liquidating_value"],
            "buying_power": summary["buying_power"],
            "positions": state.get_positions_grouped(),
            "orders": state.orders,
        },
    )


@app.delete("/api/orders/{order_id}")
async def delete_order(order_id: str, request: Request):
    if not _re.fullmatch(r"[A-Za-z0-9_-]+", order_id):
        return JSONResponse(status_code=400, content={"error": "invalid order id"})
    state: DashboardState = request.app.state.dashboard
    token: str = request.app.state.session_token
    acct = request.app.state.config.execution.account_number
    state.orders = [o for o in state.orders if str(o.get("id")) != order_id]
    try:
        await cancel_order(token, acct, order_id)
        return {"status": "ok"}
    except httpx.HTTPStatusError as e:
        return JSONResponse(status_code=e.response.status_code, content={"error": e.response.text})


@app.get("/api/positions")
async def get_positions(request: Request):
    state: DashboardState = request.app.state.dashboard
    return JSONResponse(content=state.positions)


@app.get("/stream/live")
async def stream_live(request: Request):
    state: DashboardState = request.app.state.dashboard
    queue = await state.add_subscriber()

    async def event_generator():
        yield ": keepalive\n\n"
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15.0)
                    event_name = item["event"].replace("\n", "").replace("\r", "")
                    yield f"event: {event_name}\ndata: {json.dumps(item['data'])}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            await state.remove_subscriber(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream; charset=utf-8",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/quotes/{symbol}")
async def get_quote(symbol: str, request: Request):
    state: DashboardState = request.app.state.dashboard
    return state.quotes.get(symbol, {})


@app.get("/api/chart/{symbol}")
async def get_chart(symbol: str, request: Request):
    if not _re.fullmatch(r"[A-Za-z0-9.\-]{1,15}", symbol):
        return JSONResponse(status_code=400, content={"error": "invalid symbol"})
    state: DashboardState = request.app.state.dashboard
    # Single-symbol candle scope: swap candle subscription to the new symbol
    # so at most one symbol streams live candle data at a time (AC5).
    if hasattr(request.app.state, "streamer"):
        prev = getattr(request.app.state, "active_candle_symbol", None)
        if prev is not None and prev != symbol:
            request.app.state.streamer.remove_candle(prev)
            state.evict_candle_state(prev)
        from_time = int(time.time() - 60 * 86400)
        request.app.state.streamer.add_candle(symbol, from_time)
        request.app.state.active_candle_symbol = symbol
    return state.get_chart_data(symbol)


@app.get("/api/greeks/{symbol}")
async def get_greeks(symbol: str, request: Request):
    if parse_occ(symbol) is None:
        # Equity or unrecognised symbol — return sentinel dict, no network call
        return {"delta": "—", "gamma": "—", "theta": "—", "vega": "—", "iv": "—"}

    token: str = request.app.state.session_token
    return await fetch_greeks(token, symbol)


@app.post("/api/orders")
async def create_order(request: Request):
    body = await request.json()
    token: str = request.app.state.session_token
    acct: str = request.app.state.config.execution.account_number
    try:
        symbol = str(body["symbol"]).strip()
        action = body["action"]
        instrument_type = body["instrument_type"]
        quantity = int(body["quantity"])
        limit_price = float(body["limit_price"])
    except (KeyError, ValueError) as exc:
        return JSONResponse(status_code=400, content={"error": f"Invalid request: {exc}"})

    if not symbol:
        return JSONResponse(status_code=400, content={"error": "symbol is required"})
    if action not in _VALID_ACTIONS:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid action '{action}'. Must be one of: {sorted(_VALID_ACTIONS)}"},
        )
    if instrument_type not in _VALID_INSTRUMENT_TYPES:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid instrument_type '{instrument_type}'. Must be one of: {sorted(_VALID_INSTRUMENT_TYPES)}"},
        )
    if quantity < 1:
        return JSONResponse(status_code=400, content={"error": "quantity must be >= 1"})
    if limit_price <= 0:
        return JSONResponse(status_code=400, content={"error": "limit_price must be > 0"})

    try:
        order_id = await place_order(
            session_token=token,
            account_number=acct,
            symbol=symbol,
            instrument_type=instrument_type,
            action=action,
            quantity=quantity,
            limit_price=limit_price,
        )
        return {"order_id": order_id}
    except httpx.RequestError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": f"Could not reach brokerage: {exc}"},
        )
    except httpx.HTTPStatusError as exc:
        try:
            error_data = exc.response.json()
            nested = error_data.get("error", {}) if isinstance(error_data, dict) else {}
            msg: str = (nested.get("message") if isinstance(nested, dict) else None) or exc.response.text
        except Exception:
            msg = exc.response.text
        return JSONResponse(status_code=400, content={"error": msg})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard.app:app", host="127.0.0.1", port=8000, reload=True)
