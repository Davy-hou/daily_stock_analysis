from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from src.trading.config import Side


@dataclass
class RiskConfig:
    max_position_value: float = 50000
    max_daily_loss: float = 2000
    default_stop_loss_pct: float = 0.02


@dataclass
class CheckResult:
    approved: bool = True
    reason: Optional[str] = None
    triggered: Optional[bool] = None
    exit_price: Optional[float] = None


class RiskManager:
    def __init__(self, config: RiskConfig | None = None):
        self.config = config or RiskConfig()

    def check_order(
        self,
        price: float,
        volume: int,
        side: Side,
        current_position: Any | None,
        daily_pnl: float,
    ) -> CheckResult:
        if side == Side.SELL:
            return CheckResult()
        order_value = price * volume
        if order_value > self.config.max_position_value:
            return CheckResult(
                approved=False,
                reason=f"order_value {order_value:.2f} exceeds max_position_value {self.config.max_position_value:.2f}",
            )
        if daily_pnl <= -self.config.max_daily_loss:
            return CheckResult(
                approved=False,
                reason=f"daily_pnl {daily_pnl:.2f} exceeds max_daily_loss {self.config.max_daily_loss:.2f}",
            )
        return CheckResult()

    def check_stop_loss(self, entry_price: float, current_price: float) -> CheckResult:
        loss_pct = (entry_price - current_price) / entry_price
        if loss_pct >= self.config.default_stop_loss_pct:
            return CheckResult(
                approved=True,
                triggered=True,
                reason=f"stop_loss triggered: loss {loss_pct:.2%} >= {self.config.default_stop_loss_pct:.2%}",
                exit_price=current_price,
            )
        return CheckResult(triggered=False)
