# 日内量化交易系统 MVP 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现日内回测系统 MVP，支持分钟线回测、Momentum 策略、T+0 多轮交易和绩效统计。

**Architecture:** 在 DSA 项目 `src/trading/` 下新建日内交易模块，与现有分析流程平行。`data_provider/intraday.py` 统一分钟线数据接入，`engine.py` 提供回测引擎，`strategies/` 实现策略，`reporter.py` 输出绩效。

**Tech Stack:** Python 3.10+, pandas, pytest, numpy

---

### Task 1: 核心数据结构（Bar, Signal, Order, Trade, Metrics）

**Files:**
- Create: `src/trading/__init__.py`
- Create: `src/trading/config.py`
- Create: `tests/trading/__init__.py`
- Test: `tests/trading/test_config.py`

**核心数据结构定义：**

Bar: 分钟线（时间、开高低收、成交量）
Signal: 策略信号（动作、方向、价格、置信度、时间）
Order: 订单（方向、类型、价格、数量、状态）
Trade: 成交记录（入场/出场时间、价格、盈亏）
Metrics: 绩效统计（夏普、最大回撤、胜率等）

**Step 1: 创建目录结构和 `__init__.py`**

```bash
mkdir -p src/trading/strategies
mkdir -p tests/trading
```

**Step 2: 写测试 (`tests/trading/test_config.py`)**

```python
import pytest
from datetime import datetime, date
from decimal import Decimal
from src.trading.config import Bar, Signal, Order, Trade, Metrics, Side, OrderType, OrderStatus


class TestBar:
    def test_create(self):
        bar = Bar(
            time=datetime(2026, 7, 1, 9, 31),
            open=10.0, high=10.1, low=9.95, close=10.05,
            volume=10000
        )
        assert bar.time == datetime(2026, 7, 1, 9, 31)
        assert bar.close == 10.05

class TestSignal:
    def test_buy_signal(self):
        sig = Signal(code="513100.XSHG", side=Side.BUY, price=1.5, confidence=0.8, time=datetime(2026, 7, 1, 10, 0))
        assert sig.side == Side.BUY
        assert sig.code == "513100.XSHG"

class TestTrade:
    def test_profit(self):
        trade = Trade(
            code="513100.XSHG",
            buy_time=datetime(2026, 7, 1, 10, 0),
            buy_price=1.5,
            sell_time=datetime(2026, 7, 1, 14, 0),
            sell_price=1.52,
            volume=1000,
            fee=2.0
        )
        assert trade.profit == pytest.approx(18.0)


class TestMetrics:
    def test_empty(self):
        m = Metrics(trades=[])
        assert m.total_trades == 0
        assert m.win_rate is None

    def test_with_trades(self):
        trades = [
            Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
                  sell_time=datetime(2026,7,1,14,0), sell_price=11.0,
                  volume=100, fee=1.0),
            Trade(code="A", buy_time=datetime(2026,7,1,10,30), buy_price=10.0,
                  sell_time=datetime(2026,7,1,14,30), sell_price=9.0,
                  volume=100, fee=1.0),
        ]
        m = Metrics(trades=trades)
        assert m.total_trades == 2
        assert m.win_rate == 50.0
```

**Step 3: 写实现 (`src/trading/config.py`)**

