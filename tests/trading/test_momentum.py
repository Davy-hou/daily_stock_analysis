import pytest
from datetime import datetime, timedelta
import pandas as pd
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.momentum import MomentumStrategy
from src.trading.engine import IntradayEngine


def make_breakout_data(
    count: int,
    start_price: float = 10.0,
    uptrend: bool = True,
    breakout_at: int = 10,
) -> pd.DataFrame:
    rows = []
    dt = datetime(2026, 7, 1, 9, 31)
    price = start_price
    for i in range(count):
        direction = 1 if uptrend else -1
        if i >= breakout_at:
            direction *= 3
        rows.append({
            "time": dt,
            "open": round(price, 4),
            "high": round(price * 1.002, 4),
            "low": round(price * 0.998, 4),
            "close": round(price + direction * 0.01, 4),
            "volume": 10000,
        })
        price += direction * 0.005
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


def make_breakout_reversal_data() -> pd.DataFrame:
    """3-phase data: small uptrend, strong breakout, then reversal."""
    rows = []
    dt = datetime(2026, 7, 1, 9, 31)
    price = 10.0
    for i in range(5):
        rows.append({
            "time": dt, "open": round(price, 4), "high": round(price * 1.002, 4),
            "low": round(price * 0.998, 4), "close": round(price + 0.01, 4),
            "volume": 10000,
        })
        price += 0.005
        dt += timedelta(minutes=1)
    for i in range(8):
        rows.append({
            "time": dt, "open": round(price, 4), "high": round(price * 1.002, 4),
            "low": round(price * 0.998, 4), "close": round(price + 0.03, 4),
            "volume": 10000,
        })
        price += 0.015
        dt += timedelta(minutes=1)
    for i in range(8):
        rows.append({
            "time": dt, "open": round(price, 4), "high": round(price * 1.002, 4),
            "low": round(price * 0.998, 4), "close": round(price - 0.03, 4),
            "volume": 10000,
        })
        price -= 0.015
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


class TestMomentumStrategy:
    def test_breakout_up(self):
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        data = make_breakout_reversal_data()
        engine = IntradayEngine(fee_rate=0.0)
        result = engine.run(data, strategy)
        assert len(result.trades) > 0

    def test_no_breakout_no_trade(self):
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 1.0})
        data = make_breakout_data(30, start_price=10.0, uptrend=True, breakout_at=15)
        engine = IntradayEngine(fee_rate=0.0)
        result = engine.run(data, strategy)
        assert len(result.trades) == 0

    def test_params_validation(self):
        with pytest.raises(ValueError):
            MomentumStrategy(params={"lookback": 0})
        with pytest.raises(ValueError):
            MomentumStrategy(params={"lookback": 1})

    def test_reset_clears_state(self):
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        data = make_breakout_reversal_data()
        engine = IntradayEngine(fee_rate=0.0)
        result1 = engine.run(data, strategy)
        result2 = engine.run(data, strategy)
        assert len(result1.trades) == len(result2.trades)

    def test_breakout_down_no_trade(self):
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        data = make_breakout_data(30, start_price=10.0, uptrend=False, breakout_at=15)
        engine = IntradayEngine(fee_rate=0.0)
        result = engine.run(data, strategy)
        assert len(result.trades) == 0

    def test_close_on_exit_signal(self):
        strategy = MomentumStrategy(params={"lookback": 3, "threshold_pct": 0.02})
        engine = IntradayEngine(fee_rate=0.0)
        data = make_breakout_reversal_data()
        result = engine.run(data, strategy)
        assert len(result.trades) > 0
