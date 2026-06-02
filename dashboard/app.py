from __future__ import annotations
import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.auth import login
from src.config import load_config
from dashboard.api import fetch_balance, fetch_positions, fetch_orders, fetch_quote_token
from dashboard.state import DashboardState
from dashboard.streamer import DashboardStreamer

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
        state.orders = await fetch_orders(token, acct)
        await state.broadcast("account", state.get_account_summary())
        await state.broadcast("positions", {"positions": state.positions})
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
            "positions": state.positions,
            "orders": state.orders,
        },
    )


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
                    yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard.app:app", host="127.0.0.1", port=8000, reload=True)
