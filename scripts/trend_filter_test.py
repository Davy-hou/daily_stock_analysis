#!/usr/bin/env python3
"""RSI(8,35,85) + 科创50 MA(20) 趋势过滤 — 用现有数据测试"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from datetime import datetime
from typing import Optional

from data_provider.intraday import MinuteDataLoader
from src.trading.strategies.rsi import RSIStrategy
from src.trading.config import Bar, Signal, Side, Trade, Metrics
from src.trading.executor import SimulatedExecutor
from src.trading.reporter import generate_report
from src.trading.risk_manager import RiskConfig, RiskManager


def load_minute_with_fallback(code: str) -> pd.DataFrame:
    """Try multiple data sources, return clean deduplicated data"""
    loader = MinuteDataLoader(source="akshare")
    dates = ["2026-07-17", "2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23"]
    parts = []
    for d in dates:
        try:
            df = loader.load(code, d)
            if df is not None and not df.empty:
                parts.append(df)
        except Exception:
            pass
    if not parts:
        return pd.DataFrame()
    combined = pd.concat(parts, ignore_index=True)
    combined = combined.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    return combined


def load_index_daily(code: str) -> pd.DataFrame:
    import akshare as ak
    df = ak.stock_zh_index_daily_em(symbol=f"sh{code}")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date")
    return df[["date", "close"]].rename(columns={"close": "idx_close"})


def simulate(df: pd.DataFrame, code: str, trend_col: Optional[str] = None) -> dict:
    strat = RSIStrategy(params={"period": 8, "oversold": 35, "overbought": 85})
    risk_mgr = RiskManager(RiskConfig(max_position_value=50000, max_daily_loss=3000, default_stop_loss_pct=0.015))
    executor = SimulatedExecutor(fee_rate=0.0001, slippage=0.0001)
    strat.reset()

    trades = []
    position = None
    cash = 100000
    equity_curve = [100000]

    for idx, row in df.iterrows():
        bar = Bar(time=row["time"], open=float(row["open"]), high=float(row["high"]),
                  low=float(row["low"]), close=float(row["close"]), volume=int(row["volume"]))

        # Stop-loss check
        if position is not None:
            sl = risk_mgr.check_stop_loss(entry_price=position["buy_price"], current_price=bar.low)
            if sl.triggered:
                sig = Signal(code=code, side=Side.SELL, price=sl.exit_price or bar.low,
                             confidence=1.0, time=bar.time, reason=sl.reason or "stop")
                r = executor.execute(sig, position, cash)
                if r.trade:
                    trades.append(r.trade)
                    cash += r.cash_received
                position = None
                equity_curve.append(cash)
                continue

        # Strategy signal
        state = {"position": position, "cash": cash, "bar": bar}
        signal = strat.on_bar(bar, state)

        # Apply trend filter (buy only)
        if signal is not None and signal.side == Side.BUY and trend_col is not None:
            if not row.get(trend_col, False):
                signal = None

        if signal is not None:
            if signal.side == Side.BUY and position is None:
                max_vol = int(cash * 0.95 / signal.price / 100) * 100
                risk_vol = int(risk_mgr.config.max_position_value / signal.price / 100) * 100
                vol = min(max_vol, risk_vol)
                if vol >= 100:
                    rc = risk_mgr.check_order(signal.price, vol, Side.BUY, None, 0)
                    if rc.approved:
                        r = executor.execute(signal, position, cash)
                        if r.error is None:
                            position = r.position
                            cash -= r.cash_used
            elif signal.side == Side.SELL and position is not None:
                r = executor.execute(signal, position, cash)
                if r.trade:
                    trades.append(r.trade)
                    cash += r.cash_received
                position = None

        equity_curve.append(cash + (position["volume"] * bar.close if position else 0))

    report = generate_report(trades)
    return {"trades": trades, "report": report, "equity_curve": equity_curve}


def main():
    CODE = "589020"
    INDEX = "000688"

    # Load index daily data
    print("1. 加载科创50日线...")
    df_idx = load_index_daily(INDEX)
    print(f"   {len(df_idx)} 天 ({df_idx['date'].iloc[0]} ~ {df_idx['date'].iloc[-1]})")

    # Load minute data
    print(f"\n2. 加载 {CODE} 分钟线...")
    df = load_minute_with_fallback(CODE)
    if df.empty:
        print("   ❌ 无数据")
        return

    print(f"   {len(df)} 条K线, {df['time'].apply(lambda t: t.date()).nunique()} 天")
    print(f"   时间范围: {df['time'].iloc[0]} ~ {df['time'].iloc[-1]}")

    # Add index data
    df["date"] = df["time"].dt.date
    df = df.merge(df_idx, on="date", how="left")

    # Compute MA on index
    df_idx_trend = df_idx.copy()
    for ma in [5, 10, 20]:
        df_idx_trend[f"ma{ma}"] = df_idx_trend["idx_close"].rolling(ma).mean()
        df_idx_trend[f"trend_ma{ma}"] = df_idx_trend["idx_close"] > df_idx_trend[f"ma{ma}"]
    df = df.merge(df_idx_trend[["date", "trend_ma5", "trend_ma10", "trend_ma20"]], on="date", how="left")

    # Show daily trend status
    print(f"\n   每日科创50趋势:")
    for d in sorted(df["date"].unique()):
        r = df[df["date"] == d].iloc[0]
        print(f"   {d}  科创50:{r['idx_close']:.0f}  MA5:{r.get('trend_ma5', '?')}  MA10:{r.get('trend_ma10', '?')}  MA20:{r.get('trend_ma20', '?')}")

    # Run comparisons
    configs = [
        ("🚫 无过滤",  None),
        ("MA5 过滤",  "trend_ma5"),
        ("MA10 过滤", "trend_ma10"),
        ("MA20 过滤", "trend_ma20"),
    ]

    print(f"\n{'='*70}")
    print(f"  RSI(8,35,85) + 科创50 趋势过滤 对比")
    print(f"{'='*70}")
    print(f"  {'配置':<20} {'交易':<6} {'胜率':<8} {'总盈亏':<12} {'收益率':<10}")
    print(f"  {'-'*56}")

    results = {}
    for label, col in configs:
        res = simulate(df, CODE, trend_col=col)
        results[label] = res
        r = res["report"]
        wr = f"{r['win_rate']:.1f}%" if r['win_rate'] else "-"
        ret = (res['equity_curve'][-1] / 100000 - 1) * 100
        print(f"  {label:<20} {r['total_trades']:<6} {wr:<8} {r['total_profit']:<12.2f} {ret:<10.2f}%")

        # Print trades for no-filter case
        if col is None:
            for i, t in enumerate(res["trades"], 1):
                print(f"     #{i} {t.buy_time.strftime('%m/%d %H:%M')} B {t.buy_price:.4f} → "
                      f"{t.sell_time.strftime('%m/%d %H:%M')} S {t.sell_price:.4f}  {t.profit:+.0f}")

    print(f"\n  ✅ 完成")


if __name__ == "__main__":
    main()
