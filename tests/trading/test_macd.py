import pytest
from datetime import datetime
from src.trading.config import Bar, Side
from src.trading.strategies.macd import MACDStrategy


def _bar(close: float, idx: int) -> Bar:
    t = datetime(2026, 7, 3, 9, 30) + __import__("datetime").timedelta(minutes=idx)
    return Bar(time=t, open=close, high=close, low=close, close=close, volume=1000)


class TestMACDStrategy:
    def test_requires_warmup(self):
        s = MACDStrategy()
        for i in range(26):
            assert s.on_bar(_bar(10.0, i), {"code": "T"}) is None

    def test_invalid_periods(self):
        with pytest.raises(ValueError, match="slow"):
            MACDStrategy(params={"fast": 26, "slow": 12})
        with pytest.raises(ValueError, match=">= 1"):
            MACDStrategy(params={"fast": 0})

    def test_golden_cross_generates_buy(self):
        s = MACDStrategy(params={"fast": 5, "slow": 10, "signal": 3})
        sig = None
        for i in range(50):
            close = 10.0 + (i * 0.02)
            sig = s.on_bar(_bar(close, i), {"code": "T"})
            if sig:
                break
        assert sig is not None
        assert sig.side == Side.BUY
        assert "金叉" in sig.reason

    def test_golden_then_dead_cross_completes_trade(self):
        s = MACDStrategy(params={"fast": 5, "slow": 10, "signal": 3})
        sigs = []
        for i in range(120):
            if i < 30:
                close = 10.0 - (i * 0.02)
            elif i < 80:
                close = 9.4 + ((i - 30) * 0.04)
            else:
                close = 11.4 - ((i - 80) * 0.04)
            sig = s.on_bar(_bar(close, i), {"code": "T"})
            if sig:
                sigs.append(sig)
        assert len(sigs) == 2
        assert sigs[0].side == Side.BUY
        assert sigs[1].side == Side.SELL

    def test_reset_clears_state(self):
        s = MACDStrategy(params={"fast": 5, "slow": 10, "signal": 3})
        for i in range(60):
            close = 10.0 + (i * 0.02)
            s.on_bar(_bar(close, i), {"code": "T"})
        s.reset()
        assert s._in_position is False
        assert s._ema_fast is None
        assert s._bars == 0

    def test_no_signal_in_flat_market(self):
        s = MACDStrategy(params={"fast": 5, "slow": 10, "signal": 3})
        sigs = []
        for i in range(100):
            sig = s.on_bar(_bar(10.0, i), {"code": "T"})
            if sig:
                sigs.append(sig)
        assert len(sigs) == 0

    def test_custom_params(self):
        s = MACDStrategy(params={"fast": 3, "slow": 7, "signal": 2})
        assert s._fast == 3
        assert s._slow == 7
        assert s._signal == 2
