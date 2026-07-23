from __future__ import annotations

from collections import deque
from typing import Any, Optional
from src.trading.config import Bar, Signal, Side
from src.trading.strategies.base import Strategy


def _ema(prev: float, price: float, period: int) -> float:
    k = 2.0 / (period + 1)
    return (price - prev) * k + prev


class MACDStrategy(Strategy):
    def __init__(self, params: dict[str, Any] | None = None):
        p = params or {}
        fast = p.get("fast", 12)
        slow = p.get("slow", 26)
        signal = p.get("signal", 9)
        if slow <= fast:
            raise ValueError(f"slow ({slow}) must be > fast ({fast})")
        if fast < 1 or slow < 1 or signal < 1:
            raise ValueError("periods must be >= 1")
        super().__init__(name="macd", params={**p, "fast": fast, "slow": slow, "signal": signal})
        self._fast = fast
        self._slow = slow
        self._signal = signal
        self._ema_fast: float | None = None
        self._ema_slow: float | None = None
        self._signal_line: float | None = None
        self._prev_macd: float | None = None
        self._prev_signal: float | None = None
        self._in_position = False
        self._bars = 0

    def reset(self) -> None:
        self._ema_fast = None
        self._ema_slow = None
        self._signal_line = None
        self._prev_macd = None
        self._prev_signal = None
        self._in_position = False
        self._bars = 0

    def on_bar(self, bar: Bar, state: dict) -> Optional[Signal]:
        code = state.get("code", "UNKNOWN")
        self._bars += 1

        if self._ema_fast is None:
            self._ema_fast = bar.close
            self._ema_slow = bar.close
            return None

        self._ema_fast = _ema(self._ema_fast, bar.close, self._fast)
        self._ema_slow = _ema(self._ema_slow, bar.close, self._slow)

        if self._bars < self._slow:
            return None

        macd = self._ema_fast - self._ema_slow

        if self._signal_line is None:
            self._signal_line = macd
            self._prev_macd = macd
            self._prev_signal = macd
            return None

        self._signal_line = _ema(self._signal_line, macd, self._signal)

        cross_up = self._prev_macd <= self._prev_signal and macd > self._signal_line
        cross_down = self._prev_macd >= self._prev_signal and macd < self._signal_line

        self._prev_macd = macd
        self._prev_signal = self._signal_line

        if not self._in_position and cross_up:
            self._in_position = True
            return Signal(
                code=code, side=Side.BUY, price=bar.close,
                confidence=0.7, time=bar.time,
                reason="MACD金叉",
            )

        if self._in_position and cross_down:
            self._in_position = False
            return Signal(
                code=code, side=Side.SELL, price=bar.close,
                confidence=0.7, time=bar.time,
                reason="MACD死叉",
            )

        return None
