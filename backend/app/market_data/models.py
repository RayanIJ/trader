"""Plain data-transfer objects for market data.

Deliberately dependency-free (no pandas/numpy) so the feature engine, scanner,
and backtester share the same lightweight types and stay fast and portable.
Times are timezone-aware UTC datetimes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.core.enums import DataFeedStatus, OptionRight


@dataclass(frozen=True)
class Candle:
    ts: datetime           # bar open time (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return max(self.high - self.low, 0.0)

    @property
    def is_green(self) -> bool:
        return self.close >= self.open

    @property
    def typical_price(self) -> float:
        return (self.high + self.low + self.close) / 3.0


@dataclass
class Quote:
    symbol: str
    ts: datetime
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float | None = None
    feed: DataFeedStatus = DataFeedStatus.UNAVAILABLE

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.ask >= self.bid >= 0:
            return self.ask - self.bid
        return None

    @property
    def spread_pct(self) -> float | None:
        s = self.spread
        m = self.mid
        if s is None or not m:
            return None
        return (s / m) * 100.0

    def is_stale(self, now: datetime, max_age_sec: float) -> bool:
        return (now - self.ts).total_seconds() > max_age_sec

    def has_two_sided(self) -> bool:
        return (
            self.bid is not None and self.ask is not None
            and self.bid > 0 and self.ask > 0 and self.ask >= self.bid
        )


@dataclass(frozen=True)
class OptionContractSpec:
    """An option contract definition (no live quote)."""

    underlying: str
    expiry: str            # YYYYMMDD
    strike: float
    right: OptionRight
    multiplier: float | None = None
    con_id: int | None = None

    @property
    def is_defined(self) -> bool:
        return self.multiplier is not None and self.multiplier > 0


@dataclass
class OptionQuote:
    spec: OptionContractSpec
    ts: datetime
    bid: float | None = None
    ask: float | None = None
    last: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    iv: float | None = None
    delta: float | None = None
    gamma: float | None = None
    theta: float | None = None
    vega: float | None = None
    feed: DataFeedStatus = DataFeedStatus.UNAVAILABLE

    @property
    def mid(self) -> float | None:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last

    @property
    def spread_pct(self) -> float | None:
        if (
            self.bid is not None and self.ask is not None
            and self.bid > 0 and self.ask > 0 and self.ask >= self.bid
        ):
            m = (self.bid + self.ask) / 2.0
            return ((self.ask - self.bid) / m) * 100.0 if m else None
        return None

    def has_two_sided(self) -> bool:
        return (
            self.bid is not None and self.ask is not None
            and self.bid > 0 and self.ask > 0 and self.ask >= self.bid
        )


@dataclass
class ReferenceLevels:
    """Daily reference levels used by the feature engine."""

    prev_close: float | None = None
    premarket_high: float | None = None
    premarket_low: float | None = None
    day_high: float | None = None
    day_low: float | None = None


@dataclass
class OptionChain:
    underlying: str
    asof: datetime
    expiries: list[str] = field(default_factory=list)
    quotes: list[OptionQuote] = field(default_factory=list)

    def has_zero_dte(self, today_yyyymmdd: str) -> bool:
        return today_yyyymmdd in self.expiries
