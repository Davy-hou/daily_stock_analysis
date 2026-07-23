from __future__ import annotations

from collections import deque
from typing import Any, Optional
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.base import Strategy


class RSIStrategy(Strategy):
    def __init__(self, params: dict[str, Any] | None = None):
        p = params or {}
        period = p.get("period", 14)
        oversold = p.get("oversold", 30)
        overbought = p.get("overbought", 70)
        if period < 1:
            raise ValueError(f"period must be >= 1, got {period}")
        if oversold >= overbought:
            raise ValueError(f"oversold ({oversold}) must be < overbought ({overbought})")
        super().__init__(name="rsi", params={**p, "period": period, "oversold": oversold, "overbought": overbought})
        self._period = period
        self._oversold = oversold
        self._overbought = overbought
        self._in_position = False
        self._prev_close: float | None = None
        self._gains: deque[float] = deque(maxlen=period)
        self._losses: deque[float] = deque(maxlen=period)
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None

    def reset(self) -> None:
        self._in_position = False
        self._prev_close = None
        self._gains.clear()
        self._losses.clear()
        self._avg_gain = None
        self._avg_loss = None

    def on_bar(self, bar: Bar, state: dict) -> Optional[Signal]:
        code = state.get("code", "UNKNOWN")

        if self._prev_close is None:
            self._prev_close = bar.close
            return None

        change = bar.close - self._prev_close
        self._prev_close = bar.close
        gain = max(change, 0.0)
        loss = max(-change, 0.0)
        self._gains.append(gain)
        self._losses.append(loss)

        if len(self._gains) < self._period:
            return None

        if self._avg_gain is None:
            self._avg_gain = sum(self._gains) / self._period
            self._avg_loss = sum(self._losses) / self._period
        else:
            self._avg_gain = (self._avg_gain * (self._period - 1) + gain) / self._period
            self._avg_loss = (self._avg_loss * (self._period - 1) + loss) / self._period

        if self._avg_loss == 0 and self._avg_gain == 0:
            rsi = 50.0
        elif self._avg_loss == 0:
            rsi = 100.0
        else:
            rsi = 100.0 - (100.0 / (1.0 + self._avg_gain / self._avg_loss))

        if not self._in_position and rsi < self._oversold:
            self._in_position = True
            return Signal(
                code=code, side=Side.BUY, price=bar.close,
                confidence=0.65, time=bar.time,
                reason=f"RSI超卖({rsi:.0f}<{self._oversold})",
            )

        if self._in_position and rsi > self._overbought:
            self._in_position = False
            return Signal(
                code=code, side=Side.SELL, price=bar.close,
                confidence=0.65, time=bar.time,
                reason=f"RSI超买({rsi:.0f}>{self._overbought})",
            )

        return None
