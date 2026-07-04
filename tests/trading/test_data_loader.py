import pytest
from datetime import datetime
import pandas as pd
from data_provider.intraday import MinuteDataLoader


class TestMinuteDataLoader:
    def test_standardize_akshare_columns(self):
        loader = MinuteDataLoader(source="akshare")
        raw = pd.DataFrame({
            "时间": ["2026-07-01 09:31", "2026-07-01 09:32"],
            "开盘": [10.0, 10.01],
            "最高": [10.05, 10.03],
            "最低": [9.98, 9.99],
            "收盘": [10.02, 10.01],
            "成交量": [10000, 12000],
        })
        standard = loader.load_from_df(raw)
        assert "time" in standard.columns
        assert "open" in standard.columns
        assert "close" in standard.columns
        assert isinstance(standard["time"].iloc[0], datetime)
        assert standard["time"].iloc[0].hour == 9

    def test_empty_dataframe(self):
        loader = MinuteDataLoader(source="akshare")
        df = pd.DataFrame()
        result = loader.load_from_df(df)
        assert result.empty

    def test_unknown_source(self):
        with pytest.raises(ValueError, match="Unknown source"):
            MinuteDataLoader(source="invalid_source")

    def test_missing_columns_raises_error(self):
        loader = MinuteDataLoader(source="standard")
        df = pd.DataFrame({"time": ["2026-07-01 09:31"], "open": [10.0]})
        with pytest.raises(ValueError, match="Missing required column"):
            loader.load_from_df(df)

    def test_standard_source_no_rename(self):
        loader = MinuteDataLoader(source="standard")
        raw = pd.DataFrame({
            "time": [datetime(2026, 7, 1, 9, 31)],
            "open": [10.0],
            "high": [10.05],
            "low": [9.98],
            "close": [10.02],
            "volume": [10000],
        })
        result = loader.load_from_df(raw)
        assert len(result) == 1
        assert result["close"].iloc[0] == 10.02

    def test_tickflow_source(self):
        loader = MinuteDataLoader(source="tickflow")
        raw = pd.DataFrame({
            "time": [1700000000],
            "open": [10.0],
            "high": [10.05],
            "low": [9.98],
            "close": [10.02],
            "volume": [10000],
        })
        result = loader.load_from_df(raw)
        assert "time" in result.columns
        assert result["close"].iloc[0] == 10.02
