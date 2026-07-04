import pytest
from datetime import datetime, timedelta
import pandas as pd
from src.trading.simulator import Simulator
from src.trading.strategies.momentum import MomentumStrategy
from src.trading.risk_manager import RiskConfig
from data_provider.intraday import MinuteDataLoader


def simulate_trading_day(
    start_price: float = 1.500,
    volatility: float = 0.003,
    trend: float = 0.0001,
) -> pd.DataFrame:
    """模拟一个完整的交易日分钟线，带趋势和随机波动"""
    import random
    random.seed(42)
    rows = []
    dt = datetime(2026, 7, 1, 9, 30)
    price = start_price
    for i in range(240):
        change = random.gauss(trend, volatility)
        price += change
        price = max(price, start_price * 0.95)
        rows.append({
            "time": dt,
            "open": round(price, 4),
            "high": round(price * (1 + abs(change) * 0.5), 4),
            "low": round(price * (1 - abs(change) * 0.5), 4),
            "close": round(price, 4),
            "volume": int(50000 + random.gauss(0, 10000)),
        })
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


class TestSimIntegration:
    def test_full_sim_pipeline(self):
        df = simulate_trading_day()
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        risk_config = RiskConfig(max_position_value=100000, max_daily_loss=5000)
        sim = Simulator(strategy=strategy, risk_config=risk_config, fee_rate=0.0001, slippage=0.0001)
        result = sim.run_from_df(df, code="513100")

        # Verify all outputs exist
        assert isinstance(result.trades, list)
        assert len(result.equity_curve) == len(df) + 1
        assert result.report["total_trades"] == len(result.trades)
        assert result.equity_curve[0] == 100000

    def test_multiple_strategies(self):
        df = simulate_trading_day()
        configs = [
            (MomentumStrategy(params={"lookback": 3, "threshold_pct": 0.03}),
             RiskConfig(max_position_value=50000, max_daily_loss=3000)),
            (MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05}),
             RiskConfig(max_position_value=80000, max_daily_loss=5000)),
            (MomentumStrategy(params={"lookback": 10, "threshold_pct": 0.10}),
             RiskConfig(max_position_value=100000, max_daily_loss=10000)),
        ]
        results = []
        for strategy, risk_config in configs:
            sim = Simulator(strategy=strategy, risk_config=risk_config)
            result = sim.run_from_df(df)
            results.append(result)
            assert result.metrics.total_trades >= 0

        assert len(results) == 3

    def test_data_loader_compatible(self):
        """Verify MinuteDataLoader output format is compatible with Simulator"""
        loader = MinuteDataLoader(source="standard")
        df = pd.DataFrame({
            "time": [datetime(2026, 7, 1, 9, 31), datetime(2026, 7, 1, 9, 32)],
            "open": [1.5, 1.501],
            "high": [1.502, 1.503],
            "low": [1.498, 1.499],
            "close": [1.501, 1.502],
            "volume": [50000, 52000],
        })
        standardized = loader.load_from_df(df)
        strategy = MomentumStrategy(params={"lookback": 2, "threshold_pct": 0.1})
        sim = Simulator(strategy=strategy, risk_config=RiskConfig())
        result = sim.run_from_df(standardized, code="513100")
        assert result.metrics.total_trades >= 0

    def test_trade_details_consistency(self):
        df = simulate_trading_day(start_price=1.5, volatility=0.005, trend=0.0002)
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        sim = Simulator(strategy=strategy, risk_config=RiskConfig())
        result = sim.run_from_df(df, code="513100")

        for trade in result.trades:
            assert trade.buy_price > 0
            assert trade.sell_price > 0
            assert trade.volume > 0
            assert trade.sell_time > trade.buy_time
            assert trade.code == "513100"
