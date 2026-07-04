import pytest
from datetime import datetime, timedelta
import pandas as pd
from src.trading.engine import IntradayEngine
from src.trading.strategies.momentum import MomentumStrategy
from src.trading.reporter import generate_report
from src.trading.config import Metrics


def simulate_etf_day() -> pd.DataFrame:
    """模拟纳指ETF一个交易日的分钟线数据（震荡上行+尾盘回落）"""
    rows = []
    dt = datetime(2026, 7, 1, 9, 30)
    price = 1.500
    for i in range(240):
        change = 0.0
        if 30 <= i < 60:
            change = 0.002
        elif 90 <= i < 120:
            change = 0.003
        elif 150 <= i < 180:
            change = -0.001
        elif 210 <= i < 240:
            change = 0.001
        price += change
        rows.append({
            "time": dt,
            "open": round(price, 4),
            "high": round(price * 1.001, 4),
            "low": round(price * 0.999, 4),
            "close": round(price, 4),
            "volume": 50000 + int(i * 100),
        })
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


class TestIntegration:
    def test_full_backtest_run(self):
        data = simulate_etf_day()
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        engine = IntradayEngine(fee_rate=0.0001, slippage=0.0001)
        result = engine.run(data, strategy)

        assert len(result.equity_curve) == len(data) + 1
        assert result.equity_curve[0] == 100000
        assert isinstance(result.metrics, Metrics)
        assert result.metrics.total_trades >= 0

        report = generate_report(result.trades)
        assert report["total_trades"] == result.metrics.total_trades

    def test_multiple_param_sets(self):
        data = simulate_etf_day()
        params_list = [
            {"lookback": 3, "threshold_pct": 0.03},
            {"lookback": 5, "threshold_pct": 0.05},
            {"lookback": 10, "threshold_pct": 0.1},
        ]
        results = []
        for params in params_list:
            strategy = MomentumStrategy(params=params)
            engine = IntradayEngine(fee_rate=0.0001)
            result = engine.run(data, strategy)
            results.append((params, result.metrics))

        assert len(results) == 3
        for params, metrics in results:
            assert metrics.total_trades >= 0

    def test_different_fee_rates(self):
        data = simulate_etf_day()
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        rates = [0.0, 0.0001, 0.0003]
        profits = []
        for rate in rates:
            engine = IntradayEngine(fee_rate=rate)
            result = engine.run(data, strategy)
            profits.append(result.metrics.total_profit)

        assert profits[0] >= profits[1] >= profits[2]

    def test_reporter_from_engine_output(self):
        data = simulate_etf_day()
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        engine = IntradayEngine(fee_rate=0.0001)
        result = engine.run(data, strategy)

        report = generate_report(result.trades)
        assert report["total_trades"] == len(result.trades)
        if report["total_trades"] > 0:
            assert report["win_rate"] is not None
            assert isinstance(report["per_trade"], list)
            assert len(report["per_trade"]) == report["total_trades"]
            first = report["per_trade"][0]
            for key in ("code", "buy_price", "sell_price", "profit", "return_pct", "hold_minutes"):
                assert key in first
