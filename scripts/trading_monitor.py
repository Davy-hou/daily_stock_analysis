#!/usr/bin/env python3
"""589020 实时监控：每10分钟检查 RSI(8,35,85) + 科创50 MA5，发现信号推送飞书"""

import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import pandas as pd
from datetime import datetime, time as dtime, timedelta, timezone
from typing import Optional

from data_provider.intraday import MinuteDataLoader

# === 配置 ===
CODE = "589020"
NAME = "科创半导体"
INDEX_CODE = "000688"
RSI_PERIOD = 8
BUY_THRESHOLD = 35
SELL_THRESHOLD = 85
TREND_MA_PERIOD = 5

# 北京时间 CST = UTC+8
CST = timezone(timedelta(hours=8))
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(15, 0)

# 状态文件（GitHub Actions Cache 持久化）
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", ".monitor_state.json")


# ============================================================
#   RSI 计算
# ============================================================
def compute_rsi(closes: list[float], period: int = 8) -> list[float]:
    if len(closes) < period + 1:
        return []
    rsis = []
    gains, losses = [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i-1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
        if len(gains) > period:
            gains.pop(0)
            losses.pop(0)
        if len(gains) == period:
            avg_g = sum(gains) / period
            avg_l = sum(losses) / period
            if avg_l == 0:
                rsis.append(100.0)
            else:
                rsis.append(100 - 100 / (1 + avg_g / avg_l))
    return rsis


# ============================================================
#   数据加载
# ============================================================
def load_minute_data(code: str) -> pd.DataFrame:
    loader = MinuteDataLoader(source="akshare")
    today = datetime.now(CST).strftime("%Y-%m-%d")
    # 尝试当日；若盘前运行则加载前一交易日
    for date_str in [today, (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")]:
        try:
            df = loader.load(code, date_str)
            if df is not None and not df.empty and len(df) >= RSI_PERIOD + 5:
                return df
        except Exception:
            continue
    return pd.DataFrame()


def load_index_data(code: str) -> pd.DataFrame:
    import akshare as ak
    df = ak.stock_zh_index_daily_em(symbol=f"sh{code}")
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.sort_values("date").tail(TREND_MA_PERIOD + 3)
    df["ma"] = df["close"].rolling(TREND_MA_PERIOD).mean()
    return df


# ============================================================
#   信号检测（无状态跨界检测）
# ============================================================
def detect_signals(closes: list[float], rsis: list[float],
                   trend_ok: bool) -> tuple[Optional[str], Optional[str]]:
    if not rsis or len(rsis) < 3:
        return None, None

    current_rsi = rsis[-1]
    buy_signal = None
    sell_signal = None

    # 买入：RSI 从上方穿过 35 → 当前 < 35 且之前 >= 35
    if current_rsi < BUY_THRESHOLD:
        # 检查最近 10 个 RSI 值中是否有 >= 35 的（说明刚刚下穿）
        recent = rsis[-min(len(rsis), 10):-1]
        if recent and max(recent) >= BUY_THRESHOLD:
            if trend_ok:
                buy_signal = f"RSI 下穿 35（当前 {current_rsi:.1f}）✅ 趋势向上"
            else:
                buy_signal = f"RSI 下穿 35（当前 {current_rsi:.1f}）⚠️ 趋势向下，建议观望"

    # 卖出：RSI 从下方穿过 85 → 当前 > 85 且之前 <= 85
    if current_rsi > SELL_THRESHOLD:
        recent = rsis[-min(len(rsis), 10):-1]
        if recent and min(recent) <= SELL_THRESHOLD:
            sell_signal = f"RSI 上穿 85（当前 {current_rsi:.1f}）"

    return buy_signal, sell_signal


# ============================================================
#   飞书通知
# ============================================================
def send_feishu(webhook_url: str, title: str, body: str) -> bool:
    if not webhook_url:
        print("  ❌ FEISHU_WEBHOOK_URL 未设置")
        return False

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "lark_md", "content": f"🚨 {title}"},
            "template": "red" if "卖出" in title else "green",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body}},
            {"tag": "hr"},
            {"tag": "note", "element": {"tag": "plain_text", "content": f"589020 实时监控 · {datetime.now(CST).strftime('%m/%d %H:%M')}"}},
        ],
    }
    try:
        resp = requests.post(
            webhook_url,
            json={"msg_type": "interactive", "card": card},
            timeout=10,
        )
        ok = resp.ok
        print(f"  {'✅' if ok else '❌'} 飞书推送: {resp.status_code}" + (f" {resp.text[:100]}" if not ok else ""))
        return ok
    except Exception as e:
        print(f"  ❌ 飞书推送异常: {e}")
        return False


# ============================================================
#   状态管理（GH Actions Cache）
# ============================================================
def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"day": "", "buy_alerted": False, "sell_alerted": False}


