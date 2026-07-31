"""A 股市场情绪分析服务

两大部分:
1. 量化市场情绪指标: 涨停/跌停家数、涨跌家数比、成交额热度
2. 大V情绪跟踪: 网页搜索跟踪指定大V的近期言论并打分

输出: 市场温度 (0~100), 情绪标签 (hot/cold/neutral), 大V群体观点

用法:
    svc = ChinaSentimentService()
    result = svc.analyze_market()          # 市场整体情绪
    kol_result = svc.analyze_kols()        # 大V情绪
    combined = svc.analyze_all()           # 综合
"""

from __future__ import annotations

import html
import logging
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

logger = logging.getLogger(__name__)

# ── 中文金融情绪词典 ──────────────────────────────────────────

BULLISH_KEYWORDS = [
    "大涨", "涨停", "创新高", "突破", "利好", "放量", "拉升", "反弹",
    "反攻", "看好", "抄底", "加仓", "买入", "增持", "做多", "看涨",
    "超预期", "扭亏", "拐点", "催化", "风口", "主线", "龙头", "强势",
    "回暖", "复苏", "触底", "爆发", "领涨", "大单", "主力",
    "北向资金", "净流入", "降准", "降息", "宽松", "重组", "并购",
    "业绩预增", "利润增长", "分红", "回购", "牛市", "上车",
]

BEARISH_KEYWORDS = [
    "大跌", "跌停", "新低", "破位", "利空", "缩量", "跳水", "下探",
    "撤退", "看空", "减仓", "卖出", "减持", "做空", "看跌", "清仓",
    "不及预期", "暴雷", "亏损", "退市", "崩盘", "踩踏", "割肉",
    "恐慌", "回调", "出货", "砸盘", "主力流出", "北向资金净流出",
    "加息", "紧缩", "监管", "立案", "处罚", "调查", "风险提示",
    "业绩预减", "利润下滑", "营收下降", "债务", "违约", "裁员",
    "贸易战", "制裁", "封杀", "停牌", "质押平仓", "熊市", "销户",
    "认输", "割肉离场", "别玩了", "垃圾", "亏麻", "哭",
]

# 极端情绪词（用于冰点/热点判断）
EXTREME_BEARISH = ["清仓", "销户", "割肉", "认输", "亏麻", "崩盘", "退市", "别玩了"]
EXTREME_BULLISH = ["牛市", "满仓", "梭哈", "涨停潮", "踏空", "冲天", "主升浪"]


def _score_text(text: str) -> float:
    """正负面打分，返回 [-1, 1]"""
    if not text:
        return 0.0
    score = 0.0
    matched = 0

    for kw in BULLISH_KEYWORDS:
        if kw in text:
            score += 1.0
            matched += 1
    for kw in BEARISH_KEYWORDS:
        if kw in text:
            score -= 1.0
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


# ── 大V配置 ───────────────────────────────────────────────────

DEFAULT_KOLS = [
    {"name": "峰哥亡命天涯",
     "search_terms": ["峰哥亡命天涯 清仓", "峰哥亡命天涯 A股", "峰哥亡命天涯 股市"]},
    {"name": "小冰冰",
     "search_terms": ["小冰冰 炒股", "小冰冰 A股", "小冰冰 股市 复盘"]},
]


