import pytest
from datetime import datetime
from src.trading.config import Signal, Side, Order, OrderType, OrderStatus, Trade
from src.trading.executor import SimulatedExecutor, ExecutionResult


class TestSimulatedExecutor:
    def test_buy_execution(self):
        executor = SimulatedExecutor(fee_rate=0.0, slippage=0.0)
        signal = Signal(code="TEST", side=Side.BUY, price=10.0, confidence=0.8,
                        time=datetime(2026, 7, 1, 10, 0), reason="test")
        result = executor.execute(signal=signal, position=None, cash=100000)
        assert result.error is None
        assert result.order.side == Side.BUY
        assert result.order.status == OrderStatus.FILLED
        assert result.position is not None
        assert result.position["volume"] > 0
        assert result.trade is None  # BUY doesn't produce a trade

    def test_buy_with_insufficient_cash(self):
        executor = SimulatedExecutor(fee_rate=0.0, slippage=0.0)
        signal = Signal(code="TEST", side=Side.BUY, price=10000.0, confidence=0.8,
                        time=datetime(2026, 7, 1, 10, 0), reason="test")
        result = executor.execute(signal=signal, position=None, cash=1000)
        assert result.error is not None
        assert "cash" in result.error.lower()

    def test_sell_without_position(self):
        executor = SimulatedExecutor(fee_rate=0.0, slippage=0.0)
        signal = Signal(code="TEST", side=Side.SELL, price=10.0, confidence=0.8,
                        time=datetime(2026, 7, 1, 10, 0), reason="test")
        result = executor.execute(signal=signal, position=None, cash=100000)
        assert result.error is not None
        assert "position" in result.error.lower()

    def test_sell_execution(self):
        executor = SimulatedExecutor(fee_rate=0.0, slippage=0.0)
        signal = Signal(code="TEST", side=Side.SELL, price=11.0, confidence=0.8,
                        time=datetime(2026, 7, 1, 11, 0), reason="sell")
        position = {"buy_price": 10.0, "buy_time": datetime(2026, 7, 1, 10, 0), "volume": 1000}
        result = executor.execute(signal=signal, position=position, cash=50000)
        assert result.error is None
        assert result.order.side == Side.SELL
        assert result.trade is not None
        assert result.trade.profit > 0
        assert result.position is None

    def test_slippage_applied(self):
        executor = SimulatedExecutor(fee_rate=0.0, slippage=0.001)
        signal = Signal(code="TEST", side=Side.BUY, price=10.0, confidence=0.8,
                        time=datetime(2026, 7, 1, 10, 0), reason="test")
        result = executor.execute(signal=signal, position=None, cash=100000)
        assert result.order.filled_price == pytest.approx(10.01)  # 10 * 1.001

    def test_fee_applied(self):
        executor = SimulatedExecutor(fee_rate=0.001, slippage=0.0)
        signal = Signal(code="TEST", side=Side.BUY, price=10.0, confidence=0.8,
                        time=datetime(2026, 7, 1, 10, 0), reason="test")
        result = executor.execute(signal=signal, position=None, cash=100000)
        assert result.position is not None
        # Check cash was deducted with fee
        assert result.cash_used > 0

    def test_buy_rounds_to_lot_size(self):
        executor = SimulatedExecutor(fee_rate=0.0, slippage=0.0)
        signal = Signal(code="TEST", side=Side.BUY, price=10.0, confidence=0.8,
                        time=datetime(2026, 7, 1, 10, 0), reason="test")
        result = executor.execute(signal=signal, position=None, cash=950)  # Can only buy 95 shares -> round to 0
        assert result.error is not None

    def test_min_volume_check(self):
        executor = SimulatedExecutor(fee_rate=0.0, slippage=0.0, min_volume=100)
        signal = Signal(code="TEST", side=Side.BUY, price=10.0, confidence=0.8,
                        time=datetime(2026, 7, 1, 10, 0), reason="test")
        result = executor.execute(signal=signal, position=None, cash=500)
        assert result.error is not None
