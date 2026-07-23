import pytest
from datetime import datetime
from src.trading.config import Bar, Side
from src.trading.strategies.rsi import RSIStrategy


def _bar(close: float, idx: int) -> Bar:
    t = datetime(2026, 7, 3, 9, 30) + __import__("datetime").timedelta(minutes=idx)
    return Bar(time=t, open=close, high=close, low=close, close=close, volume=1000)


class TestRSIStrategy:
    def test_requires_warmup(self):
        s = RSIStrategy()
        for i in range(15):
            assert s.on_bar(_bar(10.0, i), {"code": "T"}) is None

    def test_invalid_period(self):
        with pytest.raises(ValueError, match=">= 1"):
            RSIStrategy(params={"period": 0})

    def test_invalid_thresholds(self):
        with pytest.raises(ValueError, match="oversold"):
            RSIStrategy(params={"oversold": 70, "overbought": 30})

    def test_oversold_generates_buy(self):
        s = RSIStrategy(params={"period": 5, "oversold": 30, "overbought": 70})
        sig = None
        for i in range(60):
            close = 10.0 - (i * 0.3)
            sig = s.on_bar(_bar(max(close, 1.0), i), {"code": "T"})
            if sig:
                break
        assert sig is not None
        assert sig.side == Side.BUY

    def test_oversold_then_overbought_completes_trade(self):
        s = RSIStrategy(params={"period": 5, "oversold": 30, "overbought": 70})
        sigs = []
        for i in range(200):
            if i < 40:
                close = 10.0 - (i * 0.25)
            elif i < 80:
                close = 1.0 + ((i - 40) * 0.3)
            elif i < 120:
                close = 13.0 - ((i - 80) * 0.25)
            else:
                close = 3.0
            sig = s.on_bar(_bar(max(close, 0.5), i), {"code": "T"})
            if sig:
                sigs.append(sig)
        found_buy = any(s.side == Side.BUY for s in sigs)
        found_sell = any(s.side == Side.SELL for s in sigs)
        assert found_buy and found_sell

    def test_flat_market_no_signal(self):
        s = RSIStrategy(params={"period": 5, "oversold": 30, "overbought": 70})
        sigs = []
        for i in range(100):
            sig = s.on_bar(_bar(10.0, i), {"code": "T"})
            if sig:
                sigs.append(sig)
        assert len(sigs) == 0

    def test_reset_clears_state(self):
        s = RSIStrategy(params={"period": 5})
        for i in range(60):
            close = 10.0 - (i * 0.3)
            s.on_bar(_bar(max(close, 1.0), i), {"code": "T"})
        s.reset()
        assert s._in_position is False
        assert s._prev_close is None

    def test_custom_params(self):
        s = RSIStrategy(params={"period": 7, "oversold": 25, "overbought": 75})
        assert s._period == 7
        assert s._oversold == 25
        assert s._overbought == 75
