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
    print(f"  ── 市场量化指标 ──")
    market = svc.analyze_market()
    print(f"  涨停: {market['zt_count']} 家 | 跌停: {market['dt_count']} 家")
    if market.get("volume_ratio"):
        print(f"  成交额: {market['volume_ratio']:.2f} 倍于20日均值")
    print(f"  量化温度: {market['temperature']:.0f}/100  ({market['label_cn']})")

    # 2. 大V情绪
    print(f"\n  ── 大V情绪跟踪 ──")
    kols = svc.analyze_kols()
    print(f"  综合: {kols['avg_score']:+.3f} ({kols['stance']})")
    for kol in kols.get("kols", []):
        em = {"positive": "📈", "negative": "📉", "neutral": "⚪"}.get(
            kol.get("stance", "neutral"), "⚪")
        print(f"  {em} {kol['name']}: {kol.get('score', 0):+.3f} "
              f"({kol.get('stance', '?')})  来源 {kol.get('sources', 0)} 条")
        for s in kol.get("snippets", [])[:2]:
            print(f"      - {s['title'][:50]}")

    # 3. 综合分析
    print(f"\n  ── 综合判断 ──")
    result = svc.analyze_all()
    print(f"  综合得分: {result['combined_score']:.1f}/100")
    print(f"  判断: {result['label_cn']}")

    # 飞书推送
    webhook = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook:
        ok = svc.send_feishu(webhook, result)
        print(f"\n  {'✅' if ok else '❌'} 飞书推送完成")
    else:
        print(f"\n  ⏭  FEISHU_WEBHOOK_URL 未设置，跳过飞书推送")

    print(f"\n  ✅ 情绪分析完成")


if __name__ == "__main__":
    main()
