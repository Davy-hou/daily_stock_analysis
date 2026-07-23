#!/usr/bin/env python3
"""RSI 参数网格扫描：对 period / oversold / overbought 做系统化搜索"""

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

# === 配置 ===
ETFS = {
    "589020": "科创半导体",
    "513050": "中概互联",
    "513750": "港股非银ETF",
}
PERIODS = list(range(5, 21))        # 5~20
OVERSOLD = list(range(15, 46, 5))   # 15,20,25,30,35,40,45
OVERBOUGHT = list(range(55, 86, 5)) # 55,60,65,70,75,80,85

DATES = ["2026-07-03", "2026-07-02", "2026-07-01", "2026-06-30", "2026-06-29",
         "2026-06-26", "2026-06-25", "2026-06-24", "2026-06-23", "2026-06-22",
         "2026-06-19", "2026-06-18", "2026-06-17", "2026-06-16", "2026-06-15",
         "2026-06-12", "2026-06-11", "2026-06-10", "2026-06-09", "2026-06-08"]


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
        raise RuntimeError("Cannot connect to any PyTDX server")
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


def main():
    target_dates = set(pd.to_datetime(DATES).date)

    for code, name in ETFS.items():
        print(f"\n{'='*70}")
        print(f"  {name} ({code}) — 加载全部 PyTDX 数据...")
        sys.stdout.flush()
        t0 = datetime.now()

        df = load_all_pytdx_data(code)
        if df.empty:
            print(f"  ❌ 无数据")
            continue

        df = df[df["time"].dt.date.isin(target_dates)].copy()
        days = df["time"].apply(lambda t: t.date()).nunique()
        bars = len(df)
        elapsed = (datetime.now() - t0).total_seconds()
        print(f"  加载完成: {bars} bars, {days} 天数据 ({elapsed:.0f}s)")
        sys.stdout.flush()

        results = []
        combos = [(p, os_, ob) for p in PERIODS
                  for os_ in OVERSOLD for ob in OVERBOUGHT if os_ < ob]
        total = len(combos)

        t0 = datetime.now()
        for idx, (period, oversold, overbought) in enumerate(combos, 1):
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
                "period": period, "oversold": oversold, "overbought": overbought,
                "trades": r["total_trades"], "win_rate": r.get("win_rate"),
                "total_profit": r["total_profit"],
                "profit_factor": r.get("profit_factor"),
                "sharpe": r.get("sharpe_ratio"), "mdd": r.get("max_drawdown_pct"),
            })

            if idx % 50 == 0 or idx == total:
                elapsed = (datetime.now() - t0).total_seconds()
                print(f"  进度: {idx}/{total} ({elapsed:.0f}s)")
                sys.stdout.flush()

        df_rank = pd.DataFrame(results).sort_values("total_profit", ascending=False)

        # 打印 Top 15
        print(f"\n  {'='*70}")
        print(f"  {name} ({code}) — RSI 参数网格扫描 Top 15（按总盈亏排序）")
        print(f"  {'='*70}")
        header = f"  {'#':<4} {'Per':<5} {'OS':<5} {'OB':<5} {'Trades':<8} {'Win%':<8} {'总盈亏':<12} {'盈亏比':<10} {'夏普':<10} {'MDD%':<8}"
        print(header)
        print(f"  {'-'*66}")
        for rank, (_, row) in enumerate(df_rank.head(15).iterrows(), 1):
            wr = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "-"
            pf = f"{row['profit_factor']:.2f}" if pd.notna(row['profit_factor']) else "-"
            sp = f"{row['sharpe']:.3f}" if pd.notna(row['sharpe']) else "-"
            md = f"{row['mdd']:.2f}%" if pd.notna(row['mdd']) else "-"
            print(f"  {rank:<4} {int(row['period']):<5} {int(row['oversold']):<5} {int(row['overbought']):<5} {int(row['trades']):<8} {wr:<8} {row['total_profit']:<12.2f} {pf:<10} {sp:<10} {md:<8}")

        # 基准对比
        for label, (p, os_, ob) in [
            ("默认 RSI(14,30,70)", (14, 30, 70)),
            ("之前最佳 RSI(7,25,75)", (7, 25, 75)),
        ]:
            match = df_rank[(df_rank["period"]==p) & (df_rank["oversold"]==os_) & (df_rank["overbought"]==ob)]
            if not match.empty:
                r = match.iloc[0]
                print(f"\n  --- {label} ---")
                print(f"  盈亏: {r['total_profit']:.2f} | 胜率: {r['win_rate']:.1f}% | 交易: {int(r['trades'])} | 盈亏比: {r['profit_factor']:.2f} | 夏普: {r['sharpe']:.3f} | MDD: {r['mdd']:.2f}%")

    print("\n  ✅ 网格扫描完成")


if __name__ == "__main__":
    main()
