"""Chart serializer — converts enriched intraday bars into LLM-consumable payloads.

Handles full-bar emission when the session fits within the token budget and
tiered compression (90-min full + 5-min compressed + pivots) when it does not.
The compression method is deterministic and always logged.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.enums import (
    ChartCompressionMethod,
    MarketStateHint,
    RangePosition,
)
from app.core.logging import get_logger
from app.core.timezone import dual_timestamp, to_et
from app.features import indicators as ind
from app.features.engine import FeatureSet
from app.market_data.models import Candle, Quote, ReferenceLevels

logger = get_logger("chart_serializer")


def _range_position(price: float, day_high: float, day_low: float) -> str:
    """Classify where price sits within the day's range."""
    if day_high == day_low:
        return RangePosition.MID_RANGE.value
    pct = (price - day_low) / (day_high - day_low)
    if pct >= 0.95:
        return RangePosition.NEAR_HIGH.value
    if pct >= 0.70:
        return RangePosition.UPPER_RANGE.value
    if pct >= 0.30:
        return RangePosition.MID_RANGE.value
    if pct >= 0.05:
        return RangePosition.LOWER_RANGE.value
    return RangePosition.NEAR_LOW.value


def _market_state_hint(fs: FeatureSet | None) -> str:
    """Infer a market state label from the feature set."""
    if fs is None:
        return MarketStateHint.RANGE.value
    if fs.chop.blocks_trade:
        return MarketStateHint.CHOP.value
    slope = fs.trend_slope
    above = fs.above_vwap
    hh = fs.higher_highs
    ll = fs.lower_lows
    dist = fs.dist_from_vwap_pct

    if hh and slope and slope > 0 and above:
        return MarketStateHint.TREND_UP.value
    if ll and slope and slope < 0 and not above:
        return MarketStateHint.TREND_DOWN.value
    if hh and not above:
        return MarketStateHint.REVERSAL_ATTEMPT.value
    if ll and above:
        return MarketStateHint.REVERSAL_ATTEMPT.value
    if dist and dist > 0.3:
        return MarketStateHint.BREAKOUT_ATTEMPT.value
    if dist and dist < -0.3:
        return MarketStateHint.BREAKDOWN_ATTEMPT.value
    return MarketStateHint.RANGE.value


def serialize_session_summary(
    candles: list[Candle],
    refs: ReferenceLevels | None,
    quote: Quote | None,
    fs: FeatureSet | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the compact session summary dict for the LLM payload."""
    from app.core.timezone import to_et, to_riyadh
    from datetime import timezone as _tz

    now = now or datetime.now(_tz.utc)
    refs = refs or ReferenceLevels()

    closes = [c.close for c in candles] if candles else []
    current_price = (quote.last if quote and quote.last else None) or (closes[-1] if closes else None)
    day_high = max((c.high for c in candles), default=None) if candles else None
    day_low = min((c.low for c in candles), default=None) if candles else None
    vwap = ind.session_vwap(candles) if candles else None
    ema10 = ind.ema(closes, 10)
    ema20 = ind.ema(closes, 20)
    rsi_val = ind.rsi(closes, 14)
    slope = ind.trend_slope(closes[-10:]) if len(closes) >= 2 else None
    vwap_series = ind.running_vwap_series(candles)
    cross_count = ind.vwap_cross_count(candles, vwap_series)
    or_hi, or_lo = ind.opening_range(candles, 15) if candles else (None, None)

    range_pos = _range_position(current_price, day_high, day_low) if (current_price and day_high and day_low) else RangePosition.MID_RANGE.value
    state_hint = _market_state_hint(fs)

    last_bar_time = candles[-1].ts if candles else now
    last_et = to_et(last_bar_time)
    last_riyadh = to_riyadh(last_bar_time)

    return {
        "current_price": round(current_price, 2) if current_price else None,
        "prior_close": round(refs.prev_close, 2) if refs.prev_close else None,
        "day_open": round(candles[0].open, 2) if candles else None,
        "day_high": round(day_high, 2) if day_high else None,
        "day_low": round(day_low, 2) if day_low else None,
        "premarket_high": round(refs.premarket_high, 2) if refs.premarket_high else None,
        "premarket_low": round(refs.premarket_low, 2) if refs.premarket_low else None,
        "opening_range_high": round(or_hi, 2) if or_hi else None,
        "opening_range_low": round(or_lo, 2) if or_lo else None,
        "vwap": round(vwap, 4) if vwap else None,
        "ema_10": round(ema10, 4) if ema10 else None,
        "ema_20": round(ema20, 4) if ema20 else None,
        "rsi_14": round(rsi_val, 2) if rsi_val else None,
        "trend_slope": round(slope, 6) if slope else None,
        "vwap_cross_count": cross_count,
        "current_range_position": range_pos,
        "market_state_hint": state_hint,
        "last_completed_bar_time_et": last_et.isoformat(),
        "last_completed_bar_time_gmt3": last_riyadh.isoformat(),
    }


def _compress_to_5min(bars: list[dict]) -> list[dict]:
    """Aggregate 1-minute bar dicts into 5-minute OHLCV dicts."""
    compressed: list[dict] = []
    chunk: list[dict] = []
    for bar in bars:
        chunk.append(bar)
        if len(chunk) == 5:
            compressed.append({
                "timestamp_et": chunk[0]["timestamp_et"],
                "timestamp_gmt3": chunk[0]["timestamp_gmt3"],
                "open": chunk[0]["open"],
                "high": max(b["high"] for b in chunk),
                "low": min(b["low"] for b in chunk),
                "close": chunk[-1]["close"],
                "volume": sum(b["volume"] for b in chunk),
                "vwap": chunk[-1].get("vwap"),
                "ema_10": chunk[-1].get("ema_10"),
                "ema_20": chunk[-1].get("ema_20"),
                "rsi_14": chunk[-1].get("rsi_14"),
                "atr_14": chunk[-1].get("atr_14"),
                "above_vwap": chunk[-1].get("above_vwap"),
                "distance_from_vwap_points": chunk[-1].get("distance_from_vwap_points"),
                "distance_from_vwap_percent": chunk[-1].get("distance_from_vwap_percent"),
                "bar_type": "5min_compressed",
            })
            chunk = []
    # Remaining bars (< 5) — emit as-is.
    if chunk:
        compressed.append({
            **chunk[-1],
            "bar_type": "1min_tail",
        })
    return compressed


def serialize_chart(
    enriched_bars: list[dict],
    max_full_bars: int = 390,
) -> tuple[list[dict], ChartCompressionMethod]:
    """Serialize bars for the LLM payload, applying compression if needed.

    Returns (bars, compression_method).
    """
    if not enriched_bars:
        return [], ChartCompressionMethod.FULL

    if len(enriched_bars) <= max_full_bars:
        return enriched_bars, ChartCompressionMethod.FULL

    # Tiered compression: last N bars full, earlier bars compressed to 5-min.
    cutoff = max(len(enriched_bars) - max_full_bars, 0)
    early = enriched_bars[:cutoff]
    recent = enriched_bars[cutoff:]

    compressed_early = _compress_to_5min(early)
    combined = compressed_early + recent
    logger.info(
        "chart compressed: %d bars → %d (early=%d→%d 5min, recent=%d full)",
        len(enriched_bars), len(combined), len(early), len(compressed_early), len(recent),
    )
    return combined, ChartCompressionMethod.TIERED_90M
