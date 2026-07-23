import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock
import pandas as pd
from data_provider.intraday import MinuteDataLoader


@pytest.fixture
def mock_all_fail():
    ak = MagicMock()
    ak.fund_etf_hist_min_em.side_effect = Exception("fail")
    ef = MagicMock()
    ef.stock.get_quote_history.side_effect = Exception("fail")
    return {"akshare": ak, "efinance": ef, "pytdx": None}


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

    # --- akshare source tests ---

    def test_load_akshare_success(self):
        loader = MinuteDataLoader(source="akshare")
        fake_df = pd.DataFrame({
            "时间": ["2026-07-03 09:31:00", "2026-07-03 09:32:00"],
            "开盘": [1.451, 1.452],
            "收盘": [1.452, 1.453],
            "最高": [1.453, 1.455],
            "最低": [1.450, 1.451],
            "成交量": [10000, 12000],
        })
        with patch.dict("sys.modules", {"akshare": MagicMock(fund_etf_hist_min_em=MagicMock(return_value=fake_df)), "efinance": None, "pytdx": None}):
            result = loader.load("513750", "2026-07-03")
        assert len(result) == 2
        assert list(result.columns) == ["time", "open", "high", "low", "close", "volume"]
        assert result["close"].iloc[0] == 1.452

    def test_load_akshare_empty_response(self):
        loader = MinuteDataLoader(source="akshare")
        with patch.dict("sys.modules", {"akshare": MagicMock(fund_etf_hist_min_em=MagicMock(return_value=pd.DataFrame())), "efinance": MagicMock(stock=MagicMock(get_quote_history=MagicMock(return_value=pd.DataFrame()))), "pytdx": None}):
            with pytest.raises(RuntimeError, match="All data sources failed"):
                loader.load("513750", "2026-07-04")

    def test_load_akshare_import_error(self):
        loader = MinuteDataLoader(source="akshare")
        with patch.dict("sys.modules", {"akshare": None, "efinance": None, "pytdx": None}):
            with pytest.raises(RuntimeError, match="All data sources failed"):
                loader.load("513750", "2026-07-03")

    def test_load_akshare_network_error(self):
        loader = MinuteDataLoader(source="akshare")
        mock_ak = MagicMock()
        mock_ak.fund_etf_hist_min_em.side_effect = Exception("timeout")
        with patch.dict("sys.modules", {"akshare": mock_ak, "efinance": None, "pytdx": None}):
            with pytest.raises(RuntimeError, match="All data sources failed"):
                loader.load("513750", "2026-07-03")

    def test_load_akshare_custom_period(self):
        loader = MinuteDataLoader(source="akshare")
        fake_df = pd.DataFrame({
            "时间": ["2026-07-03 09:31:00"],
            "开盘": [1.451],
            "收盘": [1.452],
            "最高": [1.453],
            "最低": [1.450],
            "成交量": [10000],
        })
        mock_ak = MagicMock()
        mock_ak.fund_etf_hist_min_em.return_value = fake_df
        with patch.dict("sys.modules", {"akshare": mock_ak, "efinance": None, "pytdx": None}):
            loader.load("513750", "2026-07-03", period="5")
        mock_ak.fund_etf_hist_min_em.assert_called_once_with(
            symbol="513750", period="5",
            start_date="2026-07-03 09:00:00", end_date="2026-07-03 15:30:00",
        )

    # --- efinance source tests ---

    def test_load_efinance_success(self):
        loader = MinuteDataLoader(source="efinance")
        fake_df = pd.DataFrame({
            "日期": ["2026-07-03 09:31", "2026-07-03 09:32"],
            "开盘": [1.451, 1.452],
            "收盘": [1.452, 1.453],
            "最高": [1.453, 1.455],
            "最低": [1.450, 1.451],
            "成交量": [10000, 12000],
        })
        with patch.dict("sys.modules", {"efinance": MagicMock(stock=MagicMock(get_quote_history=MagicMock(return_value=fake_df)))}):
            result = loader.load("513750", "2026-07-03", source="efinance")
        assert len(result) == 2
        assert list(result.columns) == ["time", "open", "high", "low", "close", "volume"]
        assert result["close"].iloc[0] == 1.452

    def test_load_efinance_empty_response(self):
        loader = MinuteDataLoader(source="efinance")
        with patch.dict("sys.modules", {"efinance": MagicMock(stock=MagicMock(get_quote_history=MagicMock(return_value=pd.DataFrame())))}):
            result = loader.load("513750", "2026-07-04", source="efinance")
        assert result.empty

    def test_load_efinance_import_error(self):
        loader = MinuteDataLoader(source="efinance")
        with patch.dict("sys.modules", {"efinance": None}):
            with pytest.raises(ImportError, match="efinance package is required"):
                loader.load("513750", "2026-07-03", source="efinance")

    def test_load_efinance_network_error(self):
        loader = MinuteDataLoader(source="efinance")
        mock_ef = MagicMock()
        mock_ef.stock.get_quote_history.side_effect = Exception("Connection refused")
        with patch.dict("sys.modules", {"efinance": mock_ef}):
            with pytest.raises(RuntimeError, match="efinance minute data fetch failed"):
                loader.load("513750", "2026-07-03", source="efinance")

    # --- pytdx source tests ---

    def test_standardize_pytdx_columns(self):
        loader = MinuteDataLoader(source="pytdx")
        raw = pd.DataFrame({
            "datetime": ["2026-07-03 09:31"],
            "open": [1.451],
            "high": [1.453],
            "low": [1.448],
            "close": [1.451],
            "vol": [7700200],
        })
        result = loader.load_from_df(raw)
        assert list(result.columns) == ["time", "open", "high", "low", "close", "volume"]
        assert isinstance(result["time"].iloc[0], datetime)

    def test_load_pytdx_success(self):
        loader = MinuteDataLoader(source="pytdx")
        fake_rows = [
            {"datetime": "2026-07-03 09:31", "open": 1.451, "high": 1.453,
             "low": 1.448, "close": 1.451, "vol": 7700200, "amount": 0},
        ]
        with patch("pytdx.hq.TdxHq_API") as mock_api_cls:
            mock_api = MagicMock()
            mock_api.connect.return_value = True
            mock_api.get_security_bars.side_effect = \
                lambda *a, **kw: fake_rows
            mock_api_cls.return_value = mock_api
            result = loader.load("513750", "2026-07-03", source="pytdx")
        assert list(result.columns) == ["time", "open", "high", "low", "close", "volume"]
        assert result["close"].iloc[0] == 1.451

    def test_load_pytdx_empty(self):
        loader = MinuteDataLoader(source="pytdx")
        with patch("pytdx.hq.TdxHq_API") as mock_api_cls:
            mock_api = MagicMock()
            mock_api.connect.return_value = True
            mock_api.get_security_bars.return_value = []
            mock_api_cls.return_value = mock_api
            result = loader.load("513750", "2026-07-03", source="pytdx")
        assert result.empty

    def test_load_pytdx_connect_fail(self):
        loader = MinuteDataLoader(source="pytdx")
        with patch("pytdx.hq.TdxHq_API") as mock_api_cls:
            mock_api = MagicMock()
            mock_api.connect.return_value = False
            mock_api_cls.return_value = mock_api
            with pytest.raises(RuntimeError, match="PyTDX could not connect"):
                loader.load("513750", "2026-07-03", source="pytdx")

    def test_tdx_market_sh(self):
        from data_provider.intraday import _tdx_market
        assert _tdx_market("513750") == 1
        assert _tdx_market("600519") == 1
        assert _tdx_market("159920") == 0
        assert _tdx_market("000001") == 0

    # --- fallback chain tests ---

    def test_fallback_akshare_fails_efinance_succeeds(self):
        loader = MinuteDataLoader(source="akshare")
        ef_df = pd.DataFrame({
            "日期": ["2026-07-03 09:31"],
            "开盘": [1.451],
            "收盘": [1.452],
            "最高": [1.453],
            "最低": [1.450],
            "成交量": [10000],
        })
        mock_ak = MagicMock()
        mock_ak.fund_etf_hist_min_em.side_effect = Exception("timeout")
        mock_ef = MagicMock()
        mock_ef.stock.get_quote_history.return_value = ef_df
        with patch.dict("sys.modules", {"akshare": mock_ak, "efinance": mock_ef, "pytdx": None}):
            result = loader.load("513750", "2026-07-03")
        assert len(result) == 1
        assert result["close"].iloc[0] == 1.452

    def test_fallback_akshare_empty_efinance_succeeds(self):
        loader = MinuteDataLoader(source="akshare")
        ef_df = pd.DataFrame({
            "日期": ["2026-07-03 09:31"],
            "开盘": [1.451],
            "收盘": [1.452],
            "最高": [1.453],
            "最低": [1.450],
            "成交量": [10000],
        })
        mock_ak = MagicMock()
        mock_ak.fund_etf_hist_min_em.return_value = pd.DataFrame()
        mock_ef = MagicMock()
        mock_ef.stock.get_quote_history.return_value = ef_df
        with patch.dict("sys.modules", {"akshare": mock_ak, "efinance": mock_ef, "pytdx": None}):
            result = loader.load("513750", "2026-07-03")
        assert len(result) == 1

    def test_fallback_all_fail_raises_error(self):
        loader = MinuteDataLoader(source="akshare")
        with patch.dict("sys.modules", {"akshare": None, "efinance": None,
                                        "pytdx": None, "pytdx.hq": None}):
            with pytest.raises(RuntimeError, match="All data sources failed"):
                loader.load("513750", "2026-07-03")

    def test_standardize_efinance_columns(self):
        loader = MinuteDataLoader(source="efinance")
        raw = pd.DataFrame({
            "日期": ["2026-07-01 09:31"],
            "开盘": [10.0],
            "最高": [10.05],
            "最低": [9.98],
            "收盘": [10.02],
            "成交量": [10000],
        })
        result = loader.load_from_df(raw)
        assert "time" in result.columns
        assert isinstance(result["time"].iloc[0], datetime)
