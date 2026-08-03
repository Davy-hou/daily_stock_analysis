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
import os
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

# 动作词：直接表达大V操作/立场，权重 2 倍（市场描述词不干扰观点判断）
BULLISH_ACTIONS = [
    "抄底", "加仓", "买入", "增持", "做多", "看多", "敢买", "满仓",
    "梭哈", "低吸", "上车", "反弹", "反攻", "拉升", "打光",
]
BEARISH_ACTIONS = [
    "清仓", "减仓", "卖出", "减持", "做空", "看空", "割肉", "销户",
    "认输", "撤退", "离场", "出清", "跑路", "止损", "抛售",
]


def _score_text(text: str) -> float:
    """正负面打分，返回 [-1, 1]

    动作词（加仓/清仓等）权重 2 倍，市场描述词（大跌/大涨）权重 1 倍，
    避免“大跌敢买”这类逆向表达被误判为看空。
    """
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
    # 动作词 2 倍权重
    for kw in BULLISH_ACTIONS:
        if kw in text:
            score += 2.0
            matched += 2
    for kw in BEARISH_ACTIONS:
        if kw in text:
            score -= 2.0
            matched += 2

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
    {"name": "峰哥亡命天涯", "style": "散户反指",
     "search_terms": ["峰哥亡命天涯 清仓 销户", "峰哥亡命天涯 A股 最新"]},
    {"name": "淘气天尊", "style": "散户技术派",
     "search_terms": ["淘气天尊 收评 抄底", "淘气天尊 A股 反攻 最新"]},
    {"name": "但斌", "style": "私募价值派",
     "search_terms": ["但斌 最新观点 股市", "但斌 看好 A股 观点", "但斌 人工智能 十年牛市"]},
    {"name": "月风_投资笔记", "style": "私募宏观",
     "search_terms": ["月风投资笔记 股市 观点", "吴悦风 月风 A股 最新"]},
    {"name": "李大霄", "style": "机构派",
     "search_terms": ["李大霄 最新 股市 观点", "李大霄 A股 底部 观点"]},
    {"name": "杨德龙", "style": "机构派",
     "search_terms": ["杨德龙 看多 A股", "杨德龙 牛市 观点", "杨德龙 救市 A股"]},
    {"name": "陈宇", "style": "私募价值派",
     "search_terms": ["神农投资 陈宇 牛市 看好", "陈宇 神农 A股 机会"]},
]


_ZH_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


_HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u30ff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def _is_relevant(result: dict) -> bool:
    """过滤无关结果：标题须以中文为主，且不含明显垃圾关键词"""
    title = result.get("title", "")
    if not title:
        return False
    # 日文/韩文/纯英文标题排除
    if not _ZH_CHAR_RE.search(title):
        return False
    if _HIRAGANA_KATAKANA_RE.search(title):
        return False
    zh_chars = len(_ZH_CHAR_RE.findall(title))
    latin_chars = len(_LATIN_RE.findall(title))
    if latin_chars > zh_chars * 2:
        return False
    junk = ["sex", "porn", "comics", "adult", "muses", "gambling", "casino",
            "下载器", "成人", "色情", "裸聊", "博彩", "彩票", "quote of the day"]
    lower = title.lower()
    if any(j in lower for j in junk):
        return False
    return True


