"""Entry-timing gates — no-late-entry rules for 0DTE scalping.

Rejects entries when momentum is already extended, the option premium already
expanded, the trigger candle is oversized, or price is chasing beyond the key
level. These run after the scanner score but before risk approval.
"""
from __future__ import annotations

from app.config.schema import EntryTimingConfig
from app.core.enums import Direction, RejectCode
from app.features.engine import FeatureSet
from app.market_data.models import Candle


def _avg_body(candles: list[Candle], lookback: int = 10) -> float | None:
    seg = candles[-lookback:]
    if len(seg) < 3:
        return None
    bodies = [abs(c.close - c.open) for c in seg]
    return sum(bodies) / len(bodies)


def candle_extension_filter(
    fs: FeatureSet, candles: list[Candle], cfg: EntryTimingConfig
) -> RejectCode | None:
    """Reject if the latest candle body is much larger than recent average."""
    if not candles:
        return None
    last = candles[-1]
    avg = _avg_body(candles)
    if avg is None or avg <= 0:
        return None
    body = abs(last.close - last.open)
    if body > avg * cfg.max_candle_extension_mult:
        return RejectCode.BLOCKED_OVEREXTENDED
    return None


def level_distance_filter(fs: FeatureSet, direction: Direction, cfg: EntryTimingConfig) -> RejectCode | None:
    """Reject if price is too far beyond the breakout/breakdown level (chasing)."""
    if fs.price is None:
        return None
    if direction == Direction.CALL:
        level = fs.opening_range_high
        dist = fs.dist_from_or_high_pct
    else:
        level = fs.opening_range_low
        dist = fs.dist_from_or_low_pct
    if level is None or dist is None:
        return None
    # dist_from_or_* is signed distance from level; positive = beyond level in breakout dir.
    if direction == Direction.CALL and dist > cfg.max_distance_beyond_level_pct:
        return RejectCode.BLOCKED_OVEREXTENDED
    if direction == Direction.PUT and dist < -cfg.max_distance_beyond_level_pct:
        return RejectCode.BLOCKED_OVEREXTENDED
    return None


def scalp_distance_filter(fs: FeatureSet, direction: Direction, cfg: EntryTimingConfig) -> RejectCode | None:
    """Reject if the move already traveled most of the expected scalp distance."""
    if fs.price is None or fs.vwap is None:
        return None
    # Expected scalp distance: opening-range width or VWAP-to-level span.
    or_hi, or_lo = fs.opening_range_high, fs.opening_range_low
    if or_hi is None or or_lo is None:
        return None
    or_width = max(or_hi - or_lo, fs.price * 0.001)
    if direction == Direction.CALL:
        traveled = max(fs.price - or_hi, 0.0)
    else:
        traveled = max(or_lo - fs.price, 0.0)
    if or_width > 0 and (traveled / or_width) > cfg.max_scalp_distance_traveled_pct:
        return RejectCode.BLOCKED_OVEREXTENDED
    return None


def premium_expansion_filter(
    option_ask: float | None,
    option_bid: float | None,
    prior_mid: float | None,
    cfg: EntryTimingConfig,
) -> RejectCode | None:
    """Reject if the option premium already expanded sharply before entry."""
    if prior_mid is None or prior_mid <= 0:
        return None
    mid = None
    if option_bid and option_ask and option_bid > 0 and option_ask > 0:
        mid = (option_bid + option_ask) / 2.0
    elif option_ask and option_ask > 0:
        mid = option_ask
    if mid is None:
        return None
    expansion = ((mid - prior_mid) / prior_mid) * 100.0
    if expansion > cfg.max_premium_preexpansion_pct:
        return RejectCode.BLOCKED_OVEREXTENDED
    return None


def collect_entry_timing_filters(
    fs: FeatureSet,
    direction: Direction,
    candles: list[Candle],
    cfg: EntryTimingConfig,
    *,
    option_ask: float | None = None,
    option_bid: float | None = None,
    prior_option_mid: float | None = None,
) -> list[RejectCode]:
    codes: list[RejectCode] = []
    for rc in (
        candle_extension_filter(fs, candles, cfg),
        level_distance_filter(fs, direction, cfg),
        scalp_distance_filter(fs, direction, cfg),
        premium_expansion_filter(option_ask, option_bid, prior_option_mid, cfg),
    ):
        if rc is not None and rc not in codes:
            codes.append(rc)
    if cfg.reject_if_chasing and RejectCode.BLOCKED_OVEREXTENDED in codes:
        return codes
    return codes
