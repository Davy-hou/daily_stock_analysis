#!/usr/bin/env python3
"""多标的实时监控：每10分钟检查 RSI 信号，发现信号推送飞书"""

import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
import pandas as pd
from datetime import datetime, time as dtime, timedelta, timezone

from data_provider.intraday import MinuteDataLoader

# === 多标的配置 ===
STOCKS = [
    {"code": "589020", "name": "科创半导体", "rsi_p": 8, "os": 35, "ob": 85,
     "idx": "000688", "idx_name": "科创50", "ma": 5},
    {"code": "159500", "name": "创业板ETF", "rsi_p": 18, "os": 30, "ob": 55,
     "idx": "399006", "idx_name": "创业板指", "ma": 5},
    {"code": "515880", "name": "通信ETF",   "rsi_p": 10, "os": 35, "ob": 85,
     "idx": "000001", "idx_name": "上证指数", "ma": 5},
    {"code": "588220", "name": "科创ETF",   "rsi_p": 20, "os": 30, "ob": 55,
     "idx": "000688", "idx_name": "科创50", "ma": 5},
]

CST = timezone(timedelta(hours=8))
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(15, 0)
STATE_FILE = os.path.join(os.path.dirname(__file__), "..", ".monitor_state.json")
_index_cache: dict = {}

# ============================================================
#   RSI 计算
# ============================================================
def compute_rsi(closes: list[float], period: int) -> list[float]:
    if len(closes) < period + 1:
        return []
    rsis = []
    gains, losses = [], []
    for i in range(1, len(closes)):
        chg = closes[i] - closes[i-1]
        gains.append(max(chg, 0))
        losses.append(max(-chg, 0))
        if len(gains) > period:
            gains.pop(0); losses.pop(0)
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
def load_minute_data(code: str, min_bars: int) -> pd.DataFrame:
    loader = MinuteDataLoader(source="akshare")
    today = datetime.now(CST).strftime("%Y-%m-%d")
    for date_str in [today, (datetime.now(CST) - timedelta(days=1)).strftime("%Y-%m-%d")]:
        try:
            df = loader.load(code, date_str)
            if df is not None and not df.empty and len(df) >= min_bars:
                return df
        except Exception:
            continue
    return pd.DataFrame()

def load_index_trend(index_code: str, ma_period: int) -> tuple[bool, float, float, str]:
    """返回 (trend_ok, close, ma_value, name)"""
    cache_key = f"{index_code}_{ma_period}"
    if cache_key in _index_cache:
        return _index_cache[cache_key]

    import akshare as ak
    prefix = "sz" if index_code.startswith("399") else "sh"
    try:
        df = ak.stock_zh_index_daily_em(symbol=f"{prefix}{index_code}")
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.sort_values("date").tail(ma_period + 5)
        df["ma"] = df["close"].rolling(ma_period).mean()
        if df.empty:
            return False, 0, 0, ""
        latest = df.iloc[-1]
        ok = latest["close"] > latest["ma"]
        _index_cache[cache_key] = (ok, latest["close"], latest["ma"], prefix)
        return ok, latest["close"], latest["ma"], prefix
    except Exception:
        return False, 0, 0, ""

# ============================================================
#   信号检测
# ============================================================
def detect_signals(rsis: list[float], os: int, ob: int, trend_ok: bool
                   ) -> tuple[str | None, str | None]:
    if not rsis or len(rsis) < 3:
        return None, None
    cur = rsis[-1]
    buy_sig = sell_sig = None

    if cur < os:
        recent = rsis[-min(len(rsis), 10):-1]
        if recent and max(recent) >= os:
            buy_sig = ("✅" if trend_ok else "⚠️") + f" RSI={cur:.0f} < {os}"

    if cur > ob:
        recent = rsis[-min(len(rsis), 10):-1]
        if recent and min(recent) <= ob:
            sell_sig = f"RSI={cur:.0f} > {ob}"

    return buy_sig, sell_sig

# ============================================================
#   飞书通知
# ============================================================
def send_feishu(webhook_url: str, title: str, body: str, tag: str = "") -> bool:
    if not webhook_url:
        return False
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "lark_md", "content": f"🚨 {title}"},
            "template": "red" if "卖出" in title else ("green" if "买入" in title else "blue"),
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": body}},
            {"tag": "hr"},
            {"tag": "note", "element": {"tag": "plain_text",
              "content": f"{tag} · {datetime.now(CST).strftime('%m/%d %H:%M')}"}},
        ],
    }
    try:
        resp = requests.post(webhook_url, json={"msg_type": "interactive", "card": card}, timeout=10)
        ok = resp.ok
        print(f"  {'✅' if ok else '❌'} 飞书: {resp.status_code}" + (f" {resp.text[:80]}" if not ok else ""))
        return ok
    except Exception as e:
        print(f"  ❌ 飞书异常: {e}")
        return False

