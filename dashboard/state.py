from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class DashboardState:
    account_number: str = "—"
    net_liquidating_value: str = "—"
    buying_power: str = "—"
    positions: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)

    def get_account_summary(self) -> dict:
        return {
            "account_number": self.account_number,
            "net_liquidating_value": self.net_liquidating_value,
            "buying_power": self.buying_power,
        }
