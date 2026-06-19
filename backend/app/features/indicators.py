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


# ---------------------------------------------------------------------------
# Extended indicators for LLM chart context
# ---------------------------------------------------------------------------

def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI on the final value of *closes*."""
    if len(closes) <= period:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            avg_gain = (avg_gain * (period - 1) + delta) / period
            avg_loss = (avg_loss * (period - 1)) / period
        else:
            avg_gain = (avg_gain * (period - 1)) / period
            avg_loss = (avg_loss * (period - 1) - delta) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr(candles: list[Candle], period: int = 14) -> float | None:
    """Average True Range (Wilder smoothing) at the end of the series."""
    if len(candles) < period + 1:
        return None

    def _tr(curr: Candle, prev: Candle) -> float:
        return max(
            curr.high - curr.low,
            abs(curr.high - prev.close),
            abs(curr.low - prev.close),
        )

    # Seed with simple average of first `period` true ranges.
    total = sum(_tr(candles[i], candles[i - 1]) for i in range(1, period + 1))
    atr_val = total / period
    for i in range(period + 1, len(candles)):
        atr_val = (atr_val * (period - 1) + _tr(candles[i], candles[i - 1])) / period
    return atr_val


def running_ema_series(closes: list[float], period: int) -> list[float | None]:
    """Full EMA series (one value per close) for chart serialisation."""
    out: list[float | None] = [None] * min(period - 1, len(closes))
    if len(closes) < period or period < 1:
        return [None] * len(closes)
    k = 2.0 / (period + 1.0)
    seed = sum(closes[:period]) / period
    out.append(seed)
    e = seed
    for v in closes[period:]:
        e = v * k + e * (1.0 - k)
        out.append(e)
    return out


def running_rsi_series(closes: list[float], period: int = 14) -> list[float | None]:
    """RSI at each bar from the start of the series (Wilder's method)."""
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= period:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            gains += d
        else:
            losses -= d
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        out[period] = 100.0
    else:
        out[period] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    for i in range(period + 1, n):
        d = closes[i] - closes[i - 1]
        if d >= 0:
            avg_gain = (avg_gain * (period - 1) + d) / period
            avg_loss = (avg_loss * (period - 1)) / period
        else:
            avg_gain = (avg_gain * (period - 1)) / period
            avg_loss = (avg_loss * (period - 1) - d) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            out[i] = 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))
    return out


def running_atr_series(candles: list[Candle], period: int = 14) -> list[float | None]:
    """ATR at each bar from the start of the series (Wilder smoothing)."""
    n = len(candles)
    out: list[float | None] = [None] * n
    if n < period + 1:
        return out

    def _tr(curr: Candle, prev: Candle) -> float:
        return max(
            curr.high - curr.low,
            abs(curr.high - prev.close),
            abs(curr.low - prev.close),
        )

    total = sum(_tr(candles[i], candles[i - 1]) for i in range(1, period + 1))
    atr_val = total / period
    out[period] = atr_val
    for i in range(period + 1, n):
        atr_val = (atr_val * (period - 1) + _tr(candles[i], candles[i - 1])) / period
        out[i] = atr_val
    return out
