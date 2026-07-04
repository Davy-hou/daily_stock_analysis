from __future__ import annotations

from datetime import datetime
from typing import Optional
import pandas as pd


SOURCE_MAP = {
    "akshare": {"time": "时间", "open": "开盘", "high": "最高",
                "low": "最低", "close": "收盘", "volume": "成交量"},
    "tickflow": {"time": "time", "open": "open", "high": "high",
                 "low": "low", "close": "close", "volume": "volume"},
    "standard": {"time": "time", "open": "open", "high": "high",
                 "low": "low", "close": "close", "volume": "volume"},
}


class MinuteDataLoader:
    def __init__(self, source: str = "standard"):
        if source not in SOURCE_MAP:
            raise ValueError(f"Unknown source: {source}")
        self.source = source

    def load(self, code: str, date: str, source: Optional[str] = None) -> pd.DataFrame:
        src = source or self.source
        if src == "akshare":
            return self._load_akshare(code, date)
        raise ValueError(f"Unsupported source for live loading: {src}")

    def _load_akshare(self, code: str, date: str) -> pd.DataFrame:
        raise NotImplementedError("AkShare minute data loading requires akshare package")

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
