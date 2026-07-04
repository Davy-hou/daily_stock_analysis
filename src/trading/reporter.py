from __future__ import annotations

from typing import Any
from src.trading.config import Trade, Metrics


def generate_report(trades: list[Trade]) -> dict[str, Any]:
    metrics = Metrics(trades=trades)
    report = {
        "total_trades": metrics.total_trades,
        "win_trades": metrics.win_trades,
        "loss_trades": metrics.loss_trades,
        "win_rate": metrics.win_rate,
        "total_profit": metrics.total_profit,
        "profit_factor": metrics.profit_factor,
        "sharpe_ratio": metrics.sharpe_ratio,
        "max_drawdown_pct": metrics.max_drawdown_pct,
    }
    if trades:
        durations = [t.duration_minutes for t in trades]
        report["avg_hold_minutes"] = sum(durations) / len(durations)
        report["max_hold_minutes"] = max(durations)
        report["min_hold_minutes"] = min(durations)
        report["per_trade"] = [
            {
                "code": t.code,
                "buy_time": t.buy_time.isoformat(),
                "sell_time": t.sell_time.isoformat(),
                "buy_price": round(t.buy_price, 4),
                "sell_price": round(t.sell_price, 4),
                "volume": t.volume,
                "profit": round(t.profit, 2),
                "return_pct": round(t.return_pct, 4),
                "hold_minutes": round(t.duration_minutes, 1),
            }
            for t in trades
        ]
    return report