```python
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional
import numpy as np


class Side(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"


@dataclass
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    code: str
    side: Side
    price: float
    confidence: float
    time: datetime
    reason: str = ""


@dataclass
class Order:
    code: str
    side: Side
    price: float
    volume: int
    status: OrderStatus = OrderStatus.PENDING
    type: OrderType = OrderType.MARKET
    filled_time: Optional[datetime] = None
    filled_price: Optional[float] = None


@dataclass
class Trade:
    code: str
    buy_time: datetime
    buy_price: float
    sell_time: datetime
    sell_price: float
    volume: int
    fee: float

    @property
    def profit(self) -> float:
        return (self.sell_price - self.buy_price) * self.volume - self.fee

    @property
    def return_pct(self) -> float:
        return (self.sell_price - self.buy_price) / self.buy_price * 100

    @property
    def duration_minutes(self) -> float:
        return (self.sell_time - self.buy_time).total_seconds() / 60.0


@dataclass
class Metrics:
    trades: list[Trade]

    @property
    def total_trades(self) -> int:
        return len(self.trades)

    @property
    def win_trades(self) -> int:
        return sum(1 for t in self.trades if t.profit > 0)

    @property
    def loss_trades(self) -> int:
        return sum(1 for t in self.trades if t.profit <= 0)

    @property
    def win_rate(self) -> Optional[float]:
        if self.total_trades == 0:
            return None
        return self.win_trades / self.total_trades * 100

    @property
    def total_profit(self) -> float:
        return sum(t.profit for t in self.trades)

    @property
    def profit_factor(self) -> Optional[float]:
        gross_profit = sum(t.profit for t in self.trades if t.profit > 0)
        gross_loss = abs(sum(t.profit for t in self.trades if t.profit < 0))
        if gross_loss == 0:
            return float("inf") if gross_profit > 0 else None
        return gross_profit / gross_loss

    @property
    def sharpe_ratio(self) -> Optional[float]:
        if self.total_trades < 2:
            return None
        returns = [(t.sell_price - t.buy_price) / t.buy_price for t in self.trades]
        if len(returns) < 2 or np.std(returns) == 0:
            return None
        return float(np.mean(returns) / np.std(returns) * np.sqrt(240))

    @property
    def max_drawdown_pct(self) -> Optional[float]:
        if self.total_trades == 0:
            return None
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative += t.profit
            peak = max(peak, cumulative)
            dd = (peak - cumulative) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)
        return max_dd * 100
```

**Step 4: 运行测试确认通过**

```bash
pip install pytest numpy
python -m pytest tests/trading/test_config.py -v
```

**Step 5: 提交**

```bash
git add src/trading/ tests/trading/
git commit -m "feat: add core data structures for intraday trading module"
```

---

### Task 2: Strategy 基类

**Files:**
- Create: `src/trading/strategies/__init__.py`
- Create: `src/trading/strategies/base.py`
- Test: `tests/trading/test_strategy_base.py`

**Step 1: 写测试**

```python
import pytest
from datetime import datetime
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.base import Strategy


class DummyStrategy(Strategy):
    def __init__(self):
        super().__init__(name="dummy", params={"threshold": 0.01})

    def on_bar(self, bar: Bar, state: dict) -> Signal | None:
        if bar.close > 10.0:
            return Signal(code="TEST", side=Side.BUY, price=bar.close,
                          confidence=0.6, time=bar.time, reason="above 10")
        return None


class TestStrategy:
    def test_base_instantiation(self):
        with pytest.raises(TypeError):
            Strategy()

    def test_dummy_strategy(self):
        s = DummyStrategy()
        assert s.name == "dummy"
        assert s.params == {"threshold": 0.01}

    def test_on_bar_return_signal(self):
        s = DummyStrategy()
        bar = Bar(time=datetime(2026, 7, 1, 10, 0), open=10.0, high=10.2, low=9.9, close=10.05, volume=1000)
        sig = s.on_bar(bar, {})
        assert sig is not None
        assert sig.side == Side.BUY

    def test_on_bar_no_signal(self):
        s = DummyStrategy()
        bar = Bar(time=datetime(2026, 7, 1, 10, 0), open=9.5, high=9.6, low=9.4, close=9.55, volume=1000)
        sig = s.on_bar(bar, {})
        assert sig is None
```

**Step 2: 写实现**

```python
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional

from src.trading.config import Bar, Signal


class Strategy(ABC):
    def __init__(self, name: str, params: dict[str, Any] | None = None):
        self._name = name
        self._params = params or {}

    @property
    def name(self) -> str:
        return self._name

    @property
    def params(self) -> dict[str, Any]:
        return self._params

    @abstractmethod
    def on_bar(self, bar: Bar, state: dict) -> Optional[Signal]:
        ...

    def on_tick(self, tick) -> Optional[Signal]:
        return None

    def reset(self) -> None:
        pass
```

