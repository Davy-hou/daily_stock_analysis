import pytest
from datetime import datetime
from src.trading.config import Bar, Signal, Trade, Metrics, Side


class TestBar:
    def test_create(self):
        bar = Bar(
            time=datetime(2026, 7, 1, 9, 31),
            open=10.0, high=10.1, low=9.95, close=10.05,
            volume=10000
        )
        assert bar.time == datetime(2026, 7, 1, 9, 31)
        assert bar.close == 10.05


class TestSignal:
    def test_buy_signal(self):
        sig = Signal(code="513100.XSHG", side=Side.BUY, price=1.5, confidence=0.8, time=datetime(2026, 7, 1, 10, 0))
        assert sig.side == Side.BUY
        assert sig.code == "513100.XSHG"


class TestTrade:
    def test_profit(self):
        trade = Trade(
            code="513100.XSHG",
            buy_time=datetime(2026, 7, 1, 10, 0),
            buy_price=1.5,
            sell_time=datetime(2026, 7, 1, 14, 0),
            sell_price=1.52,
            volume=1000,
            fee=2.0
        )
        assert trade.profit == pytest.approx(18.0)


class TestMetrics:
    def test_empty(self):
        m = Metrics(trades=[])
        assert m.total_trades == 0
        assert m.win_rate is None

    def test_with_trades(self):
        trades = [
            Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
                  sell_time=datetime(2026,7,1,14,0), sell_price=11.0,
                  volume=100, fee=1.0),
            Trade(code="A", buy_time=datetime(2026,7,1,10,30), buy_price=10.0,
                  sell_time=datetime(2026,7,1,14,30), sell_price=9.0,
                  volume=100, fee=1.0),
        ]
        m = Metrics(trades=trades)
        assert m.total_trades == 2
        assert m.win_rate == 50.0
