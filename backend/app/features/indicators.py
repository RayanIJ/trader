"""Pure-Python intraday indicators.

No pandas/numpy: the inputs are short intraday candle lists, so plain loops are
fast and keep the dependency surface minimal (important on bleeding-edge Python
versions). Every function is deterministic and unit-tested.
"""
from __future__ import annotations

from app.market_data.models import Candle


def session_vwap(candles: list[Candle]) -> float | None:
    """Volume-weighted average price across the provided (session) candles."""
    num = 0.0
    den = 0.0
    for c in candles:
        num += c.typical_price * c.volume
        den += c.volume
    if den <= 0:
        return None
    return num / den


def ema(values: list[float], period: int) -> float | None:
    """Exponential moving average of the final value in the series."""
    if not values or period < 1 or len(values) < period:
        return None
    k = 2.0 / (period + 1.0)
    # Seed with the SMA of the first `period` values for stability.
    seed = sum(values[:period]) / period
    e = seed
    for v in values[period:]:
        e = v * k + e * (1.0 - k)
    return e


def opening_range(candles: list[Candle], minutes: int) -> tuple[float | None, float | None]:
    """High/low of the first ``minutes`` of 1-minute candles."""
    if not candles:
        return None, None
    window = candles[:minutes]
    if not window:
        return None, None
    hi = max(c.high for c in window)
    lo = min(c.low for c in window)
    return hi, lo


def relative_volume(today_volume: float, historical_avg_volume: float | None) -> float | None:
    """Today's cumulative volume vs the historical average for the same period."""
    if not historical_avg_volume or historical_avg_volume <= 0:
        return None
    return today_volume / historical_avg_volume


def volume_impulse(candles: list[Candle], lookback: int = 5) -> float | None:
    """Latest candle volume vs the average of the prior ``lookback`` candles."""
    if len(candles) < lookback + 1:
        return None
    prior = candles[-(lookback + 1):-1]
    avg = sum(c.volume for c in prior) / len(prior)
    if avg <= 0:
        return None
    return candles[-1].volume / avg


def candle_body_pct(c: Candle) -> float:
    """Body size as a fraction of the candle range (0..1)."""
    if c.range <= 0:
        return 0.0
    return c.body / c.range


def upper_wick_pct(c: Candle) -> float:
    if c.range <= 0:
        return 0.0
    return (c.high - max(c.open, c.close)) / c.range


def lower_wick_pct(c: Candle) -> float:
    if c.range <= 0:
        return 0.0
    return (min(c.open, c.close) - c.low) / c.range


def trend_slope(values: list[float]) -> float | None:
    """Least-squares slope of ``values`` over their index (per-bar change)."""
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(values) / n
    num = sum((xs[i] - mean_x) * (values[i] - mean_y) for i in range(n))
    den = sum((x - mean_x) ** 2 for x in xs)
    if den == 0:
        return None
    return num / den


def distance_pct(price: float, level: float | None) -> float | None:
    """Signed distance from ``level`` as a percentage of ``level``."""
    if level is None or level == 0:
        return None
    return ((price - level) / level) * 100.0


def vwap_cross_count(candles: list[Candle], vwap_series: list[float | None]) -> int:
    """Number of times close crosses VWAP across aligned series."""
    crosses = 0
    prev_side: int | None = None
    for c, v in zip(candles, vwap_series):
        if v is None:
            continue
        side = 1 if c.close >= v else -1
        if prev_side is not None and side != prev_side:
            crosses += 1
        prev_side = side
    return crosses


def running_vwap_series(candles: list[Candle]) -> list[float | None]:
    """Cumulative VWAP value at each bar (used for chop/cross detection)."""
    out: list[float | None] = []
    num = 0.0
    den = 0.0
    for c in candles:
        num += c.typical_price * c.volume
        den += c.volume
        out.append((num / den) if den > 0 else None)
    return out
