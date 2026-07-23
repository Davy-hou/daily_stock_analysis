#!/usr/bin/env python3
"""RSI 参数网格扫描 V2 — 全量 31 天 + 前后半段交叉验证"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from itertools import product
import pandas as pd
from datetime import datetime

from data_provider.intraday import MinuteDataLoader
from src.trading.simulator import Simulator
from src.trading.strategies.rsi import RSIStrategy
from src.trading.risk_manager import RiskConfig

ETFS = {
    "589020": "科创半导体",
    "513050": "中概互联",
    "513750": "港股非银ETF",
}
PERIODS = list(range(5, 21))
OVERSOLD = list(range(15, 46, 5))
OVERBOUGHT = list(range(55, 86, 5))


def load_all_pytdx_data(code: str) -> pd.DataFrame:
    from pytdx.hq import TdxHq_API
    category = 8
    market = 1 if code[0] in ("5", "6") else 0
    servers = [("60.191.117.167", 7709), ("119.147.212.81", 7709), ("47.94.80.90", 7709)]
    api = TdxHq_API()
    for host, port in servers:
        try:
            if api.connect(host, port, time_out=3):
                break
        except Exception:
            continue
    else:
        raise RuntimeError("Cannot connect")
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


def run_single(df: pd.DataFrame, code: str, period: int, oversold: int, overbought: int) -> dict:
    strat = RSIStrategy(params={"period": period, "oversold": oversold, "overbought": overbought})
    sim = Simulator(
        strategy=strat,
        risk_config=RiskConfig(max_position_value=50000, max_daily_loss=3000, default_stop_loss_pct=0.015),
    )
    result = sim.run_from_df(df, code=code)
    r = result.report
    return {
        "period": period, "oversold": oversold, "overbought": overbought,
        "trades": r["total_trades"], "win_rate": r.get("win_rate"),
        "total_profit": r["total_profit"],
        "profit_factor": r.get("profit_factor"),
        "sharpe": r.get("sharpe_ratio"), "mdd": r.get("max_drawdown_pct"),
    }


def scan(df: pd.DataFrame, code: str) -> pd.DataFrame:
    results = []
    combos = [(p, os_, ob) for p in PERIODS
              for os_ in OVERSOLD for ob in OVERBOUGHT if os_ < ob]
    total = len(combos)
    t0 = datetime.now()
    for idx, (p, os_, ob) in enumerate(combos, 1):
        results.append(run_single(df, code, p, os_, ob))
        if idx % 100 == 0 or idx == total:
            print(f"  进度: {idx}/{total} ({(datetime.now()-t0).total_seconds():.0f}s)")
    return pd.DataFrame(results)


def main():
    for code, name in ETFS.items():
        print(f"\n{'='*70}")
        print(f"  {name} ({code}) — 加载数据...")
        sys.stdout.flush()
        df = load_all_pytdx_data(code)
        if df.empty:
            print("  ❌ 无数据")
            continue

        all_dates = sorted(df["time"].apply(lambda t: t.date()).unique())
        mid = len(all_dates) // 2
        first_dates = all_dates[:mid]
        second_dates = all_dates[mid:]
        print(f"  全量: {len(all_dates)} 天 ({all_dates[0]} ~ {all_dates[-1]})")
        print(f"  前半: {len(first_dates)} 天 ({first_dates[0]} ~ {first_dates[-1]})")
        print(f"  后半: {len(second_dates)} 天 ({second_dates[0]} ~ {second_dates[-1]})")

        df_first = df[df["time"].dt.date.isin(set(first_dates))]
        df_second = df[df["time"].dt.date.isin(set(second_dates))]

        # 全量扫描
        print(f"  全量扫描...")
        sys.stdout.flush()
        full = scan(df, code)

        # 前后半段扫描
        print(f"  前半扫描...")
        sys.stdout.flush()
        first = scan(df_first, code)
        print(f"  后半扫描...")
        sys.stdout.flush()
        second = scan(df_second, code)

        # 合并
        merged = full.merge(first, on=["period", "oversold", "overbought"],
                            suffixes=("", "_first"))
        merged = merged.merge(second, on=["period", "oversold", "overbought"],
                              suffixes=("", "_second"))

        # 筛选：前后半段均盈利且后半段也为正
        robust = merged[
            (merged["total_profit_first"] > 0) &
            (merged["total_profit_second"] > 0)
        ].copy()

        if robust.empty:
            print(f"\n  ⚠️  无参数在前后半段均盈利！放宽条件：至少后半段盈利")
            robust = merged[merged["total_profit_second"] > 0].copy()

        # 按总利润排序
        robust = robust.sort_values("total_profit", ascending=False)

        print(f"\n  {'='*70}")
        print(f"  {name} ({code}) — 稳健参数 Top 15（前后半段均为正）")
        print(f"  {'='*70}")
        header = (f"  {'#':<4} {'参数':<16} {'交易':<6} {'Win%':<8} "
                  f"{'全量盈亏':<12} {'前段盈亏':<12} {'后段盈亏':<12} "
                  f"{'前Win%':<8} {'后Win%':<8}")
        print(header)
        print(f"  {'-'*80}")
        for rank, (_, row) in enumerate(robust.head(15).iterrows(), 1):
            wr = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "-"
            wr1 = f"{row['win_rate_first']:.1f}%" if pd.notna(row['win_rate_first']) else "-"
            wr2 = f"{row['win_rate_second']:.1f}%" if pd.notna(row['win_rate_second']) else "-"
            label = f"RSI({int(row['period'])},{int(row['oversold'])},{int(row['overbought'])})"
            print(f"  {rank:<4} {label:<16} {int(row['trades']):<6} {wr:<8} "
                  f"{row['total_profit']:<12.2f} {row['total_profit_first']:<12.2f} {row['total_profit_second']:<12.2f} "
                  f"{wr1:<8} {wr2:<8}")

        # 默认参数对比
        for label, (p, os_, ob) in [
            ("默认(14,30,70)", (14, 30, 70)),
            ("快速(7,25,75)", (7, 25, 75)),
        ]:
            match = robust[(robust["period"]==p) & (robust["oversold"]==os_) & (robust["overbought"]==ob)]
            if not match.empty:
                r = match.iloc[0]
                print(f"\n  --- {label} ---")
                print(f"  全量: {r['total_profit']:.2f} | 前段: {r['total_profit_first']:.2f} | 后段: {r['total_profit_second']:.2f}")

        # 全量 Top 3 （无过滤，用来对比）
        print(f"\n  --- 全量 Top 3（无交叉过滤） ---")
        for rank, (_, row) in enumerate(full.sort_values("total_profit", ascending=False).head(3).iterrows(), 1):
            wr = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "-"
            label = f"RSI({int(row['period'])},{int(row['oversold'])},{int(row['overbought'])})"
            print(f"  #{rank} {label}: 盈亏={row['total_profit']:.0f} 胜率={wr} 交易={int(row['trades'])}")

    print(f"\n  ✅ V2 扫描完成")


if __name__ == "__main__":
    main()
