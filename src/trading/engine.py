from __future__ import annotations

from typing import Optional
import pandas as pd

from src.trading.config import Bar, Signal, Side, Trade, Metrics
from src.trading.strategies.base import Strategy


class BacktestResult:
    def __init__(self, trades: list[Trade], equity_curve: list[float], metrics: Metrics):
        self.trades = trades
        self.equity_curve = equity_curve
        self.metrics = metrics


class IntradayEngine:
    def __init__(self, fee_rate: float = 0.0001, slippage: float = 0.0001,
                 initial_cash: float = 100000):
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.initial_cash = initial_cash

    def run(self, df: pd.DataFrame, strategy: Strategy) -> BacktestResult:
        strategy.reset()
        trades: list[Trade] = []
        position: Optional[dict] = None
        cash = self.initial_cash
        equity_curve = [self.initial_cash]

        for _, row in df.iterrows():
            bar = Bar(
                time=row["time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
            )
            state = {"position": position, "cash": cash, "bar": bar}
            signal = strategy.on_bar(bar, state)

            if signal is None:
                equity_curve.append(self._current_equity(cash, position, bar.close))
                continue

            if signal.side == Side.BUY and position is None:
                volume = int(cash * 0.95 / bar.close / 100) * 100
                if volume < 100:
                    equity_curve.append(self._current_equity(cash, position, bar.close))
                    continue
                fill_price = bar.close * (1 + self.slippage)
                fee = fill_price * volume * self.fee_rate
                cash -= fill_price * volume + fee
                position = {"buy_price": fill_price, "buy_time": bar.time, "volume": volume}

            elif signal.side == Side.SELL and position is not None:
                fill_price = bar.close * (1 - self.slippage)
                volume = position["volume"]
                fee = fill_price * volume * self.fee_rate
                cash += fill_price * volume - fee

                trade = Trade(
                    code=signal.code,
                    buy_time=position["buy_time"],
                    buy_price=position["buy_price"],
                    sell_time=bar.time,
                    sell_price=fill_price,
                    volume=volume,
                    fee=fee + position["buy_price"] * volume * self.fee_rate,
                )
                trades.append(trade)
                position = None

            equity_curve.append(self._current_equity(cash, position, bar.close))

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            metrics=Metrics(trades=trades),
        )

    def _current_equity(self, cash: float, position: Optional[dict],
                        current_price: float) -> float:
        if position is None:
            return cash
        return cash + position["volume"] * current_price
