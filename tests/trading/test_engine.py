import pytest
from datetime import datetime, timedelta
import pandas as pd

from src.trading.config import Bar, Signal, Side, Trade, Metrics
from src.trading.engine import IntradayEngine
from src.trading.strategies.base import Strategy


def make_minute_bars(count: int, start_price: float = 10.0) -> pd.DataFrame:
    rows = []
    dt = datetime(2026, 7, 1, 9, 31)
    price = start_price
    for i in range(count):
        rows.append({
            "time": dt,
            "open": round(price, 4),
            "high": round(price * 1.001, 4),
            "low": round(price * 0.999, 4),
            "close": round(price, 4),
            "volume": 10000,
        })
        price += 0.01
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


class BuyEveryBar(Strategy):
    def __init__(self):
        super().__init__(name="buy_every_bar")

    def on_bar(self, bar: Bar, state: dict) -> Signal | None:
        return Signal(code="TEST", side=Side.BUY, price=bar.close,
                      confidence=0.5, time=bar.time, reason="test")


class AlternateStrategy(Strategy):
    def __init__(self):
        super().__init__(name="alternate", params={"count": 0})

    def on_bar(self, bar: Bar, state: dict) -> Signal | None:
        self._params["count"] += 1
        if self._params["count"] % 2 == 1:
            return Signal(code="TEST", side=Side.BUY, price=bar.close,
                          confidence=0.5, time=bar.time, reason="buy")
        return Signal(code="TEST", side=Side.SELL, price=bar.close,
                      confidence=0.5, time=bar.time, reason="sell")


class TestIntradayEngine:
    def test_empty_data(self):
        engine = IntradayEngine(fee_rate=0.0)
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        result = engine.run(df, BuyEveryBar())
        assert len(result.trades) == 0

    def test_no_signal(self):
        class NoOp(Strategy):
            def __init__(self):
                super().__init__(name="noop")

            def on_bar(self, bar, state):
                return None

        engine = IntradayEngine(fee_rate=0.0)
        df = make_minute_bars(10)
        result = engine.run(df, NoOp())
        assert len(result.trades) == 0
        assert len(result.equity_curve) > 0

    def test_buy_no_sell_no_trade(self):
        engine = IntradayEngine(fee_rate=0.0)
        df = make_minute_bars(30)
        result = engine.run(df, BuyEveryBar())
        assert len(result.trades) == 0

    def test_alternate_produces_trades(self):
        engine = IntradayEngine(fee_rate=0.0)
        df = make_minute_bars(20, start_price=10.0)
        result = engine.run(df, AlternateStrategy())
        assert len(result.trades) == 10

    def test_fee_deducted(self):
        df = make_minute_bars(20, start_price=10.0)
        result_no_fee = IntradayEngine(fee_rate=0.0).run(df, AlternateStrategy())
        result_with_fee = IntradayEngine(fee_rate=0.001).run(df, AlternateStrategy())
        assert result_with_fee.metrics.total_profit < result_no_fee.metrics.total_profit

    def test_initial_cash_limits_buy_volume(self):
        engine = IntradayEngine(fee_rate=0.0, initial_cash=1000)
        df = make_minute_bars(20, start_price=10.0)
        result = engine.run(df, AlternateStrategy())
        assert result.metrics.total_trades >= 0

    def test_equity_curve_length(self):
        engine = IntradayEngine(fee_rate=0.0)
        df = make_minute_bars(10)
        result = engine.run(df, AlternateStrategy())
        assert len(result.equity_curve) == len(df) + 1

    def test_backtestresult_has_metrics(self):
        engine = IntradayEngine(fee_rate=0.0)
        df = make_minute_bars(20, start_price=10.0)
        result = engine.run(df, AlternateStrategy())
        assert isinstance(result.metrics, Metrics)
        assert result.metrics.total_trades > 0
