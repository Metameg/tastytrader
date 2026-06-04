from __future__ import annotations
from datetime import datetime, timezone, timedelta

import httpx

BASE_URL = "https://api.cert.tastyworks.com"

try:
    from zoneinfo import ZoneInfo
    _CENTRAL_TZ = ZoneInfo("America/Chicago")
except Exception:
    _CENTRAL_TZ = timezone(timedelta(hours=-5))  # CDT fallback


def _fmt_order_time(received: str) -> str:
    if not received:
        return "—"
    try:
        dt = datetime.fromisoformat(received.replace("Z", "+00:00"))
        ct = dt.astimezone(_CENTRAL_TZ)
        h, m = ct.hour, ct.minute
        return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'} CT"
    except Exception:
        return received[11:19] if len(received) >= 19 else received


async def fetch_balance(
    session_token: str,
    account_number: str,
    base_url: str = BASE_URL,
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/accounts/{account_number}/balances",
            headers={"Authorization": session_token},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return {
            "account_number": data["account-number"],
            "net_liquidating_value": data["net-liquidating-value"],
            "buying_power": data.get("derivative-buying-power", data.get("equity-buying-power", "—")),
        }


async def fetch_positions(
    session_token: str,
    account_number: str,
    base_url: str = BASE_URL,
) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/accounts/{account_number}/positions",
            headers={"Authorization": session_token},
        )
        resp.raise_for_status()
        items = resp.json()["data"]["items"]
        return [
            {
                "symbol": item["symbol"],
                "instrument_type": item["instrument-type"],
                "quantity": int(item["quantity"]),
                "avg_cost": item.get("average-open-price", "—"),
                "current_price": None,
                "pl": None,
            }
            for item in items
        ]


async def fetch_quote_token(
    session_token: str,
    base_url: str = BASE_URL,
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/api-quote-tokens",
            headers={"Authorization": session_token},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
        return {
            "token": data["token"],
            "dxlink_url": data["dxlink-url"],
        }


async def fetch_orders(
    session_token: str,
    account_number: str,
    base_url: str = BASE_URL,
) -> list[dict]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{base_url}/accounts/{account_number}/orders/live",
            headers={"Authorization": session_token},
        )
        resp.raise_for_status()
        items = resp.json()["data"]["items"]
        result = []
        for item in items:
            legs = item.get("legs", [{}])
            leg = legs[0] if legs else {}
            time_str = _fmt_order_time(item.get("received-at", ""))
            result.append({
                "id": item.get("id"),
                "symbol": item.get("underlying-symbol", leg.get("symbol", "—")),
                "action": leg.get("action", "—"),
                "order_type": item.get("order-type", "—"),
                "quantity": int(leg.get("quantity", 0)),
                "price": item.get("price", "—"),
                "status": item.get("status", "—"),
                "time": time_str,
            })
        return result


async def place_order(
    session_token: str,
    account_number: str,
    symbol: str,
    instrument_type: str,
    action: str,
    quantity: int,
    limit_price: float,
    base_url: str = BASE_URL,
) -> str:
    price_effect = "Debit" if action == "Buy to Open" else "Credit"
    body = {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price": f"{limit_price:.2f}",
        "price-effect": price_effect,
        "legs": [
            {
                "instrument-type": instrument_type,
                "symbol": symbol,
                "quantity": str(quantity),
                "action": action,
            }
        ],
    }
    print(f"[order] POST /orders body: {body}")
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/accounts/{account_number}/orders",
            json=body,
            headers={"Authorization": session_token},
        )
        print(f"[order] response {resp.status_code}: {resp.text}")
        resp.raise_for_status()
        return resp.json()["data"]["order"]["id"]


async def cancel_order(
    session_token: str,
    account_number: str,
    order_id: str,
    base_url: str = BASE_URL,
) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.delete(
            f"{base_url}/accounts/{account_number}/orders/{order_id}",
            headers={"Authorization": session_token},
        )
        resp.raise_for_status()


_GREEKS_SENTINEL: dict[str, str] = {
    "delta": "—",
    "gamma": "—",
    "theta": "—",
    "vega": "—",
    "iv": "—",
}


async def fetch_greeks(
    session_token: str,
    symbol: str,
    base_url: str = BASE_URL,
) -> dict[str, str]:
    """Fetch option greeks for an OCC-formatted symbol.

    Calls GET /option-chains/{underlying}, matches the contract by OCC symbol,
    and returns a dict with keys delta, gamma, theta, vega, iv.
    Every missing/error case returns the string sentinel "—" without raising.
    """
    # Import here to avoid circular — state.py is a sibling module
    from dashboard.state import parse_occ

    parsed = parse_occ(symbol)
    if parsed is None:
        return dict(_GREEKS_SENTINEL)

    underlying = parsed["underlying"]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{base_url}/option-chains/{underlying}",
                headers={"Authorization": session_token},
            )
            resp.raise_for_status()
            items: list[dict] = resp.json()["data"]["items"]
    except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError):
        return dict(_GREEKS_SENTINEL)

    contract: dict | None = next(
        (it for it in items if it.get("symbol") == symbol), None
    )
    if contract is None:
        return dict(_GREEKS_SENTINEL)

    def _val(key: str) -> str:
        v = contract.get(key)
        return str(v) if v is not None and v != "" else "—"

    return {
        "delta": _val("delta"),
        "gamma": _val("gamma"),
        "theta": _val("theta"),
        "vega": _val("vega"),
        "iv": _val("implied-volatility"),
    }
