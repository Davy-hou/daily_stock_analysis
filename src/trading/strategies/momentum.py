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
            raise ValueError(f"lookback must be >= 2, got {lookback}")
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
        code = self._params.get("code", "UNKNOWN")

        if not self._in_position and bar.close > highest * (1 + threshold):
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
                reason=f"exit below {self._params['lookback']}-bar low {lowest:.4f}",
            )

        return None
