"""One-shot script to place a single equity buy order on the paper trading account.

Usage:
    python scripts/test_equity_buy.py [SYMBOL] [LIMIT_PRICE] [QUANTITY]

Example:
    python scripts/test_equity_buy.py AAPL 210.00 1
"""
from __future__ import annotations
import asyncio
import json
import sys

import httpx
from dotenv import load_dotenv
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / "config" / ".env")

BASE_URL = "https://api.cert.tastyworks.com"
ACCOUNT = "5WX78966"


async def get_token() -> str:
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{BASE_URL}/sessions",
            json={
                "login": os.environ["TASTYTRADE_USERNAME"],
                "password": os.environ["TASTYTRADE_PASSWORD"],
            },
        )
        r.raise_for_status()
        return r.json()["data"]["session-token"]


async def place_equity_order(token: str, symbol: str, quantity: int, limit_price: float) -> dict:
    body = {
        "order-type": "Limit",
        "time-in-force": "Day",
        "price": f"{limit_price:.2f}",
        "price-effect": "Debit",
        "legs": [
            {
                "instrument-type": "Equity",
                "symbol": symbol,
                "quantity": quantity,
                "action": "Buy to Open",
            }
        ],
    }
    print("Order body:")
    print(json.dumps(body, indent=2))

    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{BASE_URL}/accounts/{ACCOUNT}/orders",
            json=body,
            headers={"Authorization": token},
        )
        print(f"\nResponse ({r.status_code}):")
        print(r.text)
        return r.json()


async def main() -> None:
    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "AAPL"
    limit_price = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    quantity = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    if limit_price <= 0:
        print("Usage: python scripts/test_equity_buy.py SYMBOL LIMIT_PRICE [QUANTITY]")
        print("Example: python scripts/test_equity_buy.py AAPL 210.00 1")
        sys.exit(1)

    print("Logging in...")
    token = await get_token()
    print("Authenticated.\n")

    print(f"Placing BUY {quantity}x {symbol} @ ${limit_price:.2f} on account {ACCOUNT}...")
    await place_equity_order(token, symbol, quantity, limit_price)


if __name__ == "__main__":
    asyncio.run(main())
