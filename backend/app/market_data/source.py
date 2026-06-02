"""Market data source interface.

The scanner, feature engine, and (later) backtester depend only on this
abstraction, so a live TWS feed, a deterministic simulator, and a historical
replay are interchangeable.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.core.enums import OptionRight
from app.market_data.models import Candle, OptionChain, OptionQuote, Quote, ReferenceLevels


class MarketDataSource(ABC):
    name: str

    @abstractmethod
    async def get_candles_1m(self, symbol: str, lookback: int) -> list[Candle]:
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> Quote | None:
        ...

    @abstractmethod
    async def get_reference_levels(self, symbol: str) -> ReferenceLevels:
        ...

    @abstractmethod
    async def get_historical_avg_volume(self, symbol: str) -> float | None:
        ...

    @abstractmethod
    async def get_option_chain(self, underlying: str, spot: float) -> OptionChain | None:
        ...

    async def get_option_quote(
        self, underlying: str, expiry: str, strike: float, right: OptionRight
    ) -> OptionQuote | None:
        """Single-contract quote for position monitoring (optional override)."""
        return None

    async def close(self) -> None:  # optional cleanup hook
        return None
