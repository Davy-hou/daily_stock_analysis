from __future__ import annotations

from collections import deque
from typing import Any, Optional
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.base import Strategy


class TDSequentialStrategy(Strategy):
    def __init__(self, params: dict[str, Any] | None = None):
        p = params or {}
        period = p.get("period", 4)
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        super().__init__(name="td_sequential", params={**p, "period": period})
        self._period = period
        self._closes: deque[float] = deque(maxlen=period + 1)
        self._buy_count = 0
        self._sell_count = 0
        self._in_position = False
        self._pending_buy = False
        self._pending_sell = False
        self._pending_price = 0.0
        self._ma_closes: deque[float] = deque(maxlen=p.get("ma_period", 20))

    def reset(self) -> None:
        self._closes.clear()
        self._buy_count = 0
        self._sell_count = 0
        self._in_position = False
        self._pending_buy = False
        self._pending_sell = False
        self._pending_price = 0.0
        self._ma_closes.clear()

    def _trend_up(self, close: float) -> bool:
        if len(self._ma_closes) < self._ma_closes.maxlen:
            return True
        return close > sum(self._ma_closes) / len(self._ma_closes)

    def on_bar(self, bar: Bar, state: dict) -> Optional[Signal]:
        code = state.get("code", "UNKNOWN")

        if self._pending_buy:
            if bar.close > self._pending_price:
                self._pending_buy = False
                self._in_position = True
                return Signal(
                    code=code, side=Side.BUY, price=bar.close,
                    confidence=0.6, time=bar.time,
                    reason="九转买序列确认",
                )
            self._pending_buy = False

        if self._pending_sell:
            if bar.close < self._pending_price:
                self._pending_sell = False
                self._in_position = False
                return Signal(
                    code=code, side=Side.SELL, price=bar.close,
                    confidence=0.6, time=bar.time,
                    reason="九转卖序列确认",
                )
            self._pending_sell = False

        if len(self._closes) < self._period + 1:
            self._closes.append(bar.close)
            self._ma_closes.append(bar.close)
            return None

        close_period_ago = self._closes[0]
        self._closes.append(bar.close)
        self._ma_closes.append(bar.close)

        if bar.close < close_period_ago:
            self._buy_count += 1
            self._sell_count = 0
        elif bar.close > close_period_ago:
            self._sell_count += 1
            self._buy_count = 0
        else:
            self._buy_count = 0
            self._sell_count = 0

        use_trend = self._params.get("trend_filter")

        if not self._in_position and self._buy_count == 9:
            self._buy_count = 0
            if use_trend and not self._trend_up(bar.close):
                return None
            if self._params.get("confirm"):
                self._pending_buy = True
                self._pending_price = bar.close
            else:
                self._in_position = True
                return Signal(
                    code=code, side=Side.BUY, price=bar.close,
                    confidence=0.6, time=bar.time,
                    reason="九转买序列完成",
                )

        if self._in_position and self._sell_count == 9:
            self._sell_count = 0
            if self._params.get("confirm"):
                self._pending_sell = True
                self._pending_price = bar.close
            else:
                self._in_position = False
                return Signal(
                    code=code, side=Side.SELL, price=bar.close,
                    confidence=0.6, time=bar.time,
                    reason="九转卖序列完成",
                )

        return None
