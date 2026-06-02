"""Deterministic candidate scoring (0–100) per the spec weighting.

This is a *rule-based* score — no opaque ML. The Phase-3 signal engine will add
the formal no-trade filters and entry-timing gates; the scanner already needs a
faithful score so it can rank and surface candidates with reason codes.

Weighting (sums to 100):
    underlying momentum     20
    relative volume         15
    VWAP alignment          15
    sector confirmation     15
    market confirmation     10
    option liquidity        10
    clean structure         10
    time-of-day suitability  5
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.enums import Direction, SignalType
from app.features.engine import FeatureSet
from app.scanner.regime import MarketRegime

_NY = ZoneInfo("America/New_York")


@dataclass
class ScoreBreakdown:
    momentum: float = 0.0
    relative_volume: float = 0.0
    vwap_alignment: float = 0.0
    sector_confirmation: float = 0.0
    market_confirmation: float = 0.0
    option_liquidity: float = 0.0
    clean_structure: float = 0.0
    time_of_day: float = 0.0

    @property
    def total(self) -> float:
        return round(
            self.momentum
            + self.relative_volume
            + self.vwap_alignment
            + self.sector_confirmation
            + self.market_confirmation
            + self.option_liquidity
            + self.clean_structure
            + self.time_of_day,
            1,
        )

    def to_dict(self) -> dict:
        d = {
            "momentum": round(self.momentum, 1),
            "relative_volume": round(self.relative_volume, 1),
            "vwap_alignment": round(self.vwap_alignment, 1),
            "sector_confirmation": round(self.sector_confirmation, 1),
            "market_confirmation": round(self.market_confirmation, 1),
            "option_liquidity": round(self.option_liquidity, 1),
            "clean_structure": round(self.clean_structure, 1),
            "time_of_day": round(self.time_of_day, 1),
        }
        d["total"] = self.total
        return d


def time_of_day_points(now_utc: datetime, max_pts: float = 5.0) -> float:
    """Scalping suitability by NY session window.

    Prime momentum windows (open drive + afternoon trend) score full; the lunch
    lull is reduced; outside regular trading hours scores zero.
    """
    ny = now_utc.astimezone(_NY)
    minutes = ny.hour * 60 + ny.minute
    open_m, close_m = 9 * 60 + 30, 16 * 60
    if minutes < open_m or minutes >= close_m:
        return 0.0
    # First 5 min are erratic; very last minutes unsuitable for new scalps.
    if minutes < open_m + 5 or minutes >= close_m - 15:
        return max_pts * 0.2
    prime_am = open_m + 5 <= minutes <= 11 * 60 + 30
    prime_pm = 13 * 60 + 30 <= minutes <= close_m - 15
    if prime_am or prime_pm:
        return max_pts
    return max_pts * 0.5  # midday lull


def _rvol_points(rvol: float | None, floor: float, max_pts: float) -> float:
    if rvol is None:
        return 0.0
    if rvol <= 1.0:
        return 0.0
    if rvol >= floor + 1.0:
        return max_pts
    # Linear ramp between 1.0 and floor+1.0.
    return max_pts * min((rvol - 1.0) / max(floor, 0.5), 1.0)


def infer_signal_type(fs: FeatureSet, direction: Direction) -> SignalType:
    """Best-effort setup classification for display/journaling.

    Phase 3 will own the authoritative classification; here we map the dominant
    feature pattern to a plausible type so the scanner is informative.
    """
    price = fs.price
    if price is None or fs.bias == "FLAT":
        return SignalType.NO_SETUP

    if direction == Direction.CALL:
        if fs.opening_range_high is not None and price >= fs.opening_range_high:
            return SignalType.OPENING_RANGE_BREAKOUT
        if fs.above_vwap and (fs.dist_from_vwap_pct or 0.0) < 0.15:
            return SignalType.VWAP_RECLAIM_CONTINUATION
        if fs.higher_highs:
            return SignalType.MOMENTUM_BREAKOUT
        return SignalType.PULLBACK_CONTINUATION

    if fs.opening_range_low is not None and price <= fs.opening_range_low:
        return SignalType.MOMENTUM_BREAKDOWN
    if fs.above_vwap is False and abs(fs.dist_from_vwap_pct or 0.0) < 0.15:
        return SignalType.VWAP_REJECTION_CONTINUATION
    if fs.lower_lows:
        return SignalType.MOMENTUM_BREAKDOWN
    return SignalType.PULLBACK_CONTINUATION


def score_candidate(
    fs: FeatureSet,
    direction: Direction,
    *,
    regime: MarketRegime,
    is_index: bool,
    min_relative_volume: float,
    option_liquidity_ok: bool,
    option_spread_pct: float | None,
    preferred_spread_pct: float,
    now_utc: datetime,
) -> ScoreBreakdown:
    """Score a directional candidate for one symbol. Returns a full breakdown."""
    b = ScoreBreakdown()
    direction_up = direction == Direction.CALL

    # --- Underlying momentum (20) — only credited when bias matches direction. ---
    if (fs.bias == "UP" and direction_up) or (fs.bias == "DOWN" and not direction_up):
        b.momentum = (fs.momentum_score / 100.0) * 20.0

    # --- Relative volume (15). ---
    b.relative_volume = _rvol_points(fs.relative_volume, min_relative_volume, 15.0)

    # --- VWAP alignment (15). ---
    if fs.above_vwap is not None:
        if fs.above_vwap == direction_up:
            b.vwap_alignment = 15.0
        else:
            b.vwap_alignment = 0.0
    # Penalize chop: scale VWAP alignment down by chop band.
    if fs.chop.band == "MEDIUM":
        b.vwap_alignment *= 0.6
    elif fs.chop.band == "HIGH":
        b.vwap_alignment *= 0.2

    # --- Sector confirmation (15). For an index, fold into market instead. ---
    if is_index:
        b.sector_confirmation = 0.0
    else:
        align = regime.alignment("sector", direction_up)
        b.sector_confirmation = max(0.0, align) * 15.0

    # --- Market confirmation (10) (plus index gets sector's 15 here). ---
    market_align = regime.alignment("market", direction_up)
    tech_align = regime.alignment("tech", direction_up)
    combined = (market_align + tech_align) / 2.0
    market_pts_cap = 25.0 if is_index else 10.0
    b.market_confirmation = max(0.0, combined) * market_pts_cap

    # --- Option liquidity (10). ---
    if option_liquidity_ok:
        if option_spread_pct is not None and option_spread_pct <= preferred_spread_pct:
            b.option_liquidity = 10.0
        else:
            b.option_liquidity = 6.0

    # --- Clean structure (10): directional HH/HL or LH/LL + decent candle body. ---
    structure_ok = (fs.higher_highs and direction_up) or (fs.lower_lows and not direction_up)
    if structure_ok:
        b.clean_structure = 7.0
        if (fs.candle_body_pct or 0.0) >= 0.5:
            b.clean_structure += 3.0

    # --- Time of day (5). ---
    b.time_of_day = time_of_day_points(now_utc, 5.0)
    return b
