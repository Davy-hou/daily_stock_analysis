from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import pandas as pd
from src.trading.config import Bar, Signal, Side, Trade, Metrics
from src.trading.strategies.base import Strategy
from src.trading.risk_manager import RiskManager, RiskConfig
from src.trading.executor import SimulatedExecutor
from src.trading.reporter import generate_report


@dataclass
class SimResult:
    trades: list[Trade]
    equity_curve: list[float]
    metrics: Metrics
    report: dict[str, Any]


class Simulator:
    def __init__(
        self,
        strategy: Strategy,
        risk_config: RiskConfig | None = None,
        fee_rate: float = 0.0001,
        slippage: float = 0.0001,
        initial_cash: float = 100000,
    ):
        self.strategy = strategy
        self.risk_manager = RiskManager(risk_config or RiskConfig())
        self.executor = SimulatedExecutor(fee_rate=fee_rate, slippage=slippage)
        self.initial_cash = initial_cash

    def run_from_df(self, df: pd.DataFrame, code: str = "SIM") -> SimResult:
        self.strategy.reset()
        trades: list[Trade] = []
        position: Optional[dict] = None
        cash = self.initial_cash
        equity_curve = [self.initial_cash]
        daily_pnl = 0.0

        for _, row in df.iterrows():
            bar = Bar(
                time=row["time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
            )

            if position is not None:
                sl_result = self.risk_manager.check_stop_loss(
                    entry_price=position["buy_price"],
                    current_price=bar.low,
                )
                if sl_result.triggered:
                    exit_price = sl_result.exit_price or bar.low
                    close_signal = Signal(
                        code=code, side=Side.SELL,
                        price=exit_price, confidence=1.0,
                        time=bar.time, reason=sl_result.reason or "stop_loss",
                    )
                    exec_result = self.executor.execute(close_signal, position, cash)
                    if exec_result.trade:
                        trades.append(exec_result.trade)
                        daily_pnl += exec_result.trade.profit
                        cash += exec_result.cash_received
                    position = None
                    equity_curve.append(self._equity(cash, position, bar.close))
                    continue

            state = {"position": position, "cash": cash, "bar": bar}
            signal = self.strategy.on_bar(bar, state)

            if signal is not None:
                signal.code = code
                if signal.side == Side.BUY and position is None:
                    max_vol_by_cash = int(cash * 0.95 / signal.price / 100) * 100
                    max_vol_by_risk = int(self.risk_manager.config.max_position_value / signal.price / 100) * 100
                    approx_volume = min(max_vol_by_cash, max_vol_by_risk)
                    if approx_volume >= 100:
                        risk_check = self.risk_manager.check_order(
                            price=signal.price, volume=approx_volume,
                            side=Side.BUY, current_position=position, daily_pnl=daily_pnl,
                        )
                        if risk_check.approved:
                            exec_result = self.executor.execute(signal, position, cash)
                            if exec_result.error is None:
                                position = exec_result.position
                                cash -= exec_result.cash_used

                elif signal.side == Side.SELL and position is not None:
                    exec_result = self.executor.execute(signal, position, cash)
                    if exec_result.trade:
                        trades.append(exec_result.trade)
                        daily_pnl += exec_result.trade.profit
                        cash += exec_result.cash_received
                    position = None

            equity_curve.append(self._equity(cash, position, bar.close))

        metrics = Metrics(trades=trades)
        report = generate_report(trades)
        return SimResult(trades=trades, equity_curve=equity_curve, metrics=metrics, report=report)

    def _equity(self, cash: float, position: Optional[dict], current_price: float) -> float:
        if position is None:
            return cash
        return cash + position["volume"] * current_price
