#!/usr/bin/env python3
"""A 股市场情绪日报 — 量化指标 + 大V情绪 → 飞书推送"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import logging
from datetime import datetime, timezone, timedelta

from src.services.china_sentiment_service import ChinaSentimentService


def main():
    now = datetime.now(timezone(timedelta(hours=8)))
    print(f"🕐 {now.strftime('%Y-%m-%d %H:%M:%S')} CST\n")
    print(f"  A 股市场情绪分析\n")

    svc = ChinaSentimentService()

    # 1. 市场量化情绪
    print(f"  ── 市场量化指标 ──", flush=True)
    market = svc.analyze_market()
    print(f"  涨停: {market['zt_count']} 家 | 跌停: {market['dt_count']} 家", flush=True)
    if market.get("volume_ratio"):
        print(f"  成交额: {market['volume_ratio']:.2f} 倍于20日均值", flush=True)
    print(f"  量化温度: {market['temperature']:.0f}/100  ({market['label_cn']})", flush=True)

    # 2. 大V情绪
    print(f"\n  ── 大V情绪跟踪 ──", flush=True)
    kols = svc.analyze_kols()
    print(f"  综合: {kols['avg_score']:+.3f} ({kols['stance']})", flush=True)
    for kol in kols.get("kols", []):
        em = {"positive": "📈", "negative": "📉", "neutral": "⚪"}.get(
            kol.get("stance", "neutral"), "⚪")
        print(f"  {em} {kol['name']}: {kol.get('score', 0):+.3f} "
              f"({kol.get('stance', '?')})  来源 {kol.get('sources', 0)} 条", flush=True)
        for s in kol.get("snippets", [])[:2]:
            print(f"      - {s['title'][:50]}", flush=True)

    # 3. 综合分析（复用已算好的市场与大V结果）
    print(f"\n  ── 综合判断 ──", flush=True)
    result = svc.analyze_all(market=market, kols=kols)
    print(f"  综合得分: {result['combined_score']:.1f}/100", flush=True)
    print(f"  判断: {result['label_cn']}", flush=True)

    # 飞书推送
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook:
        ok = svc.send_feishu(webhook, result)
        print(f"\n  {'✅' if ok else '❌'} 飞书推送完成", flush=True)
    else:
        print(f"\n  ⏭  FEISHU_WEBHOOK_URL 未设置，跳过飞书推送", flush=True)

    print(f"\n  ✅ 情绪分析完成", flush=True)


if __name__ == "__main__":
    main()
