"""A 股市场情绪分析服务

数据源: 东方财富个股新闻 (akshare)
情绪评分: 基于金融关键词词典的正负面打分

用法:
    svc = ChinaSentimentService()
    result = svc.analyze("589020")           # 单只
    results = svc.analyze_batch([...])        # 批量
    svc.send_feishu(webhook_url, results)     # 推飞书
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ── 中文金融情绪词典 ──────────────────────────────────────────
# 用于关键词匹配打分（无需外部 NLP 依赖）
BULLISH_KEYWORDS = [
    "大涨", "涨停", "创新高", "突破", "利好", "放量", "拉升", "反弹",
    "反攻", "看好", "抄底", "加仓", "买入", "增持", "做多", "看涨",
    "超预期", "扭亏", "拐点", "催化", "风口", "主线", "龙头", "强势",
    "回暖", "复苏", "触底", "爆发", "领涨", "领跑", "大单", "主力",
    "北向资金", "净流入", "政策支持", "扶持", "减税", "降准", "降息",
    "宽松", "注入", "重组", "并购", "订单", "中标", "合同",
    "业绩预增", "利润增长", "营收增长", "分红", "回购",
]

BEARISH_KEYWORDS = [
    "大跌", "跌停", "新低", "破位", "利空", "缩量", "跳水", "下探",
    "撤退", "看空", "减仓", "卖出", "减持", "做空", "看跌", "清仓",
    "不及预期", "暴雷", "亏损", "退市", "崩盘", "踩踏",
    "恐慌", "回调", "出货", "砸盘", "主力流出", "北向资金净流出",
    "加息", "紧缩", "监管", "立案", "处罚", "调查", "风险提示",
    "业绩预减", "利润下滑", "营收下降", "债务", "违约", "裁员",
    "贸易战", "制裁", "封杀", "停牌", "质押平仓",
]

INTENSIFIERS = {
    "大幅": 1.5, "明显": 1.3, "严重": 1.5, "持续": 1.2,
    "加速": 1.3, "全面": 1.2, "显著": 1.3, "急剧": 1.5,
}

STOCK_NAMES = {
    "589020": "科创半导体",
    "159500": "创业板ETF",
    "515880": "通信ETF",
    "588220": "科创ETF",
}


# ── 数据获取 ──────────────────────────────────────────────────


def _fetch_eastmoney_news(code: str, max_items: int = 30) -> list[dict]:
    """东方财富个股新闻 (akshare)"""
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=code)
        if df is None or df.empty:
            return []
        if "新闻标题" not in df.columns:
            return []
        items = []
        for _, row in df.head(max_items).iterrows():
            items.append({
                "title": str(row.get("新闻标题", "")),
                "content": str(row.get("新闻内容", "")),
                "time": str(row.get("发布时间", "")),
                "source": str(row.get("文章来源", "东方财富")),
            })
        return items
    except Exception as e:
        logger.debug("akshare news failed for %s: %s", code, e)
    return []


# ── 情绪评分 ──────────────────────────────────────────────────


def _score_text(text: str) -> float:
    """对单段文本做正负面打分，返回 [-1, 1]"""
    if not text:
        return 0.0
    score = 0.0
    matched = 0

    for kw in BULLISH_KEYWORDS:
        if kw in text:
            w = 1.0
            for intensifier, factor in INTENSIFIERS.items():
                if intensifier in text:
                    w = factor
                    break
            score += w
            matched += 1

    for kw in BEARISH_KEYWORDS:
        if kw in text:
            w = 1.0
            for intensifier, factor in INTENSIFIERS.items():
                if intensifier in text:
                    w = factor
                    break
            score -= w
            matched += 1

    if matched == 0:
        return 0.0
    return max(-1.0, min(1.0, score / math.sqrt(matched + 1)))


def _classify(score: float) -> str:
    if score > 0.15:
        return "positive"
    if score < -0.15:
        return "negative"
    return "neutral"


# ── 主服务 ────────────────────────────────────────────────────


class ChinaSentimentService:
    """A 股市场情绪分析服务"""

    def __init__(self):
        self._fetchers = [_fetch_eastmoney_news]

    def analyze(self, code: str, name: str = "") -> dict[str, Any]:
        """分析单只 ETF 的情绪

        返回:
        {
            "code", "name",
            "score": float (-1~1),
            "sentiment": str (positive/neutral/negative),
            "total_articles", "positive_articles", "negative_articles",
            "bullish_keywords", "bearish_keywords",
            "top_news": [{title, source, sentiment, score}],
            "source": str,
        }
        """
        name = name or STOCK_NAMES.get(code, code)
        all_articles: list[dict] = []

        for fetcher in self._fetchers:
            try:
                arts = fetcher(code)
                if arts:
                    all_articles.extend(arts)
            except Exception as e:
                logger.debug("%s fetcher failed: %s", code, e)

        if not all_articles:
            return self._empty_result(code, name)

        scored: list[dict] = []
        total = 0.0
        pos = neg = 0
        bullish_kw: set[str] = set()
        bearish_kw: set[str] = set()

        for art in all_articles:
            text = f"{art.get('title', '')} {art.get('content', '')}"
            s = _score_text(text)
            sent = _classify(s)
            art["score"] = s
            art["sentiment"] = sent
            scored.append(art)
            total += s
            if sent == "positive":
                pos += 1
            elif sent == "negative":
                neg += 1
            for kw in BULLISH_KEYWORDS:
                if kw in text:
                    bullish_kw.add(kw)
            for kw in BEARISH_KEYWORDS:
                if kw in text:
                    bearish_kw.add(kw)

        avg = total / max(len(scored), 1)

        sorted_arts = sorted(scored, key=lambda x: abs(x.get("score", 0)), reverse=True)
        top = [
            {"title": a["title"], "source": a["source"],
             "sentiment": a["sentiment"], "score": round(a["score"], 2)}
            for a in sorted_arts[:5]
        ]

        return {
            "code": code, "name": name,
            "score": round(avg, 3), "sentiment": _classify(avg),
            "total_articles": len(scored),
            "positive_articles": pos, "negative_articles": neg,
            "bullish_keywords": sorted(bullish_kw),
            "bearish_keywords": sorted(bearish_kw),
            "top_news": top,
            "source": "东方财富",
        }

    @staticmethod
    def _empty_result(code: str, name: str) -> dict:
        return {
            "code": code, "name": name,
            "score": 0.0, "sentiment": "neutral",
            "total_articles": 0, "positive_articles": 0, "negative_articles": 0,
            "bullish_keywords": [], "bearish_keywords": [],
            "top_news": [], "source": "",
        }

    def analyze_batch(self, stocks: list[tuple[str, str]],
                      max_workers: int = 4) -> list[dict[str, Any]]:
        """批量分析"""
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut = {pool.submit(self.analyze, c, n): (c, n) for c, n in stocks}
            for f in as_completed(fut):
                try:
                    results.append(f.result())
                except Exception as e:
                    c, n = fut[f]
                    logger.error("%s(%s): %s", n, c, e)
                    results.append({"code": c, "name": n, "error": str(e)})
        return results

    def format_feishu(self, result: dict) -> tuple[str, str, str]:
        """格式化单条情绪为飞书卡片"""
        name = result.get("name", result.get("code", ""))
        em = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
            result.get("sentiment", "neutral"), "⚪")
        title = f"{em} {name} 市场情绪"
        lines = [
            f"**{name} ({result['code']})**\n",
            f"综合情绪: **{result['score']:.2f}** ({result['sentiment']})",
            f"新闻覆盖: {result['total_articles']} 条 "
            f"(🟢{result['positive_articles']}/🔴{result['negative_articles']})",
        ]
        bullish = result.get("bullish_keywords", [])
        bearish = result.get("bearish_keywords", [])
        if bullish:
            lines.append(f"\n📈 积极信号: {' '.join(bullish[:5])}")
        if bearish:
            lines.append(f"📉 消极信号: {' '.join(bearish[:5])}")
        top = result.get("top_news", [])
        if top:
            lines.append("\n📰 热点新闻:")
            for n in top[:3]:
                se = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
                    n["sentiment"], "⚪")
                lines.append(f"  {se} {n['title'][:60]}")
        return title, "\n".join(lines), f"{result['code']} 情绪 {result['score']:.2f}"

    def send_feishu(self, webhook_url: str, results: list[dict],
                    title: str = "📊 市场情绪日报") -> bool:
        """推送情绪日报到飞书"""
        if not webhook_url:
            return False
        lines = [f"**{title}**\n"]
        for r in results:
            if "error" in r:
                lines.append(f"- {r.get('name', r['code'])}: ❌ {r['error']}")
                continue
            em = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}.get(
                r.get("sentiment", "neutral"), "⚪")
            s = r.get("score", 0)
            lines.append(
                f"- {em} **{r['name']}** ({r['code']}): "
                f"情绪 **{s:+.2f}** | 新闻 {r['total_articles']}条 "
                f"({r['positive_articles']}/{r['negative_articles']})"
            )
            bullish = r.get("bullish_keywords", [])
            bearish = r.get("bearish_keywords", [])
            if bullish or bearish:
                parts = []
                if bullish:
                    parts.append(f"📈{' '.join(bullish[:3])}")
                if bearish:
                    parts.append(f"📉{' '.join(bearish[:3])}")
                lines.append(f"  {' '.join(parts)}")
        lines.append(
            f"\n📡 {datetime.now(timezone(timedelta(hours=8))).strftime('%m/%d %H:%M')}")
        body = "\n".join(lines)

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "lark_md", "content": title},
                "template": "blue",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": body}},
                {"tag": "hr"},
                {"tag": "note", "element": {"tag": "plain_text",
                  "content": "数据: 东方财富个股新闻"}},
            ],
        }
        try:
            resp = requests.post(
                webhook_url, json={"msg_type": "interactive", "card": card}, timeout=10)
            ok = resp.ok
            logger.info("飞书: %s", "✅" if ok else f"❌ {resp.status_code}")
            return ok
        except Exception as e:
            logger.warning("飞书异常: %s", e)
            return False