**Step 3: 运行测试**

```bash
python -m pytest tests/trading/test_strategy_base.py -v
```

**Step 4: 提交**

```bash
git add src/trading/strategies/ tests/trading/test_strategy_base.py
git commit -m "feat: add strategy base class"
```

---

### Task 3: 回测引擎核心

**Files:**
- Create: `src/trading/engine.py`
- Test: `tests/trading/test_engine.py`

引擎职责：
1. 接收分钟线 DataFrame、Strategy、风控参数
2. 逐根 K 线驱动策略
3. 维护仓位、现金、已实现盈亏
4. T+0 多轮：每笔买入后必须等待卖出信号，每笔 round-trip 是一条 Trade
5. 记录所有 Trades 和权益曲线

**Step 1: 写测试**

```python
import pytest
from datetime import datetime, timedelta
import pandas as pd
from src.trading.config import Bar, Signal, Side, Trade, Metrics
from src.trading.engine import IntradayEngine
from src.trading.strategies.base import Strategy


def make_minute_bars(count: int, start_price: float = 10.0) -> pd.DataFrame:
    """生成模拟分钟线数据"""
    rows = []
    dt = datetime(2026, 7, 1, 9, 31)
    price = start_price
    for i in range(count):
        rows.append({
            "time": dt,
            "open": price,
            "high": price * 1.001,
            "low": price * 0.999,
            "close": price,
            "volume": 10000,
        })
        price += 0.01  # 稳定上涨
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


class BuyEveryBar(Strategy):
    """测试用策略：每根 K 线都买入"""
    def __init__(self):
        super().__init__(name="buy_every_bar")

    def on_bar(self, bar: Bar, state: dict) -> Signal | None:
        return Signal(code="TEST", side=Side.BUY, price=bar.close,
                      confidence=0.5, time=bar.time, reason="test")


class AlternateStrategy(Strategy):
    """测试用策略：奇偶切换 BUY/SELL"""
    def __init__(self):
        super().__init__(name="alternate", params={"count": 0})

    def on_bar(self, bar: Bar, state: dict) -> Signal | None:
        self._params["count"] += 1
        if self._params["count"] % 2 == 1:
            return Signal(code="TEST", side=Side.BUY, price=bar.close,
                          confidence=0.5, time=bar.time, reason="buy")
        return Signal(code="TEST", side=Side.SELL, price=bar.close,
                      confidence=0.5, time=bar.time, reason="sell")


class TestIntradayEngine:
    def test_empty_data(self):
        engine = IntradayEngine(fee_rate=0.0)
        df = pd.DataFrame(columns=["time", "open", "high", "low", "close", "volume"])
        result = engine.run(df, BuyEveryBar())
        assert len(result.trades) == 0

    def test_no_signal(self):
        class NoOp(Strategy):
            def __init__(self):
                super().__init__(name="noop")
            def on_bar(self, bar, state):
                return None

        engine = IntradayEngine(fee_rate=0.0)
        df = make_minute_bars(10)
        result = engine.run(df, NoOp())
        assert len(result.trades) == 0
        assert len(result.equity_curve) == 1  # 初始权益

    def test_buy_no_sell_no_trade(self):
        """只有买入没有卖出，不构成完整 round-trip"""
        engine = IntradayEngine(fee_rate=0.0)
        df = make_minute_bars(10)
        result = engine.run(df, BuyEveryBar())
        # 只有买单没有卖单，不产生 trade
        assert len(result.trades) == 0

    def test_alternate_produces_trades(self):
        engine = IntradayEngine(fee_rate=0.0)
        df = make_minute_bars(20, start_price=10.0)
        result = engine.run(df, AlternateStrategy())
        # 10 对 round-trips
        assert len(result.trades) == 10
        assert all(t.profit > 0 for t in result.trades)  # 稳定上涨

    def test_fee_deducted(self):
        engine = IntradayEngine(fee_rate=0.001)
        df = make_minute_bars(20, start_price=10.0)
        result_no_fee = IntradayEngine(fee_rate=0.0).run(df, AlternateStrategy())
        result_with_fee = engine.run(df, AlternateStrategy())
        assert result_with_fee.metrics.total_profit < result_no_fee.metrics.total_profit
```

