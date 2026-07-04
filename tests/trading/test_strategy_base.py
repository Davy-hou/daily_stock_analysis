import pytest
from datetime import datetime
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.base import Strategy


class DummyStrategy(Strategy):
    def __init__(self):
        super().__init__(name="dummy", params={"threshold": 0.01})

    def on_bar(self, bar: Bar, state: dict) -> Signal | None:
        if bar.close > 10.0:
            return Signal(code="TEST", side=Side.BUY, price=bar.close,
                          confidence=0.6, time=bar.time, reason="above 10")
        return None


class TestStrategy:
    def test_base_instantiation(self):
        with pytest.raises(TypeError):
            Strategy()

    def test_dummy_strategy(self):
        s = DummyStrategy()
        assert s.name == "dummy"
        assert s.params == {"threshold": 0.01}

    def test_on_bar_return_signal(self):
        s = DummyStrategy()
        bar = Bar(time=datetime(2026, 7, 1, 10, 0), open=10.0, high=10.2, low=9.9, close=10.05, volume=1000)
        sig = s.on_bar(bar, {})
        assert sig is not None
        assert sig.side == Side.BUY

    def test_on_bar_no_signal(self):
        s = DummyStrategy()
        bar = Bar(time=datetime(2026, 7, 1, 10, 0), open=9.5, high=9.6, low=9.4, close=9.55, volume=1000)
        sig = s.on_bar(bar, {})
        assert sig is None
