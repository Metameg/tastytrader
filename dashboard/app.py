from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.auth import login
from src.config import load_config
from dashboard.api import fetch_balance, fetch_positions, fetch_orders, place_order
from dashboard.state import DashboardState

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
    try:
        auth = await login(app.state.config.username, app.state.config.password)
        app.state.session_token = auth.session_token
        await _refresh(app)
    except Exception:
        pass
    task = asyncio.create_task(_poll(app))
    try:
        yield
    finally:
        task.cancel()


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


@app.post("/api/orders")
async def create_order(request: Request):
    body = await request.json()
    token: str = request.app.state.session_token
    acct: str = request.app.state.config.execution.account_number
    try:
        order_id = await place_order(
            session_token=token,
            account_number=acct,
            symbol=body["symbol"],
            instrument_type=body["instrument_type"],
            action=body["action"],
            quantity=int(body["quantity"]),
            limit_price=float(body["limit_price"]),
        )
        return {"order_id": order_id}
    except httpx.HTTPStatusError as exc:
        msg: str = str(exc)
        try:
            error_data = exc.response.json()
            if isinstance(error_data, dict):
                nested = error_data.get("error", {})
                if isinstance(nested, dict) and nested.get("message"):
                    msg = nested["message"]
                else:
                    msg = exc.response.text
            else:
                msg = exc.response.text
        except Exception:
            msg = exc.response.text
        return JSONResponse(status_code=400, content={"error": msg})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard.app:app", host="0.0.0.0", port=8000, reload=True)
