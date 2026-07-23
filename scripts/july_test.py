#!/usr/bin/env python3
"""验证 589020 在 7 月份是否仍然有效（fallback 方式加载）"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from datetime import datetime, date
from data_provider.intraday import MinuteDataLoader
from src.trading.simulator import Simulator
from src.trading.strategies.rsi import RSIStrategy
from src.trading.risk_manager import RiskConfig

PARAMS = [
    (8, 35, 85, "RSI(8,35,85) 最均衡"),
    (15, 20, 60, "RSI(15,20,60) 高胜率"),
    (15, 20, 55, "RSI(15,20,55) 全胜"),
    (14, 20, 65, "RSI(14,20,65) 均衡"),
]

# 7月已知交易日 + 尝试更多日期
JULY_DATES = ["2026-07-01", "2026-07-02", "2026-07-03",
              "2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09",
              "2026-07-10", "2026-07-13", "2026-07-14", "2026-07-15",
              "2026-07-16", "2026-07-17", "2026-07-20", "2026-07-21",
              "2026-07-22", "2026-07-23"]

def load_data_with_fallback(code: str, dates: list[str]) -> pd.DataFrame:
    loader = MinuteDataLoader(source="akshare")
    dfs = []
    for d in dates:
        try:
            df = loader.load(code, d)
            if df is not None and not df.empty:
                dfs.append(df)
                print(f"  {d}: {len(df)} bars ✓")
            else:
                print(f"  {d}: 无数据")
        except Exception as e:
            print(f"  {d}: {e}")
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)

def run_single(df, code, period, oversold, overbought):
    strat = RSIStrategy(params={"period": period, "oversold": oversold, "overbought": overbought})
    sim = Simulator(
        strategy=strat,
        risk_config=RiskConfig(max_position_value=50000, max_daily_loss=3000, default_stop_loss_pct=0.015),
    )
    result = sim.run_from_df(df, code=code)
    r = result.report
    return {
        "trades": r["total_trades"], "win_rate": r.get("win_rate"),
        "total_profit": r["total_profit"],
        "profit_factor": r.get("profit_factor"),
        "sharpe": r.get("sharpe_ratio"), "mdd": r.get("max_drawdown_pct"),
        "trades_list": result.trades,
    }

print("  589020 — 逐日加载 7月数据（三层 fallback）...")
df = load_data_with_fallback("589020", JULY_DATES)
if df.empty:
    print("  ❌ 无数据")
    sys.exit(1)

all_dates = sorted(df["time"].apply(lambda t: t.date()).unique())
print(f"\n  加载成功: {all_dates[0]} ~ {all_dates[-1]} ({len(all_dates)}天, {len(df)}条K线)")

# 每日行情概况
print(f"\n{'='*70}")
print(f"  589020 7月份每日概况")
print(f"{'='*70}")
for d in all_dates:
    df_day = df[df["time"].dt.date == d]
    o = df_day["open"].iloc[0]
    c = df_day["close"].iloc[-1]
    h = df_day["high"].max()
    l = df_day["low"].min()
    chg = (c / o - 1) * 100
    print(f"  {d}  开:{o:.4f} 高:{h:.4f} 低:{l:.4f} 收:{c:.4f} {chg:+.2f}%")

# 各参数表现
print(f"\n{'='*70}")
print(f"  7月表现对比")
print(f"{'='*70}")
header = f"  {'参数':<20} {'交易':<6} {'Win%':<8} {'总盈亏':<12} {'盈亏比':<8} {'夏普':<8} {'MDD%':<8}"
print(header)
print(f"  {'-'*66}")
for period, oversold, overbought, label in PARAMS:
    r = run_single(df, "589020", period, oversold, overbought)
    wr = f"{r['win_rate']:.1f}%" if r['win_rate'] else "-"
    pf = f"{r['profit_factor']:.2f}" if r['profit_factor'] else "-"
    sp = f"{r['sharpe']:.3f}" if r['sharpe'] else "-"
    md = f"{r['mdd']:.2f}%" if r['mdd'] else "-"
    print(f"  {label:<20} {r['trades']:<6} {wr:<8} {r['total_profit']:<12.2f} {pf:<8} {sp:<8} {md:<8}")

# RSI(8,35,85) 逐笔交易明细
print(f"\n{'='*70}")
print(f"  RSI(8,35,85) 7月逐笔交易")
print(f"{'='*70}")
r = run_single(df, "589020", 8, 35, 85)
if r["trades_list"]:
    for i, t in enumerate(r["trades_list"], 1):
        print(f"  #{i:<3} {t.buy_time.strftime('%m/%d %H:%M')} B {t.buy_price:.4f}  "
              f"→ {t.sell_time.strftime('%m/%d %H:%M')} S {t.sell_price:.4f}  "
              f"盈亏 {t.profit:+.0f}  持仓{t.duration_minutes:.0f}min")
    print(f"\n  总计: {len(r['trades_list'])}笔 | 胜率: {r['win_rate']:.1f}% | 总盈亏: {r['total_profit']:.2f}")
else:
    print(f"  7月无交易触发")

# 6月对比
print(f"\n{'='*70}")
print(f"  6月 vs 7月 对比")
print(f"{'='*70}")
loader = MinuteDataLoader(source="akshare")
june_dates = ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
              "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12",
              "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19",
              "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
              "2026-06-29", "2026-06-30"]
print(f"  加载 6月数据（可能较慢）...")
df_june_combined = pd.concat(
    [loader.load("589020", d) for d in june_dates],
    ignore_index=True
) if not df.empty else pd.DataFrame()

if not df_june_combined.empty:
    for period, oversold, ob, label in PARAMS:
        r6 = run_single(df_june_combined, "589020", period, oversold, ob)
        r7 = run_single(df, "589020", period, oversold, ob)
        tag = label.split(" ")[0]
        print(f"  {tag:<16} 6月:{r6['total_profit']:>+8.0f}({r6['trades']}笔)  7月:{r7['total_profit']:>+8.0f}({r7['trades']}笔)")
else:
    print(f"  6月数据加载失败，跳过对比")

print(f"\n  ✅ 完成")
