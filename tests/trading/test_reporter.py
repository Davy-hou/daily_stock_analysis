import pytest
from datetime import datetime
from src.trading.config import Trade
from src.trading.reporter import generate_report


def test_generate_report_empty():
    report = generate_report([])
    assert report["total_trades"] == 0

def test_generate_report_with_trades():
    trades = [
        Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
              sell_time=datetime(2026,7,1,10,30), sell_price=10.5,
              volume=1000, fee=3.0),
        Trade(code="A", buy_time=datetime(2026,7,1,11,0), buy_price=10.0,
              sell_time=datetime(2026,7,1,11,20), sell_price=9.8,
              volume=1000, fee=3.0),
    ]
    report = generate_report(trades)
    assert report["total_trades"] == 2
    assert report["win_rate"] == 50.0
    assert report["total_profit"] == pytest.approx(294.0)
    assert "avg_hold_minutes" in report
    assert "per_trade" in report

def test_report_contains_all_keys():
    trades = [
        Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
              sell_time=datetime(2026,7,1,10,30), sell_price=10.5,
              volume=1000, fee=3.0),
    ]
    report = generate_report(trades)
    expected_keys = {"total_trades", "win_trades", "loss_trades", "win_rate",
                     "total_profit", "profit_factor", "sharpe_ratio",
                     "max_drawdown_pct", "avg_hold_minutes", "per_trade"}
    assert expected_keys.issubset(report.keys())

def test_per_trade_detail():
    trades = [
        Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
              sell_time=datetime(2026,7,1,11,0), sell_price=11.0,
              volume=100, fee=1.0),
    ]
    report = generate_report(trades)
    detail = report["per_trade"][0]
    assert detail["code"] == "A"
    assert detail["volume"] == 100
    assert detail["return_pct"] == pytest.approx(10.0)