def _clean_results(results: list[dict]) -> list[dict]:
    return [r for r in results if _is_relevant(r)]


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
        snippets = re.findall(r'class="result-snippet"[^>]*>(.*?)</td>', resp.text, re.DOTALL)
        if not links:
            # 兜底: 通用 <a href> 解析
            links = re.findall(
                r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>', resp.text, re.DOTALL)
            snippets = []
        out = []
        for i, (url, title) in enumerate(links[:max_results]):
            clean = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            if not clean:
                continue
            snippet = ""
            if i < len(snippets):
                snippet = html.unescape(re.sub(r"<[^>]+>", "", snippets[i])).strip()
            out.append({"title": clean, "url": url, "snippet": snippet})
        return out

    def _bing_rss(self, query: str, max_results: int) -> list[dict]:
        """必应 RSS 接口，返回结构化结果"""
        resp = requests.get(
            "https://www.bing.com/search",
            params={"q": query, "format": "rss"},
            headers={"User-Agent": "Mozilla/5.0"}, timeout=8,
        )
        if resp.status_code != 200:
            return []
        items = re.findall(
            r'<item>.*?<title>(.*?)</title>.*?<link>(.*?)</link>', resp.text, re.DOTALL)
        out = []
        for title, url in items[:max_results]:
            clean = html.unescape(title).strip()
            if clean and clean != "Bing: " + query:
                out.append({"title": clean, "url": html.unescape(url).strip()})
        return out

    def _bing(self, query: str, max_results: int) -> list[dict]:
        # 依次尝试国际版 / 中文版 bing，取首个有结果的
        for base in ("https://www.bing.com/search", "https://cn.bing.com/search"):
            try:
                resp = requests.get(
                    base, params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0"}, timeout=8,
                )
                if resp.status_code != 200:
                    continue
                blocks = re.findall(r'<li class="b_algo"[^>]*>(.*?)</li>', resp.text, re.DOTALL)
                out = []
                for b in blocks[:max_results]:
                    m = re.search(r'<h2>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.DOTALL)
                    if m:
                        title = html.unescape(re.sub(r"<[^>]+>", "", m.group(2))).strip()
                        if title:
                            out.append({"title": title, "url": m.group(1)})
                if out:
                    return out
            except Exception as e:
                logger.debug("bing %s failed: %s", base, e)
        return []

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
        """多源搜索，返回首个成功源的结果

        优先使用付费搜索源（Tavily/Bocha 等，中文命中率高且有 snippet，
        通过 get_search_service() 读取仓库已配置的 API Key）；
        未配置时降级到免费搜索源（DDG/必应/搜狗）。
        """
        paid = self._search_paid(query, max_results)
        if paid:
            return paid

        for name, fn in [
            ("duckduckgo", self._ddg),
            ("bing_rss", self._bing_rss),
            ("bing", self._bing),
            ("sogou", self._sogou),
        ]:
            try:
                results = fn(query, max_results)
                results = _clean_results(results)
                if results:
                    logger.debug("search %s via %s: %d 条", query, name, len(results))
                    return results
            except Exception as e:
                logger.debug("search %s via %s failed: %s", query, name, e)
        return []

    def _search_paid(self, query: str, max_results: int) -> list[dict]:
        """利用仓库 SearchService 的付费搜索源"""
        try:
            from src.search_service import get_search_service
            svc = get_search_service()
        except Exception as e:
            logger.debug("paid search init failed: %s", e)
            return []
        try:
            resp = svc.search(query, max_results=max_results, days=7)
            if not resp or not getattr(resp, "results", None):
                return []
            out = []
            for r in resp.results:
                title = getattr(r, "title", "") or ""
                out.append({
                    "title": title,
                    "url": getattr(r, "url", "") or "",
                    "snippet": getattr(r, "snippet", "") or "",
                })
            out = _clean_results(out)
            if out:
                logger.debug("search %s via paid(%s): %d 条",
                             query, getattr(resp, "provider", "?"), len(out))
            return out
        except Exception as e:
            logger.debug("paid search %s failed: %s", query, e)
            return []

    def _judge_text(self, text: str) -> float:
        """用 LLM 判断单条言论情绪 [-1,1]，理解"大跌敢买"这类反转表述

        LLM 不可用/超时/返回异常时回退到关键词打分 _score_text。
        """
        try:
            from src.agent.llm_adapter import LLMToolAdapter
            adapter = LLMToolAdapter()
            if not adapter.is_available:
                logger.debug("LLM 不可用，回退关键词打分")
                return _score_text(text)
            logger.info("LLM judge start, model=%s provider=%s",
                        adapter.primary_provider, getattr(adapter, "_generation_backend_id", "?"))

            prompt = (
                "你是A股市场情绪分析师。判断下面这位炒股大V的言论情绪立场。"
                "只输出一个浮点数：正数为看多(最多+1.0)，负数为看空(最少-1.0)，"
                "0为中性/无明确倾向。注意表达的反转：如'大跌但敢买'是看多，"
                '"大涨但建议清仓"是看空。\\n\\n'
                f"言论：{text[:800]}\\n\\n"
                "输出格式：仅一个数字，例如 0.6 或 -0.4"
            )
            resp = adapter.call_text(
                [{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=8,
                timeout=20,
            )
            content = (getattr(resp, "content", "") or "").strip()
            value = self._parse_llm_score(content)
            if value is not None:
                logger.info("LLM judge: %r -> %s", content[:60], value)
            else:
                logger.info("LLM judge 解析失败: %r, 回退关键词", content[:60])
        except Exception as e:
            logger.debug("LLM judge 失败 %s，回退关键词: %s", type(e).__name__, e)
            value = None

        if value is not None:
            return max(-1.0, min(1.0, value))
        return _score_text(text)

    @staticmethod
    def _parse_llm_score(content: str) -> float | None:
        """解析 LLM 输出的情绪分数，容忍多种格式"""
        if not content:
            return None
        s = content.strip()
        # 纯数字，如 0.6 / -0.4 / 1.0
        m = re.search(r"[-+]?\d+\.?\d*", s)
        if m:
            return float(m.group())
        # 文本立场
        text = s.lower()
        if "positive" in text or "看多" in text or "多头" in text:
            return 0.6
        if "negative" in text or "看空" in text or "空头" in text:
            return -0.6
        if "neutral" in text or "中性" in text:
            return 0.0
        return None

    def analyze_kol(self, kol: dict) -> dict:
        """分析单个大V情绪"""
        name = kol["name"]
        style = kol.get("style", "")
        all_results: list[dict] = []
        for term in kol.get("search_terms", [name]):
            for r in self.search(term):
                all_results.append(r)

        if not all_results:
            return {
                "name": name, "style": style, "score": 0.0, "stance": "neutral",
                "sources": 0, "snippets": [], "raw": [],
            }

        scores = []
        snippets = []
        for r in all_results:
            title = r["title"]
            snippet = r.get("snippet", "")
            text = f"{title} {snippet}".strip()
            s = self._judge_text(text)
            scores.append(s)
            snippets.append({"title": title, "url": r["url"], "score": round(s, 3)})

        avg = sum(scores) / len(scores)
        stance = _classify(avg)

        return {
            "name": name,
            "style": style,
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
                    results.append({"name": fut[f], "style": "", "score": 0.0, "stance": "neutral",
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

        # 反向指标检测: 大V观点与市场量化方向背离
        # 大V集体看空但市场偏热 / 大V集体看多但市场偏冷 → 可能是反向信号
        divergence = self._detect_divergence(market_temp, kol_score)

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
            "divergence": divergence,
        }

    def _detect_divergence(self, market_temp: float, kol_score: float) -> dict:
        """检测大V情绪与市场量化情绪的背离（反向指标信号）

        大V温度由 kol_score(-1~1) 映射: kol_temp=(kol_score+1)/2*100
        背离判定:
        - 大V明显看空 (kol_temp<=35) + 市场偏热 (market_temp>=60) → 大V逆势看空
        - 大V明显看多 (kol_temp>=65) + 市场偏冷 (market_temp<=40) → 大V逆势看多
        """
        kol_temp = (kol_score + 1) / 2 * 100
        base = {
            "market_temp": round(market_temp, 1),
            "kol_temp": round(kol_temp, 1),
        }

        if kol_temp <= 35 and market_temp >= 60:
            return {
                **base,
                "direction": "kol_bearish_market_hot",
                "label_cn": "⚠️ 大V集体看空，但市场偏热 → 警惕反向信号（大V逆势，可能是顶部预警）",
            }
        if kol_temp >= 65 and market_temp <= 40:
            return {
                **base,
                "direction": "kol_bullish_market_cold",
                "label_cn": "💡 大V集体看多，但市场偏冷 → 注意反向机会（大V逆势抄底）",
            }

        return {
            **base,
            "direction": "aligned",
            "label_cn": "大V观点与市场方向一致",
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

        # 反向指标背离提示
        divergence = result.get("divergence", {})
        if divergence.get("direction", "aligned") != "aligned":
            lines.append(f"\n**{divergence.get('label_cn', '')}**")

        # 大V情绪
        lines.append(f"\n**🎙️ 大V情绪: {kols.get('avg_score', 0):+.2f} ({kols.get('stance', 'neutral')})**")
        for kol in kols.get("kols", []):
            k_score = kol.get("score", 0)
            k_stance = kol.get("stance", "neutral")
            k_em = {"positive": "📈", "negative": "📉", "neutral": "⚪"}.get(k_stance, "⚪")
            k_style = kol.get("style", "")
            style_txt = f"({k_style})" if k_style else ""
            lines.append(f"- {k_em} **{kol['name']}**{style_txt}: {k_score:+.2f} ({k_stance})")
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

    def save_history(self, result: dict, data_dir: str = "data/sentiment") -> str | None:
        """将当日情绪结果持久化为 JSON，用于历史回溯

        写入 data/sentiment/<date>.json，返回写入的文件路径；失败返回 None。
        若同一天已存在文件则覆盖更新。
        """
        import json as _json
        date = result.get("date")
        if not date:
            date = datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")
        try:
            path = os.path.join(data_dir, f"{date}.json")
            os.makedirs(data_dir, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                _json.dump(result, f, ensure_ascii=False, indent=2, default=str)
            logger.info("情绪历史已保存: %s", path)
            return path
        except Exception as e:
            logger.warning("保存情绪历史失败: %s", e)
            return None
