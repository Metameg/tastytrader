import tomllib
import os
from dataclasses import dataclass
from dotenv import load_dotenv


@dataclass
class MarketConfig:
    symbol: str
    ema_short: int
    ema_long: int
    threshold: float
    cooldown_seconds: int


@dataclass
class ExecutionConfig:
    account_number: str
    call_symbol: str
    put_symbol: str
    quantity: int


@dataclass
class AppConfig:
    username: str
    password: str
    market: MarketConfig
    execution: ExecutionConfig


def load_config(
    settings_path: str = "config/settings.toml",
    env_path: str = "config/.env",
) -> AppConfig:
    load_dotenv(env_path)

    with open(settings_path, "rb") as f:
        raw = tomllib.load(f)

    return AppConfig(
        username=os.environ["TASTYTRADE_USERNAME"],
        password=os.environ["TASTYTRADE_PASSWORD"],
        market=MarketConfig(**raw["market"]),
        execution=ExecutionConfig(**raw["execution"]),
    )