class KOLSentimentTracker:
    """大V情绪跟踪 - 多源网页搜索近期言论并打分

    搜索源: DuckDuckGo(优先) → 必应 → 360 → 搜狗
    GH Actions(美国服务器) 上 DDG 稳定; 国内网络下自动切换。
    """

    def __init__(self, kols: list[dict] | None = None):
        self.kols = kols or DEFAULT_KOLS

    def _ddg(self, query: str, max_results: int) -> list[dict]:
        url = "https://lite.duckduckgo.com/lite/"
        resp = requests.post(
            url, data={"q": query, "kl": "cn-zh"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=8,
        )
        if resp.status_code != 200:
            return []
        links = re.findall(
            r'<a[^>]*class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            resp.text, re.DOTALL,
        )
        if not links:
            links = re.findall(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>',
                resp.text, re.DOTALL,
            )
        out = []
        for url, title in links[:max_results]:
            clean = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            if clean:
                out.append({"title": clean, "url": url})
        return out

    def _bing(self, query: str, max_results: int) -> list[dict]:
        resp = requests.get(
            "https://cn.bing.com/search", params={"q": query},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=8,
        )
        if resp.status_code != 200:
            return []
        blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
        out = []
        for b in blocks[:max_results]:
            m = re.search(r'<h2>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.DOTALL)
            if m:
                title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                if title:
                    out.append({"title": title, "url": m.group(1)})
        return out

    def _sogou(self, query: str, max_results: int) -> list[dict]:
        s = requests.Session()
        s.headers.update({"User-Agent": "Mozilla/5.0"})
        s.get("https://www.sogou.com/", timeout=8)
        resp = s.get("https://www.sogou.com/web", params={"query": query}, timeout=8)
        if resp.status_code != 200:
            return []
        links = re.findall(
            r'<h3[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
        out = []
        for url, title in links[:max_results]:
            clean = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            if clean:
                out.append({"title": clean, "url": url})
        return out

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """多源搜索，返回首个成功源的结果"""
        for name, fn in [
            ("duckduckgo", self._ddg),
            ("bing", self._bing),
            ("sogou", self._sogou),
        ]:
            try:
                results = fn(query, max_results)
                if results:
                    logger.debug("search %s via %s: %d 条", query, name, len(results))
                    return results
            except Exception as e:
                logger.debug("search %s via %s failed: %s", query, name, e)
        return []

    def analyze_kol(self, kol: dict) -> dict:
        """分析单个大V情绪"""
        name = kol["name"]
        all_results: list[dict] = []
        for term in kol.get("search_terms", [name]):
            for r in self.search(term):
                all_results.append(r)

        if not all_results:
            return {
                "name": name, "score": 0.0, "stance": "neutral",
                "sources": 0, "snippets": [], "raw": [],
            }

        scores = []
        snippets = []
        for r in all_results:
            title = r["title"]
            s = _score_text(title)
            scores.append(s)
            snippets.append({"title": title, "url": r["url"], "score": round(s, 2)})

        avg = sum(scores) / len(scores)
        stance = _classify(avg)

        return {
            "name": name,
            "score": round(avg, 3),
            "stance": stance,
            "sources": len(snippets),
            "snippets": sorted(snippets, key=lambda x: abs(x["score"]), reverse=True)[:5],
        }

    def analyze_all(self, max_workers: int = 4) -> dict:
        """分析全部大V"""
        results = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            fut = {pool.submit(self.analyze_kol, kol): kol["name"] for kol in self.kols}
            for f in as_completed(fut):
                try:
                    results.append(f.result())
                except Exception as e:
                    logger.error("KOL %s: %s", fut[f], e)
                    results.append({"name": fut[f], "score": 0.0, "stance": "neutral",
                                    "sources": 0, "snippets": []})

        scores = [r["score"] for r in results if r.get("sources", 0) > 0]
        avg = sum(scores) / len(scores) if scores else 0.0
        return {"kols": results, "avg_score": round(avg, 3), "stance": _classify(avg)}


# ── 市场量化指标 ──────────────────────────────────────────────


def _run_with_timeout(fn, timeout: float, *args, **kwargs):
    """在线程中运行 fn，超时则返回 None（避免外部接口无超时挂死）"""
    result = {}

    def _worker():
        try:
            result["value"] = fn(*args, **kwargs)
        except Exception as e:
            result["error"] = e

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None
    if "error" in result:
        raise result["error"]
    return result.get("value")


class MarketSentimentAnalyzer:
    """市场量化情绪指标"""

    def __init__(self, date: str | None = None):
        self.date = date or datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")

    def _get_market_breadth(self) -> dict:
        """涨停/跌停家数"""
        zt_count, dt_count = -1, -1
        try:
            import akshare as ak
            zt = _run_with_timeout(ak.stock_zt_pool_em, 30, date=self.date)
            zt_count = len(zt) if zt is not None else 0
        except Exception as e:
            logger.debug("zt pool failed: %s", e)

        try:
            import akshare as ak
            dt = _run_with_timeout(ak.stock_zt_pool_dtgc_em, 30, date=self.date)
            dt_count = len(dt) if dt is not None else 0
        except Exception as e:
            logger.debug("dt pool failed: %s", e)

        return {"zt_count": zt_count, "dt_count": dt_count}

    def _get_market_volume_trend(self) -> dict:
        """市场成交量 vs 20日均值 (新浪日线)"""
        try:
            import akshare as ak
            df = _run_with_timeout(ak.stock_zh_index_daily, 30, symbol="sh000001")
            if df is None or df.empty:
                return {"amount": None, "ma20": None, "ratio": None}
            df = df.sort_values("date").tail(25)
            latest = df.iloc[-1]
            ma20 = df["volume"].iloc[:-1].tail(20).mean()
            if not ma20:
                return {"amount": None, "ma20": None, "ratio": None}
            return {
                "amount": float(latest["volume"]),
                "ma20": float(ma20),
                "ratio": float(latest["volume"] / ma20),
            }
        except Exception as e:
            logger.debug("volume trend failed: %s", e)
            return {"amount": None, "ma20": None, "ratio": None}

    def analyze(self) -> dict:
        """计算市场情绪温度 (0~100)"""
        breadth = self._get_market_breadth()
        volume = self._get_market_volume_trend()

        zt = breadth.get("zt_count", -1)
        dt = breadth.get("dt_count", -1)
        ratio = volume.get("ratio")

        # 温度分项
        temp_zt = 0.0
        if zt >= 0:
            # 涨停多 = 热
            temp_zt = min(100, zt * 2.5)  # 40只涨停≈100分

        temp_dt = 0.0
        if dt >= 0:
            # 跌停多 = 冷
            temp_dt = min(100, dt * 10)  # 10只跌停≈100分(冷)

        temp_vol = 50.0
        if ratio:
            # 成交额放大 = 热
            temp_vol = min(100, max(0, 50 + (ratio - 1) * 100))

        # 涨停贡献热，跌停贡献冷
        temperature = 0.5 * temp_zt - 0.3 * temp_dt + 0.2 * temp_vol
        temperature = max(0.0, min(100.0, temperature))

        # 标签
        if temperature >= 70:
            label = "hot"       # 热点/狂热
            label_cn = "🔥 热点（市场狂热）"
        elif temperature <= 30:
            label = "cold"      # 冰点/恐慌
            label_cn = "🧊 冰点（市场恐慌）"
        else:
            label = "neutral"
            label_cn = "⚪ 正常"

        return {
            "date": self.date,
            "zt_count": zt,
            "dt_count": dt,
            "volume_ratio": round(ratio, 2) if ratio else None,
            "temperature": round(temperature, 1),
            "label": label,
            "label_cn": label_cn,
            "breadth": breadth,
            "volume": volume,
        }


# ── 主服务 ────────────────────────────────────────────────────


class ChinaSentimentService:
    """A 股市场情绪综合分析"""

    def __init__(self, kols: list[dict] | None = None):
        self.kol_tracker = KOLSentimentTracker(kols)
        self.market_analyzer = MarketSentimentAnalyzer()

    def analyze_market(self) -> dict:
        """市场量化情绪"""
        return self.market_analyzer.analyze()

    def analyze_kols(self) -> dict:
        """大V情绪"""
        return self.kol_tracker.analyze_all()

    def analyze_all(self, market: dict | None = None, kols: dict | None = None) -> dict:
        """综合分析，输出冰点/热点判断"""
        market = market if market is not None else self.analyze_market()
        kols = kols if kols is not None else self.analyze_kols()

        # 综合: 70% 量化 + 30% 大V
        market_temp = market.get("temperature", 50)
        kol_score = kols.get("avg_score", 0.0)  # -1~1
        kol_temp = (kol_score + 1) / 2 * 100  # 映射到 0~100

        combined = round(0.7 * market_temp + 0.3 * kol_temp, 1)

        if combined >= 70:
            label = "hot"
            label_cn = "🔥 热点（市场狂热，注意风险）"
        elif combined <= 30:
            label = "cold"
            label_cn = "🧊 冰点（市场恐慌，可能是机会）"
        else:
            label = "neutral"
            label_cn = "⚪ 正常"

        return {
            "date": market.get("date"),
            "market": market,
            "kols": kols,
            "combined_score": combined,
            "label": label,
            "label_cn": label_cn,
        }

    def format_feishu(self, result: dict) -> tuple[str, str, str]:
        """格式化综合情绪为飞书卡片"""
        market = result.get("market", {})
        kols = result.get("kols", {})

        emoji = {"hot": "🔥", "cold": "🧊", "neutral": "⚪"}
        title = f"{emoji.get(result.get('label', 'neutral'), '⚪')} A股情绪 {result.get('combined_score', 0):.0f}/100"

        lines = [f"**{result.get('label_cn', '')}**\n"]

        # 市场量化
        lines.append(f"**📊 市场温度: {result.get('combined_score', 0):.1f}/100**")
        zt = market.get("zt_count")
        dt = market.get("dt_count")
        if zt is not None and dt is not None:
            lines.append(f"- 涨停 **{zt}** 家 / 跌停 **{dt}** 家")
        vr = market.get("volume_ratio")
        if vr:
            lines.append(f"- 成交额 {vr:.2f} 倍于20日均值")
        lines.append(f"- 量化温度: {market.get('temperature', 0):.0f}/100")

        # 大V情绪
        lines.append(f"\n**🎙️ 大V情绪: {kols.get('avg_score', 0):+.2f} ({kols.get('stance', 'neutral')})**")
        for kol in kols.get("kols", []):
            k_score = kol.get("score", 0)
            k_stance = kol.get("stance", "neutral")
            k_em = {"positive": "📈", "negative": "📉", "neutral": "⚪"}.get(k_stance, "⚪")
            lines.append(f"- {k_em} **{kol['name']}**: {k_score:+.2f} ({k_stance})")
            if kol.get("snippets"):
                top = kol["snippets"][0]
                lines.append(f"  `{top['title'][:45]}`")

        tag = f"A股情绪 {result.get('combined_score', 0):.0f}/100 · {datetime.now(timezone(timedelta(hours=8))).strftime('%m/%d %H:%M')}"
        return title, "\n".join(lines), tag

    def send_feishu(self, webhook_url: str, result: dict) -> bool:
        """推送综合情绪到飞书"""
        if not webhook_url:
            return False
        title, body, tag = self.format_feishu(result)
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "lark_md", "content": title},
                "template": "red" if result.get("label") == "hot" else (
                    "blue" if result.get("label") == "cold" else "grey"),
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": body}},
                {"tag": "hr"},
                {"tag": "note", "element": {"tag": "plain_text",
                  "content": f"{tag} · 数据: akshare + DuckDuckGo"}},
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
