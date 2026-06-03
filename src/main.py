from __future__ import annotations
import asyncio
import signal

from src.auth import login, fetch_quote_token
from src.config import load_config
from src.executor import Executor
from src.strategy import Strategy
from src.streamer import Streamer


async def main() -> None:
    config = load_config()

    print("Logging in to sandbox...")
    auth = await login(config.username, config.password)
    qt = await fetch_quote_token(auth.session_token)
    print("Authenticated.")

    price_queue: asyncio.Queue = asyncio.Queue()
    signal_queue: asyncio.Queue = asyncio.Queue()

    streamer = Streamer(
        symbol=config.market.symbol,
        quote_token=qt["token"],
        streamer_url=qt["dxlink_url"],
        price_queue=price_queue,
    )
    strategy = Strategy(
        config=config.market,
        price_queue=price_queue,
        signal_queue=signal_queue,
    )
    executor = Executor(
        config=config.execution,
        auth=auth,
        signal_queue=signal_queue,
    )

    loop = asyncio.get_running_loop()

    def _shutdown():
        print("Shutdown signal received.")
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _shutdown)

    print(
        f"Starting daemon — symbol={config.market.symbol} "
        f"EMA{config.market.ema_short}/{config.market.ema_long}"
    )

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(streamer.run())
            tg.create_task(strategy.run())
            tg.create_task(executor.run())
    except* asyncio.CancelledError:
        print("Daemon stopped.")


if __name__ == "__main__":
    asyncio.run(main())
