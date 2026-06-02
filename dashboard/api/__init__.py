from __future__ import annotations
import httpx

BASE_URL = "https://api.cert.tastyworks.com"


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
            "buying_power": data["buying-power"],
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
            received = item.get("received-at", "")
            time_str = received[11:19] if len(received) >= 19 else received
            result.append({
                "symbol": item.get("underlying-symbol", leg.get("symbol", "—")),
                "action": leg.get("action", "—"),
                "order_type": item.get("order-type", "—"),
                "quantity": int(leg.get("quantity", 0)),
                "price": item.get("price", "—"),
                "status": item.get("status", "—"),
                "time": time_str,
            })
        return result
