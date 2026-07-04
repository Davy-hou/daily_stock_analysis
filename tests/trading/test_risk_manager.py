import pytest
from src.trading.risk_manager import RiskManager, RiskConfig, CheckResult
from src.trading.config import Side


class TestRiskConfig:
    def test_defaults(self):
        config = RiskConfig()
        assert config.max_position_value == 50000
        assert config.max_daily_loss == 2000
        assert config.default_stop_loss_pct == 0.02


class TestRiskManager:
    def test_order_approved_when_within_limits(self):
        config = RiskConfig(max_position_value=100000, max_daily_loss=5000)
        rm = RiskManager(config)
        result = rm.check_order(price=10.0, volume=1000, side=Side.BUY, current_position=None, daily_pnl=0.0)
        assert result.approved is True
        assert result.reason is None

    def test_order_rejected_exceeds_max_position(self):
        config = RiskConfig(max_position_value=5000, max_daily_loss=5000)
        rm = RiskManager(config)
        result = rm.check_order(price=100.0, volume=1000, side=Side.BUY, current_position=None, daily_pnl=0.0)
        assert result.approved is False
        assert "max_position" in result.reason

    def test_order_rejected_exceeds_daily_loss(self):
        config = RiskConfig(max_position_value=100000, max_daily_loss=1000)
        rm = RiskManager(config)
        result = rm.check_order(price=10.0, volume=1000, side=Side.BUY, current_position=None, daily_pnl=-1500.0)
        assert result.approved is False
        assert "daily_loss" in result.reason

    def test_sell_not_checked(self):
        """Sell orders should not be blocked by risk checks"""
        config = RiskConfig(max_position_value=5000, max_daily_loss=1000)
        rm = RiskManager(config)
        result = rm.check_order(price=10.0, volume=100, side=Side.SELL, current_position={"volume": 100}, daily_pnl=-2000.0)
        assert result.approved is True

    def test_stop_loss_triggered(self):
        config = RiskConfig(default_stop_loss_pct=0.02)
        rm = RiskManager(config)
        result = rm.check_stop_loss(entry_price=100.0, current_price=97.0)
        assert result.triggered is True
        assert result.reason is not None

    def test_stop_loss_not_triggered(self):
        config = RiskConfig(default_stop_loss_pct=0.02)
        rm = RiskManager(config)
        result = rm.check_stop_loss(entry_price=100.0, current_price=99.0)
        assert result.triggered is False
        assert result.reason is None
