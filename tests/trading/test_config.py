import pytest
from datetime import datetime
from src.trading.config import Bar, Signal, Trade, Metrics, Side, Order, OrderType, OrderStatus


class TestBar:
    def test_create(self):
        bar = Bar(
            time=datetime(2026, 7, 1, 9, 31),
            open=10.0, high=10.1, low=9.95, close=10.05,
            volume=10000
        )
        assert bar.time == datetime(2026, 7, 1, 9, 31)
        assert bar.close == 10.05
        assert bar.volume == 10000


class TestSignal:
    def test_buy_signal(self):
        sig = Signal(code="513100.XSHG", side=Side.BUY, price=1.5, confidence=0.8, time=datetime(2026, 7, 1, 10, 0))
        assert sig.side == Side.BUY
        assert sig.code == "513100.XSHG"


class TestOrder:
    def test_market_order_defaults(self):
        o = Order(code="513100.XSHG", side=Side.BUY, price=1.5, volume=1000)
        assert o.status == OrderStatus.PENDING
        assert o.order_type == OrderType.MARKET

    def test_limit_order(self):
        o = Order(code="513100.XSHG", side=Side.SELL, price=1.55, volume=500, order_type=OrderType.LIMIT)
        assert o.order_type == OrderType.LIMIT


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

    def test_return_pct(self):
        trade = Trade(
            code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
            sell_time=datetime(2026,7,1,14,0), sell_price=11.0,
            volume=100, fee=1.0
        )
        assert trade.return_pct == pytest.approx(10.0)

    def test_duration_minutes(self):
        trade = Trade(
            code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
            sell_time=datetime(2026,7,1,14,30), sell_price=11.0,
            volume=100, fee=1.0
        )
        assert trade.duration_minutes == pytest.approx(270.0)


class TestMetrics:
    def test_empty(self):
        m = Metrics(trades=[])
        assert m.total_trades == 0
        assert m.win_rate is None
        assert m.profit_factor is None
        assert m.sharpe_ratio is None
        assert m.max_drawdown_pct is None
        assert m.total_profit == 0.0

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
        assert m.win_trades == 1
        assert m.loss_trades == 1
        assert m.win_rate == 50.0

    def test_loss_trades_excludes_breakeven(self):
        trades = [
            Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
                  sell_time=datetime(2026,7,1,14,0), sell_price=10.0,
                  volume=100, fee=0.0),
        ]
        m = Metrics(trades=trades)
        assert m.win_trades == 0
        assert m.loss_trades == 0

    def test_profit_factor_all_win(self):
        trades = [
            Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
                  sell_time=datetime(2026,7,1,14,0), sell_price=11.0,
                  volume=100, fee=1.0),
        ]
        m = Metrics(trades=trades)
        assert m.profit_factor is None

    def test_max_drawdown_with_profits_and_losses(self):
        trades = [
            Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
                  sell_time=datetime(2026,7,1,10,30), sell_price=12.0,
                  volume=100, fee=0.0),
            Trade(code="A", buy_time=datetime(2026,7,1,10,31), buy_price=12.0,
                  sell_time=datetime(2026,7,1,11,0), sell_price=8.0,
                  volume=100, fee=0.0),
        ]
        m = Metrics(trades=trades)
        # cumulative: +200 -> -200, peak=200, dd=(200-(-200))/200=2.0=200%
        assert m.max_drawdown_pct == 200.0

    def test_single_trade_no_sharpe(self):
        trades = [
            Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
                  sell_time=datetime(2026,7,1,14,0), sell_price=11.0,
                  volume=100, fee=1.0),
        ]
        m = Metrics(trades=trades)
        assert m.sharpe_ratio is None
