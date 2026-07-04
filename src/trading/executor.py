from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from src.trading.config import Signal, Side, Order, OrderType, OrderStatus, Trade


@dataclass
class ExecutionResult:
    order: Optional[Order] = None
    trade: Optional[Trade] = None
    position: Optional[dict] = None
    cash_used: float = 0.0
    cash_received: float = 0.0
    error: Optional[str] = None


class SimulatedExecutor:
    def __init__(self, fee_rate: float = 0.0001, slippage: float = 0.0001, min_volume: int = 100):
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.min_volume = min_volume

    def execute(
        self,
        signal: Signal,
        position: Optional[dict],
        cash: float,
    ) -> ExecutionResult:
        if signal.side == Side.BUY:
            if position is not None:
                return ExecutionResult(error="already in position")
            fill_price = signal.price * (1 + self.slippage)
            volume = int(cash * 0.95 / fill_price / self.min_volume) * self.min_volume
            if volume < self.min_volume:
                return ExecutionResult(error=f"insufficient cash: can only buy {volume} shares, min {self.min_volume}")
            order_value = fill_price * volume
            fee = order_value * self.fee_rate
            if order_value + fee > cash:
                return ExecutionResult(error=f"insufficient cash: need {order_value + fee:.2f}, have {cash:.2f}")
            order = Order(
                code=signal.code, side=Side.BUY, price=signal.price,
                volume=volume, status=OrderStatus.FILLED,
                order_type=OrderType.MARKET,
                filled_time=signal.time, filled_price=fill_price,
            )
            new_position = {
                "buy_price": fill_price,
                "buy_time": signal.time,
                "volume": volume,
            }
            return ExecutionResult(
                order=order,
                position=new_position,
                cash_used=order_value + fee,
            )

        if signal.side == Side.SELL:
            if position is None:
                return ExecutionResult(error="no position to sell")
            fill_price = signal.price * (1 - self.slippage)
            volume = position["volume"]
            order_value = fill_price * volume
            fee = order_value * self.fee_rate
            buy_fee = position["buy_price"] * volume * self.fee_rate
            order = Order(
                code=signal.code, side=Side.SELL, price=signal.price,
                volume=volume, status=OrderStatus.FILLED,
                order_type=OrderType.MARKET,
                filled_time=signal.time, filled_price=fill_price,
            )
            trade = Trade(
                code=signal.code,
                buy_time=position["buy_time"],
                buy_price=position["buy_price"],
                sell_time=signal.time,
                sell_price=fill_price,
                volume=volume,
                fee=fee + buy_fee,
            )
            return ExecutionResult(
                order=order,
                trade=trade,
                position=None,
                cash_received=order_value - fee,
            )

        return ExecutionResult(error=f"unknown side: {signal.side}")