**Step 2: 编写回测引擎**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np

from src.trading.config import (
    Bar, Signal, Side, Order, OrderType, OrderStatus,
    Trade, Metrics,
)
from src.trading.strategies.base import Strategy


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity_curve: list[float]
    metrics: Metrics


class IntradayEngine:
    def __init__(self, fee_rate: float = 0.0001, slippage: float = 0.0001):
        self.fee_rate = fee_rate
        self.slippage = slippage

    def run(self, df: pd.DataFrame, strategy: Strategy, initial_cash: float = 100000) -> BacktestResult:
        strategy.reset()
        trades: list[Trade] = []
        position: Optional[dict] = None  # {buy_price, buy_time, volume}
        cash = initial_cash
        equity_curve = [initial_cash]

        for _, row in df.iterrows():
            bar = Bar(
                time=row["time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            )

            state = {"position": position, "cash": cash, "bar": bar}
            signal = strategy.on_bar(bar, state)
            if signal is None:
                equity_curve.append(self._current_equity(cash, position, bar.close))
                continue

            if signal.side == Side.BUY and position is None:
                volume = int(cash * 0.95 / bar.close / 100) * 100
                if volume < 100:
                    equity_curve.append(self._current_equity(cash, position, bar.close))
                    continue
                fill_price = bar.close * (1 + self.slippage)
                fee = fill_price * volume * self.fee_rate
                cash -= fill_price * volume + fee
                position = {"buy_price": fill_price, "buy_time": bar.time, "volume": volume}

            elif signal.side == Side.SELL and position is not None:
                fill_price = bar.close * (1 - self.slippage)
                volume = position["volume"]
                fee = fill_price * volume * self.fee_rate
                cash += fill_price * volume - fee

                trade = Trade(
                    code=signal.code,
                    buy_time=position["buy_time"],
                    buy_price=position["buy_price"],
                    sell_time=bar.time,
                    sell_price=fill_price,
                    volume=volume,
                    fee=fee + position["buy_price"] * volume * self.fee_rate,
                )
                trades.append(trade)
                position = None

            equity_curve.append(self._current_equity(cash, position, bar.close))

        return BacktestResult(
            trades=trades,
            equity_curve=equity_curve,
            metrics=Metrics(trades=trades),
        )

    def _current_equity(self, cash: float, position: Optional[dict], current_price: float) -> float:
        if position is None:
            return cash
        return cash + position["volume"] * current_price
```

**Step 3: 运行测试**

```bash
python -m pytest tests/trading/test_engine.py -v
```

**Step 4: 提交**

```bash
git add src/trading/engine.py tests/trading/test_engine.py
git commit -m "feat: add intraday backtest engine with T+0 multi-round support"
```

---

### Task 4: 绩效报告器

**Files:**
- Create: `src/trading/reporter.py`
- Test: `tests/trading/test_reporter.py`

**Step 1: 写测试**

```python
import pytest
from datetime import datetime
from src.trading.config import Trade, Metrics
from src.trading.reporter import generate_report


def test_generate_report_empty():
    report = generate_report([])
    assert report["total_trades"] == 0

def test_generate_report_with_trades():
    trades = [
        Trade(code="A", buy_time=datetime(2026,7,1,10,0), buy_price=10.0,
              sell_time=datetime(2026,7,1,10,30), sell_price=10.5,
              volume=1000, fee=3.0),
        Trade(code="A", buy_time=datetime(2026,7,1,11,0), buy_price=10.0,
              sell_time=datetime(2026,7,1,11,20), sell_price=9.8,
              volume=1000, fee=3.0),
    ]
    report = generate_report(trades)
    assert report["total_trades"] == 2
    assert report["win_rate"] == 50.0
    assert report["total_profit"] == pytest.approx(494.0)
    assert "avg_hold_minutes" in report
    assert "per_trade" in report
```

**Step 2: 写实现**

```python
from __future__ import annotations

from typing import Any
from src.trading.config import Trade, Metrics


def generate_report(trades: list[Trade]) -> dict[str, Any]:
    metrics = Metrics(trades=trades)
    report = {
        "total_trades": metrics.total_trades,
        "win_trades": metrics.win_trades,
        "loss_trades": metrics.loss_trades,
        "win_rate": metrics.win_rate,
        "total_profit": metrics.total_profit,
        "profit_factor": metrics.profit_factor,
        "sharpe_ratio": metrics.sharpe_ratio,
        "max_drawdown_pct": metrics.max_drawdown_pct,
    }
    if trades:
        durations = [t.duration_minutes for t in trades]
        report["avg_hold_minutes"] = sum(durations) / len(durations)
        report["max_hold_minutes"] = max(durations)
        report["min_hold_minutes"] = min(durations)
        report["per_trade"] = [
            {
                "code": t.code,
                "buy_time": t.buy_time.isoformat(),
                "sell_time": t.sell_time.isoformat(),
                "buy_price": round(t.buy_price, 4),
                "sell_price": round(t.sell_price, 4),
                "volume": t.volume,
                "profit": round(t.profit, 2),
                "return_pct": round(t.return_pct, 4),
                "hold_minutes": round(t.duration_minutes, 1),
            }
            for t in trades
        ]
    return report
```

**Step 3: 运行测试**

```bash
python -m pytest tests/trading/test_reporter.py -v
```

**Step 4: 提交**

```bash
git add src/trading/reporter.py tests/trading/test_reporter.py
git commit -m "feat: add performance reporter"
```

---

### Task 5: 数据加载器（分钟线）

**Files:**
- Create: `data_provider/intraday.py`
- Test: `tests/trading/test_data_loader.py`

**Step 1: 写测试（模拟数据）**

```python
import pytest
from datetime import datetime
import pandas as pd
from data_provider.intraday import MinuteDataLoader


class TestMinuteDataLoader:
    def test_standardize_columns(self):
        loader = MinuteDataLoader(source="akshare")
        raw = pd.DataFrame({
            "时间": ["2026-07-01 09:31", "2026-07-01 09:32"],
            "开盘": [10.0, 10.01],
            "最高": [10.05, 10.03],
            "最低": [9.98, 9.99],
            "收盘": [10.02, 10.01],
            "成交量": [10000, 12000],
        })
        standard = loader._standardize(raw)
        assert "time" in standard.columns
        assert "open" in standard.columns
        assert "close" in standard.columns
        assert isinstance(standard["time"].iloc[0], datetime)
        assert standard["time"].iloc[0].hour == 9

    def test_empty_dataframe(self):
        loader = MinuteDataLoader(source="akshare")
        df = pd.DataFrame()
        result = loader._standardize(df)
        assert result.empty
```

**Step 2: 写实现**

```python
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
        self.source = source

    def load(self, code: str, date: str, source: Optional[str] = None) -> pd.DataFrame:
        src = source or self.source
        if src == "akshare":
            return self._load_akshare(code, date)
        raise ValueError(f"Unsupported source: {src}")

    def _load_akshare(self, code: str, date: str) -> pd.DataFrame:
        raise NotImplementedError("AkShare minute data loading - requires akshare package")

    def load_from_df(self, df: pd.DataFrame, source: Optional[str] = None) -> pd.DataFrame:
        src = source or self.source
        cols = SOURCE_MAP.get(src, SOURCE_MAP["standard"])
        return self._standardize(df, cols)

    def _standardize(self, df: pd.DataFrame, cols: Optional[dict] = None) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()

        cols = cols or SOURCE_MAP.get(self.source, SOURCE_MAP["standard"])
        rename = {v: k for k, v in cols.items() if v in df.columns}
        df = df.rename(columns=rename)

        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"])

        required = ["time", "open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        return df[required].sort_values("time").reset_index(drop=True)
```

**Step 3: 运行测试**

```bash
python -m pytest tests/trading/test_data_loader.py -v
```

**Step 4: 提交**

```bash
git add data_provider/intraday.py tests/trading/test_data_loader.py
git commit -m "feat: add minute data loader with standardization"
```

---

### Task 6: Momentum 策略实现

**Files:**
- Create: `src/trading/strategies/momentum.py`
- Test: `tests/trading/test_momentum.py`

逻辑：计算最近 N 根 K 线的最高价和最低价，收盘突破前 N 根高点做多，跌破前 N 根低点做空（底仓）。

**Step 1: 写测试**

```python
import pytest
from datetime import datetime, timedelta
import pandas as pd
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.momentum import MomentumStrategy
from src.trading.engine import IntradayEngine


def make_trend_data(
    count: int,
    start_price: float = 10.0,
    uptrend: bool = True,
    breakout_at: int = 10,
) -> pd.DataFrame:
    rows = []
    dt = datetime(2026, 7, 1, 9, 31)
    price = start_price
    for i in range(count):
        direction = 1 if uptrend else -1
        if i >= breakout_at:
            price += direction * 0.05  # 突破
        rows.append({
            "time": dt,
            "open": price,
            "high": price * 1.002,
            "low": price * 0.998,
            "close": price + direction * 0.02,
            "volume": 10000,
        })
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


class TestMomentumStrategy:
    def test_breakout_up(self):
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        data = make_trend_data(20, start_price=10.0, uptrend=True, breakout_at=12)
        engine = IntradayEngine(fee_rate=0.0)
        result = engine.run(data, strategy)
        assert len(result.trades) > 0
        assert all(t.profit > 0 for t in result.trades)

    def test_no_breakout_no_trade(self):
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 1.0})
        data = make_trend_data(20, start_price=10.0, uptrend=True, breakout_at=12)
        engine = IntradayEngine(fee_rate=0.0)
        result = engine.run(data, strategy)
        assert len(result.trades) == 0

    def test_params_validation(self):
        with pytest.raises(ValueError):
            MomentumStrategy(params={"lookback": 0})
```

**Step 2: 写实现**

```python
from __future__ import annotations

from collections import deque
from typing import Any, Optional
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.base import Strategy


class MomentumStrategy(Strategy):
    def __init__(self, params: dict[str, Any] | None = None):
        p = params or {}
        lookback = p.get("lookback", 5)
        if lookback < 2:
            raise ValueError("lookback must be >= 2")
        super().__init__(name="momentum", params={**p, "lookback": lookback})
        self._highs: deque[float] = deque(maxlen=lookback)
        self._lows: deque[float] = deque(maxlen=lookback)
        self._in_position = False

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._in_position = False

    def on_bar(self, bar: Bar, state: dict) -> Optional[Signal]:
        self._highs.append(bar.high)
        self._lows.append(bar.low)

        if len(self._highs) < self._params["lookback"]:
            return None

        highest = max(self._highs)
        lowest = min(self._lows)
        threshold = self._params.get("threshold_pct", 0.1) / 100.0
        code = state.get("code", "UNKNOWN")

        if not self._in_position and bar.close > highest:
            self._in_position = True
            return Signal(
                code=code, side=Side.BUY,
                price=bar.close, confidence=0.7,
                time=bar.time,
                reason=f"breakout above {self._params['lookback']}-bar high {highest:.4f}",
            )

        if self._in_position and bar.close < lowest:
            self._in_position = False
            return Signal(
                code=code, side=Side.SELL,
                price=bar.close, confidence=0.7,
                time=bar.time,
                reason=f"breakdown below {self._params['lookback']}-bar low {lowest:.4f}",
            )

        return None
```

**Step 3: 运行测试**

```bash
python -m pytest tests/trading/test_momentum.py -v
```

**Step 4: 提交**

```bash
git add src/trading/strategies/momentum.py tests/trading/test_momentum.py
git commit -m "feat: add momentum breakout strategy"
```

---

### Task 7: 端到端集成测试（回测一条完整的 ETF 分钟线数据）

**Files:**
- Test: `tests/trading/test_integration.py`

**Step 1: 写集成测试**

```python
import pytest
from datetime import datetime, timedelta
import pandas as pd
from src.trading.engine import IntradayEngine
from src.trading.strategies.momentum import MomentumStrategy
from src.trading.reporter import generate_report


def simulate_etf_day() -> pd.DataFrame:
    """模拟纳指ETF（513100）一个交易日的分钟线数据（震荡上行）"""
    rows = []
    dt = datetime(2026, 7, 1, 9, 30)
    price = 1.500
    for i in range(240):  # 240 minutes
        change = 0.0
        if 30 <= i < 60:
            change = 0.002  # 小幅拉升
        elif 90 <= i < 120:
            change = 0.003  # 主升
        elif 150 <= i < 180:
            change = -0.001  # 回调
        elif 210 <= i < 240:
            change = 0.001  # 尾盘回升
        price += change
        rows.append({
            "time": dt,
            "open": round(price, 4),
            "high": round(price * 1.001, 4),
            "low": round(price * 0.999, 4),
            "close": round(price, 4),
            "volume": 50000 + int(i * 100),
        })
        dt += timedelta(minutes=1)
    return pd.DataFrame(rows)


class TestIntegration:
    def test_full_backtest_run(self):
        data = simulate_etf_day()
        strategy = MomentumStrategy(params={"lookback": 5, "threshold_pct": 0.05})
        engine = IntradayEngine(fee_rate=0.0001, slippage=0.0001)
        result = engine.run(data, strategy)

        assert result.metrics.total_trades >= 0
        assert len(result.equity_curve) == len(data) + 1  # initial + per bar
        assert result.equity_curve[0] == 100000  # initial_cash

        report = generate_report(result.trades)
        assert report["total_trades"] == result.metrics.total_trades

    def test_equal_weight_strategy_comparison(self):
        """测试完一个完整的回测流程，确保所有组件协同工作"""
        data = simulate_etf_day()
        params_list = [
            {"lookback": 3, "threshold_pct": 0.03},
            {"lookback": 5, "threshold_pct": 0.05},
            {"lookback": 10, "threshold_pct": 0.1},
        ]
        results = []
        for params in params_list:
            strategy = MomentumStrategy(params=params)
            engine = IntradayEngine(fee_rate=0.0001)
            result = engine.run(data, strategy)
            results.append((params, result.metrics))

        # 所有参数组合都应该能跑完
        assert len(results) == 3
```

**Step 2: 运行测试**

```bash
python -m pytest tests/trading/test_integration.py -v
```

**Step 3: 提交**

```bash
git add tests/trading/test_integration.py
git commit -m "test: add integration test for full backtest pipeline"
```

---

## 验证

```bash
python -m pytest tests/trading/ -v
```

期望输出：所有测试通过。

---

## V2 计划（MVP 完成后）

- **Mean Reversion 策略**：ETF 溢价/折价回归
- **Grid 策略**：网格交易
- **风控模块**：`risk_manager.py`（单笔止损、日亏损上限、最大持仓数量）
- **模拟交易运行时**：`simulator.py` 接入实时行情推送

## V3 计划

- **实时行情订阅**：`data/realtime.py`（TickFlow WebSocket / 轮询）
- **通知推送**：通过现有 WeChat/Telegram 推送信号和复盘
- **Web UI**：回测结果可视化（权益曲线、逐笔交易列表）
