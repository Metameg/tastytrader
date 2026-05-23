from dataclasses import dataclass
from enum import Enum


class Direction(Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"


class StrategyState(Enum):
    WATCHING = "WATCHING"
    APPROACHING = "APPROACHING"
    COOLDOWN = "COOLDOWN"


@dataclass
class PriceEvent:
    symbol: str
    last: float
    bid: float
    ask: float
    timestamp: float


@dataclass
class TradeSignal:
    direction: Direction
    price_event: PriceEvent