# ============================================================
#   状态管理
# ============================================================
def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"day": "", "stocks": {}}

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

    if not (MARKET_OPEN <= current_time <= MARKET_CLOSE):
        print(f"  ⏰ 非交易时段，跳过")
        return

    state = load_state()
    if state.get("day") != today_str:
        state = {"day": today_str, "stocks": {}}
        print(f"  📅 新交易日，重置告警状态\n")

    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    triggered = []

    for s in STOCKS:
        code = s["code"]
        name = s["name"]
        key = code  # state key

        if key not in state["stocks"]:
            state["stocks"][key] = {"buy_alerted": False, "sell_alerted": False}

        print(f"  ── {name} ({code}) ──")

        # 数据
        min_bars = s["rsi_p"] + 5
        df = load_minute_data(code, min_bars)
        if df.empty:
            print(f"  ❌ 无数据")
            continue

        closes = df["close"].tolist()
        rsis = compute_rsi(closes, s["rsi_p"])
        if not rsis:
            print(f"  ❌ 数据不足")
            continue

        cur_rsi = rsis[-1]
        print(f"  📊 {len(df)} bars | RSI({s['rsi_p']})={cur_rsi:.1f}")

        # 趋势判断
        trend_ok, idx_close, idx_ma, _ = load_index_trend(s["idx"], s["ma"])
        trend_str = f" {s['idx_name']}: {idx_close:.0f} MA{s['ma']}: {idx_ma:.0f} {'✅' if trend_ok else '❌'}" if idx_close else " 指数N/A"
        print(f"  {trend_str}")

        # 信号
        buy_sig, sell_sig = detect_signals(rsis, s["os"], s["ob"], trend_ok)

        st = state["stocks"][key]

        if buy_sig and not st["buy_alerted"]:
            title = f"🟢 {name} RSI 买入"
            body = (f"**{name} ({code})**\n\n"
                    f"RSI({s['rsi_p']})={cur_rsi:.0f} < {s['os']}\n"
                    f"当前价: {closes[-1]:.4f}\n"
                    f"时间: {df['time'].iloc[-1].strftime('%H:%M')}\n\n"
                    f"{s['idx_name']}: {'✅ 趋势向上' if trend_ok else '⚠️ 趋势向下'}\n\n"
                    f"操作建议：{'关注买入，设好止损' if trend_ok else '趋势不佳，谨慎参与'}")
            send_feishu(webhook, title, body, f"{code} 实时监控")
            st["buy_alerted"] = True
            triggered.append(f"{code}🟢")

        if sell_sig and not st["sell_alerted"]:
            title = f"🔴 {name} RSI 卖出"
            body = (f"**{name} ({code})**\n\n"
                    f"RSI({s['rsi_p']})={cur_rsi:.0f} > {s['ob']}\n"
                    f"当前价: {closes[-1]:.4f}\n"
                    f"时间: {df['time'].iloc[-1].strftime('%H:%M')}\n\n"
                    f"操作建议：考虑止盈/减仓")
            send_feishu(webhook, title, body, f"{code} 实时监控")
            st["sell_alerted"] = True
            triggered.append(f"{code}🔴")

        if not buy_sig and not sell_sig:
            print(f"  📋 无信号")

    # 收盘汇总
    if dtime(14, 55) <= current_time <= dtime(15, 5):
        if not state.get("eod_summary"):
            lines = []
            for s in STOCKS:
                code = s["code"]
                st = state["stocks"].get(code, {})
                status = "🟢 已触发买入" if st.get("buy_alerted") else ("🔴 已触发卖出" if st.get("sell_alerted") else "⚪ 无信号")
                lines.append(f"- {s['name']} ({code}): {status}")
            body = "**📊 今日监控简报**\n\n" + "\n".join(lines) + "\n\n交易时段结束，明日继续监控。"
            send_feishu(webhook, "📊 收盘简报", body, "多标的总览")
            state["eod_summary"] = True

    save_state(state)
    summary = ", ".join(triggered) if triggered else "无信号"
    print(f"\n  ✅ 完成: {summary}")


if __name__ == "__main__":
    main()
