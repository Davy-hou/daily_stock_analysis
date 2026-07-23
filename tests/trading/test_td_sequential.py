import pytest
from datetime import datetime
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.td_sequential import TDSequentialStrategy


def _bar(close: float, idx: int) -> Bar:
    return Bar(time=datetime(2026, 7, 3, 9, 30 + idx),
               open=close, high=close, low=close, close=close, volume=1000)


class TestTDSequentialStrategy:
    def test_no_trade_without_enough_bars(self):
        s = TDSequentialStrategy()
        for i in range(5):
            assert s.on_bar(_bar(10.0, i), {"code": "T"}) is None

    def _run(self, closes: list[float]) -> list[Signal]:
        s = TDSequentialStrategy()
        sigs = []
        for i, c in enumerate(closes):
            sig = s.on_bar(_bar(c, i), {"code": "T"})
            if sig:
                sigs.append(sig)
        return sigs

    def test_buy_setup_completes_entry(self):
        s = TDSequentialStrategy()
        closes = [10.5, 10.4, 10.3, 10.2, 10.1,
                  10.0, 9.9, 9.8, 9.7, 9.6,
                  9.5, 9.4, 9.3, 9.2]
        sig = None
        for i, c in enumerate(closes):
            sig = s.on_bar(_bar(c, i), {"code": "T"})
        assert sig is not None
        assert sig.side == Side.BUY
        assert s._in_position is True

    def test_buy_then_sell_completes_round_trip(self):
        s = TDSequentialStrategy()
        sigs = []
        closes = [10.5, 10.4, 10.3, 10.2, 10.1,   # warmup
                  10.0, 9.9, 9.8, 9.7, 9.6,        # buy 1-5
                  9.5, 9.4, 9.3, 9.2,              # buy 6-9 → BUY
                  9.7, 9.8, 9.9, 10.0, 10.1,       # sell 1-5
                  10.2, 10.3, 10.4, 10.5]           # sell 6-9 → SELL
        for i, c in enumerate(closes):
            sig = s.on_bar(_bar(c, i), {"code": "T"})
            if sig:
                sigs.append(sig)
        assert len(sigs) == 2
        assert sigs[0].side == Side.BUY
        assert sigs[1].side == Side.SELL
        assert s._in_position is False

    def test_sell_setup_ignored_when_not_in_position(self):
        s = TDSequentialStrategy()
        closes = [5.0, 5.1, 5.2, 5.3, 5.4,
                  5.5, 5.6, 5.7, 5.8, 5.9,
                  6.0, 6.1, 6.2, 6.3]
        sig = None
        for i, c in enumerate(closes):
            sig = s.on_bar(_bar(c, i), {"code": "T"})
        assert sig is None
        assert s._in_position is False

    def test_setup_resets_on_condition_fail(self):
        s = TDSequentialStrategy()
        closes = [10.5, 10.4, 10.3, 10.2, 10.1,
                  10.0, 9.9, 9.8, 9.7, 20.0,
                  9.9, 9.8, 9.7, 9.6]
        for i, c in enumerate(closes):
            s.on_bar(_bar(c, i), {"code": "T"})
        assert s._buy_count < 9
        assert s._sell_count < 9
        assert s._in_position is False

    def test_setup_resets_after_signal(self):
        s = TDSequentialStrategy()
        closes = [10.5, 10.4, 10.3, 10.2, 10.1,
                  10.0, 9.9, 9.8, 9.7, 9.6,
                  9.5, 9.4, 9.3, 9.2,
                  9.1, 9.0, 8.9, 8.8, 8.7]
        for i, c in enumerate(closes):
            s.on_bar(_bar(c, i), {"code": "T"})
        assert s._buy_count == 5
        assert s._in_position is True

    def test_reset_clears_state(self):
        s = TDSequentialStrategy()
        closes = [10.5, 10.4, 10.3, 10.2, 10.1,
                  10.0, 9.9, 9.8, 9.7, 9.6,
                  9.5, 9.4, 9.3, 9.2]
        for i, c in enumerate(closes):
            s.on_bar(_bar(c, i), {"code": "T"})
        s.reset()
        assert s._buy_count == 0
        assert s._sell_count == 0
        assert s._in_position is False

    def test_custom_period(self):
        s = TDSequentialStrategy(params={"period": 2})
        assert s._period == 2
        closes = [3.0, 3.0, 3.0,
                  2.9, 2.8, 2.7,
                  2.6, 2.5, 2.4,
                  2.3, 2.2, 2.1]
        for i, c in enumerate(closes):
            sig = s.on_bar(_bar(c, i), {"code": "T"})
        assert sig is not None
        assert sig.side == Side.BUY

    def test_invalid_period(self):
        with pytest.raises(ValueError, match="period must be >= 1"):
            TDSequentialStrategy(params={"period": 0})
