#!/usr/bin/env python3
"""A 股市场情绪日报 — 东方财富新闻分析 → 飞书推送"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
from datetime import datetime, time as dtime, timedelta, timezone

from src.services.china_sentiment_service import ChinaSentimentService

CST = timezone(timedelta(hours=8))
STOCKS = [
    ("589020", "科创半导体"),
    ("159500", "创业板ETF"),
    ("515880", "通信ETF"),
    ("588220", "科创ETF"),
]


def main():
    now = datetime.now(CST)
    print(f"🕐 {now.strftime('%Y-%m-%d %H:%M:%S')} CST")
    print(f"  A 股市场情绪分析\n")

    svc = ChinaSentimentService()
    results = svc.analyze_batch(STOCKS)

    for r in results:
        if "error" in r:
            print(f"  ❌ {r.get('name', r['code'])}: {r['error']}")
            continue
        em = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            r.get("sentiment", "neutral"), "⚪"
        )
        print(f"  {em} {r['name']:>8} ({r['code']})  "
              f"情绪={r['score']:+.3f}  "
              f"新闻={r['total_articles']}条  "
              f"P={r['positive_articles']}/N={r['negative_articles']}")
        bullish = r.get("bullish_keywords", [])
        bearish = r.get("bearish_keywords", [])
        if bullish or bearish:
            parts = []
            if bullish:
                parts.append(f"📈{' '.join(bullish[:3])}")
            if bearish:
                parts.append(f"📉{' '.join(bearish[:3])}")
            print(f"    {' '.join(parts)}")
        top = r.get("top_news", [])
        if top:
            print(f"    📰 {top[0]['title'][:70]}")

    # 飞书推送
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook:
        ok = svc.send_feishu(webhook, results)
        print(f"\n  {'✅' if ok else '❌'} 飞书推送完成")
    else:
        print(f"\n  ⏭  FEISHU_WEBHOOK_URL 未设置，跳过飞书推送")

    print(f"\n  ✅ 情绪分析完成")


if __name__ == "__main__":
    main()
