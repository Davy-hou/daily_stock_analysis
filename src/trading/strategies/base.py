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
        return dict(self._params)

    @abstractmethod
    def on_bar(self, bar: Bar, state: dict[str, Any]) -> Optional[Signal]:
        ...

    def on_tick(self, tick: Any) -> Optional[Signal]:
        return None

    def reset(self) -> None:
        pass
