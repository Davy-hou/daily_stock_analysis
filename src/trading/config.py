from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

import numpy as np


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    code: str
    side: Side
    price: float
    confidence: float
    time: datetime
    reason: str = ""


@dataclass
class Order:
    code: str
    side: Side
    price: float
    volume: int
    status: OrderStatus = OrderStatus.PENDING
    type: OrderType = OrderType.MARKET
    filled_time: Optional[datetime] = None
    filled_price: Optional[float] = None


@dataclass
class Trade:
    code: str
    buy_time: datetime
    buy_price: float
    sell_time: datetime
    sell_price: float
    volume: int
    fee: float

    @property
    def profit(self) -> float:
        return (self.sell_price - self.buy_price) * self.volume - self.fee

    @property
    def return_pct(self) -> float:
        return (self.sell_price - self.buy_price) / self.buy_price * 100

    @property
    def duration_minutes(self) -> float:
        return (self.sell_time - self.buy_time).total_seconds() / 60.0


@dataclass
class Metrics:
    trades: list[Trade]

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def win_trades(self) -> int:
        return sum(1 for t in self.trades if t.profit > 0)

    @property
    def loss_trades(self) -> int:
        return sum(1 for t in self.trades if t.profit <= 0)

    @property
    def win_rate(self) -> Optional[float]:
        if self.total_trades == 0:
            return None
        return self.win_trades / self.total_trades * 100

    @property
    def total_profit(self) -> float:
        return sum(t.profit for t in self.trades)

    @property
    def profit_factor(self) -> Optional[float]:
        gross_profit = sum(t.profit for t in self.trades if t.profit > 0)
        gross_loss = abs(sum(t.profit for t in self.trades if t.profit < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else None
        return gross_profit / gross_loss

    @property
    def sharpe_ratio(self) -> Optional[float]:
        if self.total_trades < 2:
            return None
        returns = [(t.sell_price - t.buy_price) / t.buy_price for t in self.trades]
        if len(returns) < 2 or np.std(returns) == 0:
            return None
        return float(np.mean(returns) / np.std(returns) * np.sqrt(240))

    @property
    def max_drawdown_pct(self) -> Optional[float]:
        if self.total_trades == 0:
            return None
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative += t.profit
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd * 100
