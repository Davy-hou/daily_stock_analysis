from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
import pandas as pd


logger = logging.getLogger(__name__)


SOURCE_MAP = {
    "akshare": {"time": "时间", "open": "开盘", "high": "最高",
                "low": "最低", "close": "收盘", "volume": "成交量"},
    "efinance": {"time": "日期", "open": "开盘", "high": "最高",
                 "low": "最低", "close": "收盘", "volume": "成交量"},
    "pytdx": {"time": "datetime", "open": "open", "high": "high",
              "low": "low", "close": "close", "volume": "vol"},
    "tickflow": {"time": "time", "open": "open", "high": "high",
                 "low": "low", "close": "close", "volume": "volume"},
    "standard": {"time": "time", "open": "open", "high": "high",
                 "low": "low", "close": "close", "volume": "volume"},
}


TDX_CATEGORY_MAP = {"1": 8, "5": 0, "15": 1, "30": 2, "60": 3}


def _tdx_market(code: str) -> int:
    return 1 if code[0] in ("5", "6") else 0


class MinuteDataLoader:
    def __init__(self, source: str = "standard"):
        if source not in SOURCE_MAP:
            raise ValueError(f"Unknown source: {source}")
        self.source = source

    def load(self, code: str, date: str, source: Optional[str] = None,
             period: str = "1") -> pd.DataFrame:
        src = source or self.source
        if src == "akshare":
            return self._load_with_fallback(code, date, period=period)
        if src == "efinance":
            return self._load_efinance(code, date, period=period)
        if src == "pytdx":
            return self._load_pytdx(code, date, period=period)
        raise ValueError(f"Unsupported source for live loading: {src}")

    def _load_with_fallback(self, code: str, date: str, period: str = "1") -> pd.DataFrame:
        for label, loader in [("akshare", self._load_akshare),
                              ("efinance", self._load_efinance),
                              ("pytdx", self._load_pytdx)]:
            try:
                df = loader(code, date, period=period)
                if df is not None and not df.empty:
                    return df
            except Exception as e:
                logger.warning("%s failed for %s on %s: %s", label, code, date, e)
        raise RuntimeError(
            f"All data sources failed for {code} on {date} "
            f"(tried akshare, efinance, pytdx)"
        )

    def _load_akshare(self, code: str, date: str, period: str = "1") -> pd.DataFrame:
        try:
            import akshare as ak
        except ImportError:
            raise ImportError(
                "akshare package is required for AkShare data loading. "
                "Install with: pip install akshare"
            )

        start = f"{date} 09:00:00"
        end = f"{date} 15:30:00"
        try:
            df = ak.fund_etf_hist_min_em(
                symbol=code, period=period,
                start_date=start, end_date=end,
            )
        except Exception as e:
            raise RuntimeError(f"AkShare minute data fetch failed for {code} on {date}: {e}")

        if df.empty:
            logger.warning("AkShare returned empty data for %s on %s", code, date)
            return pd.DataFrame()

        return self.load_from_df(df, source="akshare")

    def _load_efinance(self, code: str, date: str, period: str = "1") -> pd.DataFrame:
        try:
            import efinance as ef
        except ImportError:
            raise ImportError(
                "efinance package is required for efinance data loading. "
                "Install with: pip install efinance"
            )

        klt_map = {"1": 1, "5": 5, "15": 15, "30": 30, "60": 60}
        klt = klt_map.get(period, 1)
        beg = date
        end = date
        try:
            df = ef.stock.get_quote_history(code, beg=beg, end=end, klt=klt, fqt=1)
        except Exception as e:
            raise RuntimeError(f"efinance minute data fetch failed for {code} on {date}: {e}")

        if df.empty:
            logger.warning("efinance returned empty data for %s on %s", code, date)
            return pd.DataFrame()

        return self.load_from_df(df, source="efinance")

    def _load_pytdx(self, code: str, date: str, period: str = "1") -> pd.DataFrame:
        try:
            from pytdx.hq import TdxHq_API
        except ImportError:
            raise ImportError(
                "pytdx package is required for PyTDX data loading. "
                "Install with: pip install pytdx"
            )

        category = TDX_CATEGORY_MAP.get(period, 8)
        market = _tdx_market(code)
        servers = [
            ("60.191.117.167", 7709),
            ("119.147.212.81", 7709),
            ("47.94.80.90", 7709),
        ]

        api = TdxHq_API()
        try:
            for host, port in servers:
                try:
                    if api.connect(host, port, time_out=3):
                        break
                except Exception:
                    continue
            else:
                raise RuntimeError(f"PyTDX could not connect to any server")

            rows = []
            bars_per_day = 240
            for day_offset in range(30):
                chunk = api.get_security_bars(
                    category, market, code, day_offset * bars_per_day, bars_per_day
                )
                if not chunk:
                    break
                rows.extend(chunk)
            api.disconnect()
        except RuntimeError:
            api.disconnect()
            raise
        except Exception as e:
            api.disconnect()
            raise RuntimeError(f"PyTDX minute data fetch failed for {code} on {date}: {e}")

        if not rows:
            logger.warning("PyTDX returned no data for %s on %s", code, date)
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = self.load_from_df(df, source="pytdx")

        target = pd.to_datetime(date).date()
        mask = df["time"].dt.date == target
        matched = df[mask]
        if matched.empty:
            logger.warning("PyTDX found no bars matching date %s for %s", date, code)
            return pd.DataFrame()

        return matched.reset_index(drop=True)

    def load_from_df(self, df: pd.DataFrame, source: Optional[str] = None) -> pd.DataFrame:
        src = source or self.source
        if src not in SOURCE_MAP:
            raise ValueError(f"Unknown source: {src}")
        cols = SOURCE_MAP[src]
        return self._standardize(df.copy(deep=False), cols)

    def _standardize(self, df: pd.DataFrame, cols: dict[str, str]) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()

        rename = {v: k for k, v in cols.items() if v in df.columns}
        df = df.rename(columns=rename)

        if "time" in df.columns:
            if df["time"].dtype == "int64":
                df["time"] = pd.to_datetime(df["time"], unit="s")
            else:
                df["time"] = pd.to_datetime(df["time"])

        required = ["time", "open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        return df[required].sort_values("time").reset_index(drop=True)