def save_state(state: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================
#   主流程
# ============================================================
def main():
    now = datetime.now(CST)
    today_str = now.strftime("%Y-%m-%d")
    current_time = now.time()

    print(f"🕐 {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"  标的: {NAME} ({CODE})")

    # 检查是否在交易时段
    if not (MARKET_OPEN <= current_time <= MARKET_CLOSE):
        print(f"  ⏰ 非交易时段（{MARKET_OPEN.strftime('%H:%M')}-{MARKET_CLOSE.strftime('%H:%M')}），跳过")
        return

    # 加载状态
    state = load_state()
    if state.get("day") != today_str:
        state = {"day": today_str, "buy_alerted": False, "sell_alerted": False}
        print(f"  📅 新交易日，重置告警状态")

    # 加载标的分钟线
    print(f"  加载 {CODE} 分钟线...")
    df = load_minute_data(CODE)
    if df.empty:
        print("  ❌ 无数据，跳过")
        return
    print(f"  📊 {len(df)} 条K线 ({df['time'].iloc[0].strftime('%H:%M')} ~ {df['time'].iloc[-1].strftime('%H:%M')})")

    # 计算 RSI
    closes = df["close"].tolist()
    rsis = compute_rsi(closes, RSI_PERIOD)
    if not rsis:
        print("  ❌ 数据不足，跳过")
        return

    current_rsi = rsis[-1] if rsis else 50
    print(f"  📈 RSI({RSI_PERIOD}) = {current_rsi:.1f}")

    # 加载指数判断趋势
    trend_ok = False
    print(f"  加载 {INDEX_CODE} 日线...")
    df_idx = load_index_data(INDEX_CODE)
    if not df_idx.empty:
        latest = df_idx.iloc[-1]
        trend_ok = latest["close"] > latest["ma"]
        print(f"  科创50: {latest['close']:.0f} MA{TREND_MA_PERIOD}: {latest['ma']:.0f} {'✅ 向上' if trend_ok else '❌ 向下'}")
    else:
        print(f"  ⚠️ 指数数据不可用，跳过趋势过滤")

    # 检测信号
    buy_sig, sell_sig = detect_signals(closes, rsis, trend_ok)

    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")

    # 处理买入信号
    if buy_sig and not state["buy_alerted"]:
        title = f"🟢 {NAME} RSI 买入信号"
        body = f"**{NAME} ({CODE})**\n\n"
        body += f"RSI({RSI_PERIOD}): {current_rsi:.1f}（< {BUY_THRESHOLD}）\n"
        body += f"科创50 MA{TREND_MA_PERIOD}: {'✅ 趋势向上' if trend_ok else '❌ 趋势向下'}\n\n"
        body += f"当前价: {closes[-1]:.4f}\n"
        body += f"时间: {df['time'].iloc[-1].strftime('%H:%M')}\n\n"
        body += "操作建议：关注买入机会，设好止损"

        print(f"\n  🟢 买入信号!")
        print(f"  {buy_sig}")
        send_feishu(webhook, title, body)
        state["buy_alerted"] = True

    # 处理卖出信号
    if sell_sig and not state["sell_alerted"]:
        title = f"🔴 {NAME} RSI 卖出信号"
        body = f"**{NAME} ({CODE})**\n\n"
        body += f"RSI({RSI_PERIOD}): {current_rsi:.1f}（> {SELL_THRESHOLD}）\n"
        body += f"当前价: {closes[-1]:.4f}\n"
        body += f"时间: {df['time'].iloc[-1].strftime('%H:%M')}\n\n"
        body += "操作建议：考虑止盈/减仓"

        print(f"\n  🔴 卖出信号!")
        print(f"  {sell_sig}")
        send_feishu(webhook, title, body)
        state["sell_alerted"] = True

    # 常规状态推送（仅当有信号时附带）
    if not buy_sig and not sell_sig:
        print(f"  📋 无信号，当前 RSI={current_rsi:.1f}")

        # 盘后发送一次汇总（可选）
        if current_time >= dtime(14, 55) and current_time <= dtime(15, 5):
            if not state.get("eod_summary"):
                title = f"📊 {NAME} 收盘简报"
                body = f"**{NAME} ({CODE})**\n\n"
                body += f"收盘 RSI({RSI_PERIOD}): {current_rsi:.1f}\n"
                body += f"收盘价: {closes[-1]:.4f}\n"
                body += f"今日波幅: {max(closes):.4f} ~ {min(closes):.4f}\n\n"
                body += f"科创50 MA{TREND_MA_PERIOD}: {'✅' if trend_ok else '❌'}\n\n"
                body += "今日无交易信号触发。"
                send_feishu(webhook, title, body)
                state["eod_summary"] = True

    # 保存状态
    save_state(state)
    print(f"  ✅ 完成 (RSI={current_rsi:.1f})")


if __name__ == "__main__":
    main()
