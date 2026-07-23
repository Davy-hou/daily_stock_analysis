#!/usr/bin/env python3
"""样本外验证：检查 07-03 之后是否有新数据 + 参数灵敏度 + 交叉验证"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from datetime import datetime, date
from data_provider.intraday import MinuteDataLoader
from src.trading.simulator import Simulator
from src.trading.strategies.rsi import RSIStrategy
from src.trading.risk_manager import RiskConfig

CODE = "589020"
BEST_P = 13
BEST_OS = 25
BEST_OB = 85


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


def run_single(code: str, period: int, oversold: int, overbought: int,
               df: pd.DataFrame) -> dict:
    strat = RSIStrategy(params={"period": period, "oversold": oversold, "overbought": overbought})
    sim = Simulator(
        strategy=strat,
        risk_config=RiskConfig(max_position_value=50000, max_daily_loss=3000, default_stop_loss_pct=0.015),
    )
    result = sim.run_from_df(df, code=code)
    r = result.report
    days = df["time"].apply(lambda t: t.date()).nunique()
    return {
        "period": period, "oversold": oversold, "overbought": overbought,
        "days": days, "bars": len(df),
        "trades": r["total_trades"], "win_rate": r.get("win_rate"),
        "total_profit": r["total_profit"],
        "profit_factor": r.get("profit_factor"),
        "sharpe": r.get("sharpe_ratio"), "mdd": r.get("max_drawdown_pct"),
    }


def main():
    print(f"\n{'='*70}")
    print(f"  {CODE} — 加载全部 PyTDX 数据...")
    df = load_all_pytdx_data(CODE)
    if df.empty:
        print("  ❌ 无数据")
        return

    all_dates = sorted(df["time"].apply(lambda t: t.date()).unique())
    print(f"  可用日期范围: {all_dates[0]} ~ {all_dates[-1]} ({len(all_dates)} 天)")

    # 检查是否有 07-03 之后的数据
    cutoff = date(2026, 7, 4)
    oos_dates = [d for d in all_dates if d >= cutoff]
    is_dates = [d for d in all_dates if d < cutoff]

    print(f"  样本内 (IS): {len(is_dates)} 天 ({is_dates[0]} ~ {is_dates[-1]})")
    print(f"  样本外 (OOS): {len(oos_dates)} 天 ({oos_dates[0] if oos_dates else '无'})")

    # ======== 1. 前测：在 OOS 数据上运行最优参数 ========
    if oos_dates:
        print(f"\n{'='*70}")
        print(f"  Part 1: 前测 — RSI({BEST_P},{BEST_OS},{BEST_OB}) 在 OOS 数据上")
        print(f"  {'='*70}")
        df_oos = df[df["time"].dt.date.isin(set(oos_dates))].copy()
        r = run_single(CODE, BEST_P, BEST_OS, BEST_OB, df_oos)
        print(f"  日期: {oos_dates[0]} ~ {oos_dates[-1]}")
        print(f"  K线: {r['bars']} | 交易日: {r['days']}")
        print(f"  交易: {r['trades']} | 胜率: {r['win_rate']:.1f}%" if r['win_rate'] else f"  交易: 0")
        print(f"  总盈亏: {r['total_profit']:.2f}")
        if r['profit_factor']: print(f"  盈亏比: {r['profit_factor']:.2f}")
        if r['sharpe']: print(f"  夏普: {r['sharpe']:.3f}")
        if r['mdd']: print(f"  MDD: {r['mdd']:.2f}%")
    else:
        print(f"\n  ⚠️  PyTDX 暂无 07-03 之后的数据")

    # ======== 2. 参数灵敏度：最优参数邻域 ========
    print(f"\n{'='*70}")
    print(f"  Part 2: 参数灵敏度 — RSI({BEST_P},{BEST_OS},{BEST_OB}) 邻域")
    print(f"  {'='*70}")
    print(f"  在全量数据上测试邻近参数组合\n")

    # 测试邻域：period ±2, OS ±5, OB ±5
    neighbors = []
    for dp in [0, -1, 1, -2, 2]:
        for dos in [0, -5, 5]:
            for dob in [0, -5, 5]:
                p, os_, ob = BEST_P + dp, BEST_OS + dos, BEST_OB + dob
                if p < 5 or p > 20: continue
                if os_ < 15 or os_ > 45: continue
                if ob < 55 or ob > 85: continue
                if os_ >= ob: continue
                neighbors.append((p, os_, ob))

    neighbors = list(set(neighbors))
    results = []
    for p, os_, ob in neighbors:
        r = run_single(CODE, p, os_, ob, df)
        results.append(r)

    df_r = pd.DataFrame(results).sort_values("total_profit", ascending=False)
    header = f"  {'#':<4} {'参数':<16} {'交易':<6} {'Win%':<8} {'总盈亏':<12} {'盈亏比':<8} {'夏普':<8} {'MDD%':<8}"
    print(header)
    print(f"  {'-'*66}")
    for rank, (_, row) in enumerate(df_r.head(10).iterrows(), 1):
        wr = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "-"
        pf = f"{row['profit_factor']:.2f}" if pd.notna(row['profit_factor']) else "-"
        sp = f"{row['sharpe']:.3f}" if pd.notna(row['sharpe']) else "-"
        md = f"{row['mdd']:.2f}%" if pd.notna(row['mdd']) else "-"
        label = f"RSI({int(row['period'])},{int(row['oversold'])},{int(row['overbought'])})"
        print(f"  {rank:<4} {label:<16} {int(row['trades']):<6} {wr:<8} {row['total_profit']:<12.2f} {pf:<8} {sp:<8} {md:<8}")

    # 最优参数位置标记
    best_row = df_r[(df_r["period"]==BEST_P) & (df_r["oversold"]==BEST_OS) & (df_r["overbought"]==BEST_OB)]
    if not best_row.empty:
        r = best_row.iloc[0]
        rank = df_r.index.get_loc(best_row.index[0]) + 1
        print(f"\n  ★ RSI({BEST_P},{BEST_OS},{BEST_OB}) 在此邻域中排名 #{rank}/{len(neighbors)}")

    # ======== 3. 时序交叉验证：前N天 vs 后N天 ========
    print(f"\n{'='*70}")
    print(f"  Part 3: 时序稳定性 — 前半段 vs 后半段")
    print(f"  {'='*70}")
    mid = len(all_dates) // 2
    first_half = all_dates[:mid]
    second_half = all_dates[mid:]

    df_first = df[df["time"].dt.date.isin(set(first_half))].copy()
    df_second = df[df["time"].dt.date.isin(set(second_half))].copy()

    for label, segment_df, seg_dates in [
        (f"前半段 ({first_half[0]} ~ {first_half[-1]})", df_first, first_half),
        (f"后半段 ({second_half[0]} ~ {second_half[-1]})", df_second, second_half),
    ]:
        r = run_single(CODE, BEST_P, BEST_OS, BEST_OB, segment_df)
        print(f"\n  {label}")
        print(f"  交易: {r['trades']} | 胜率: {r['win_rate']:.1f}%" if r['win_rate'] else f"  交易: 0")
        print(f"  总盈亏: {r['total_profit']:.2f}")

    # ======== 4. 在 513050 上也做 OOS ========
    print(f"\n{'='*70}")
    print(f"  Part 4: 513050 样本外验证 — RSI(15,35,65)")
    CODE2 = "513050"
    BEST2_P, BEST2_OS, BEST2_OB = 15, 35, 65

    df2 = load_all_pytdx_data(CODE2)
    if not df2.empty:
        all_dates2 = sorted(df2["time"].apply(lambda t: t.date()).unique())
        oos2 = [d for d in all_dates2 if d >= cutoff]
        is2 = [d for d in all_dates2 if d < cutoff]
        print(f"  可用日期: {len(all_dates2)} 天")
        print(f"  样本外: {len(oos2)} 天" if oos2 else "  样本外: 无")

        if oos2:
            df_oos2 = df2[df2["time"].dt.date.isin(set(oos2))].copy()
            r = run_single(CODE2, BEST2_P, BEST2_OS, BEST2_OB, df_oos2)
            print(f"  RSI({BEST2_P},{BEST2_OS},{BEST2_OB}) OOS 结果:")
            print(f"  交易: {r['trades']} | 胜率: {r['win_rate']:.1f}%" if r['win_rate'] else f"  交易: 0")
            print(f"  总盈亏: {r['total_profit']:.2f}")

        # 参数灵敏度
        print(f"\n  513050 参数灵敏度邻域:")
        neighbors2 = []
        for dp in [0, -1, 1]:
            for dos in [0, -5, 5]:
                for dob in [0, -5, 5]:
                    p, os_, ob = BEST2_P + dp, BEST2_OS + dos, BEST2_OB + dob
                    if p < 5 or p > 20: continue
                    if os_ < 15 or os_ > 45: continue
                    if ob < 55 or ob > 85: continue
                    if os_ >= ob: continue
                    neighbors2.append((p, os_, ob))

        neighbors2 = list(set(neighbors2))
        res2 = []
        for p, os_, ob in neighbors2:
            res2.append(run_single(CODE2, p, os_, ob, df2))
        df_r2 = pd.DataFrame(res2).sort_values("total_profit", ascending=False)
        for rank, (_, row) in enumerate(df_r2.head(8).iterrows(), 1):
            wr = f"{row['win_rate']:.1f}%" if pd.notna(row['win_rate']) else "-"
            pf = f"{row['profit_factor']:.2f}" if pd.notna(row['profit_factor']) else "-"
            sp = f"{row['sharpe']:.3f}" if pd.notna(row['sharpe']) else "-"
            label = f"RSI({int(row['period'])},{int(row['oversold'])},{int(row['overbought'])})"
            print(f"  #{rank} {label}: 盈亏={row['total_profit']:.0f} 胜率={wr} 盈亏比={pf} 夏普={sp}")

    print(f"\n  ✅ 验证完成")


if __name__ == "__main__":
    main()
