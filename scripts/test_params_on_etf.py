#!/usr/bin/env python3
"""在指定 ETF 上测试特定 RSI 参数组合"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from datetime import datetime
from data_provider.intraday import MinuteDataLoader
from src.trading.simulator import Simulator
from src.trading.strategies.rsi import RSIStrategy
from src.trading.risk_manager import RiskConfig

# 源自 589020 的最佳参数
PARAMS_589020 = [
    (13, 25, 85, "589020 #1 最佳"),
    (20, 25, 80, "589020 #8 低回撤"),
    (15, 20, 85, "589020 #9 低回撤"),
]
# 源自 513050 的最佳参数
PARAMS_513050 = [
    (15, 35, 65, "513050 #1 最佳"),
    (14, 35, 75, "513050 #5 低回撤"),
    (9, 25, 85, "513050 #6 零回撤"),
]

DATES = ["2026-07-03", "2026-07-02", "2026-07-01", "2026-06-30", "2026-06-29",
         "2026-06-26", "2026-06-25", "2026-06-24", "2026-06-23", "2026-06-22",
         "2026-06-19", "2026-06-18", "2026-06-17", "2026-06-16", "2026-06-15",
         "2026-06-12", "2026-06-11", "2026-06-10", "2026-06-09", "2026-06-08"]

ETFS = {"513750": "港股非银ETF"}


def load_all_pytdx_data(code: str) -> pd.DataFrame:
    from pytdx.hq import TdxHq_API
    category = 8
    market = 1 if code[0] in ("5", "6") else 0
    servers = [("60.191.117.167", 7709), ("119.147.212.81", 7709), ("47.94.80.90", 7709)]
    api = TdxHq_API()
    connected = False
    for host, port in servers:
        try:
            if api.connect(host, port, time_out=3):
                connected = True
                break
        except Exception:
            continue
    if not connected:
        raise RuntimeError("Cannot connect to PyTDX")
    rows = []
    for off in range(30):
        chunk = api.get_security_bars(category, market, code, off * 240, 240)
        if not chunk:
            break
        rows.extend(chunk)
    api.disconnect()
    if not rows:
        return pd.DataFrame()
    loader = MinuteDataLoader(source="pytdx")
    return loader.load_from_df(pd.DataFrame(rows), source="pytdx")


def run_test(code: str, name: str, params_list: list, all_params: bool = False):
    target_dates = set(pd.to_datetime(DATES).date)

    print(f"\n{'='*70}")
    print(f"  {name} ({code}) — 加载数据...")
    sys.stdout.flush()
    df = load_all_pytdx_data(code)
    if df.empty:
        print("  ❌ 无数据")
        return

    df = df[df["time"].dt.date.isin(target_dates)].copy()
    days = df["time"].apply(lambda t: t.date()).nunique()
    print(f"  加载完成: {len(df)} bars, {days} 天数据")
    sys.stdout.flush()

    # 如果 all_params=True 且 params_list 为空，扫描全部
    if all_params and not params_list:
        from itertools import product
        params_list = [(p, os_, ob, f"RSI({p},{os_},{ob})")
                       for p in range(5, 21)
                       for os_ in range(15, 46, 5)
                       for ob in range(55, 86, 5) if os_ < ob]

    results = []
    for period, oversold, overbought, label in params_list:
        strat = RSIStrategy(params={
            "period": period, "oversold": oversold, "overbought": overbought,
        })
        sim = Simulator(
            strategy=strat,
            risk_config=RiskConfig(
                max_position_value=50000, max_daily_loss=3000,
                default_stop_loss_pct=0.015,
            ),
        )
        result = sim.run_from_df(df, code=code)
        r = result.report
        results.append({
            "label": label, "period": period, "oversold": oversold, "overbought": overbought,
            "trades": r["total_trades"], "win_rate": r.get("win_rate"),
            "total_profit": r["total_profit"],
            "profit_factor": r.get("profit_factor"),
            "sharpe": r.get("sharpe_ratio"), "mdd": r.get("max_drawdown_pct"),
        })

    df_r = pd.DataFrame(results).sort_values("total_profit", ascending=False)

    print(f"\n  {'='*70}")
    print(f"  {name} ({code}) — RSI 参数测试结果")
    print(f"  {'='*70}")
    header = f"  {'#':<4} {'标签':<24} {'Per':<5} {'OS':<5} {'OB':<5} {'交易':<6} {'Win%':<8} {'总盈亏':<12} {'盈亏比':<8} {'夏普':<8} {'MDD%':<8}"
    print(header)
    print(f"  {'-'*66}")
    for rank, (_, row) in enumerate(df_r.iterrows(), 1):
        wr = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "-"
        pf = f"{row['profit_factor']:.2f}" if pd.notna(row['profit_factor']) else "-"
        sp = f"{row['sharpe']:.3f}" if pd.notna(row['sharpe']) else "-"
        md = f"{row['mdd']:.2f}%" if pd.notna(row['mdd']) else "-"
        print(f"  {rank:<4} {row['label']:<24} {int(row['period']):<5} {int(row['oversold']):<5} {int(row['overbought']):<5} {int(row['trades']):<6} {wr:<8} {row['total_profit']:<12.2f} {pf:<8} {sp:<8} {md:<8}")


def main():
    for code, name in ETFS.items():
        # 先用 589020 的参数
        print(f"\n{'~'*70}")
        print(f"  Part 1: 用 589020 最佳参数测试 {name}")
        run_test(code, name, PARAMS_589020)

        # 再用 513050 的参数
        print(f"\n{'~'*70}")
        print(f"  Part 2: 用 513050 最佳参数测试 {name}")
        run_test(code, name, PARAMS_513050)

    print("\n  ✅ 测试完成")


if __name__ == "__main__":
    main()
