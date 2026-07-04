import pytest
from datetime import datetime, timedelta
import pandas as pd
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.base import Strategy
from src.trading.strategies.momentum import MomentumStrategy
from src.trading.risk_manager import RiskConfig
from src.trading.simulator import Simulator


def make_minute_bars(count: int, price_series: list[float] | None = None) -> pd.DataFrame:
    if price_series is None:
        price_series = [10.0 + i * 0.02 for i in range(count)]
    rows = []
    dt = datetime(2026, 7, 1, 9, 31)
    for p in price_series:
        rows.append({
            "time": dt, "open": p, "high": p * 1.002, "low": p * 0.998,
            "close": p, "volume": 10000,
        })
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


class TestSimulator:
    def test_run_no_trades(self):
        class NoOp(Strategy):
            def __init__(self):
                super().__init__(name="noop")
            def on_bar(self, bar, state):
                return None

        sim = Simulator(strategy=NoOp(), risk_config=RiskConfig())
        result = sim.run_from_df(make_minute_bars(10), code="TEST")
        assert len(result.trades) == 0
        assert len(result.equity_curve) > 0
        assert result.report["total_trades"] == 0

    def test_run_with_momentum(self):
        prices = [10.0] * 10 + [10.05, 10.10, 10.15, 10.20, 10.25, 10.20, 10.15, 10.05, 9.95, 9.85]
        df = make_minute_bars(len(prices), prices)

        strategy = MomentumStrategy(params={"lookback": 3, "threshold_pct": 0.02})
        risk_config = RiskConfig(max_position_value=100000, max_daily_loss=5000)
        sim = Simulator(strategy=strategy, risk_config=risk_config)
        result = sim.run_from_df(df, code="TEST")

        assert result.metrics.total_trades > 0
        assert result.report["total_trades"] == result.metrics.total_trades

    def test_risk_blocks_trade(self):
        strategy = MomentumStrategy(params={"lookback": 3, "threshold_pct": 0.02})
        risk_config = RiskConfig(max_position_value=100, max_daily_loss=100)
        sim = Simulator(strategy=strategy, risk_config=risk_config)
        prices = [10.0] * 10 + [10.05, 10.10, 10.15, 10.20, 10.25]
        df = make_minute_bars(len(prices), prices)
        result = sim.run_from_df(df, code="TEST")
        assert len(result.trades) == 0

    def test_equity_curve_records_each_bar(self):
        sim = Simulator(strategy=MomentumStrategy(), risk_config=RiskConfig())
        df = make_minute_bars(20)
        result = sim.run_from_df(df, code="TEST")
        assert len(result.equity_curve) == len(df) + 1
        assert result.equity_curve[0] == sim.initial_cash

    def test_stop_loss_triggered(self):
        strategy = MomentumStrategy(params={"lookback": 3, "threshold_pct": 0.01})
        risk_config = RiskConfig(max_position_value=100000, max_daily_loss=5000, default_stop_loss_pct=0.01)
        sim = Simulator(strategy=strategy, risk_config=risk_config)
        prices = [10.0] * 5 + [10.05, 10.10, 10.15, 10.20, 10.25, 9.90, 9.80, 9.70, 9.60]
        df = make_minute_bars(len(prices), prices)
        result = sim.run_from_df(df, code="TEST")
        assert len(result.trades) > 0

    def test_report_keys(self):
        sim = Simulator(strategy=MomentumStrategy(), risk_config=RiskConfig())
        df = make_minute_bars(30)
        result = sim.run_from_df(df, code="TEST")
        required = {"total_trades", "win_rate", "total_profit", "sharpe_ratio", "max_drawdown_pct"}
        assert required.issubset(result.report.keys())
