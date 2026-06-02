"""Chop detection.

A 0–100 chop score penalizes conditions that make momentum scalps unreliable:
repeated VWAP crosses, small-bodied candles, alternating red/green candles, low
relative volume, and a tight range around VWAP. Cross-asset disagreement (SPX /
QQQ / SMH / SOXX pointing different ways) is layered in by the scanner.

Bands:
* LOW    (< 35)  -> normal scoring
* MEDIUM (35-65) -> requires a higher setup score
* HIGH   (> 65)  -> blocks trades
"""
from __future__ import annotations

from dataclasses import dataclass

from app.features.indicators import (
    candle_body_pct,
    running_vwap_series,
    vwap_cross_count,
)
from app.market_data.models import Candle


@dataclass
class ChopResult:
    score: float                 # 0..100 (higher = choppier)
    band: str                    # LOW / MEDIUM / HIGH
    vwap_crosses: int
    small_body_ratio: float
    alternation_ratio: float
    components: dict[str, float]

    @property
    def blocks_trade(self) -> bool:
        return self.band == "HIGH"


def _band(score: float) -> str:
    if score > 65:
        return "HIGH"
    if score >= 35:
        return "MEDIUM"
    return "LOW"


def compute_chop(
    candles: list[Candle],
    *,
    relative_volume: float | None,
    vwap_cross_limit: int = 3,
    small_body_threshold: float = 0.35,
    window: int = 20,
) -> ChopResult:
    """Compute a chop score over the most recent ``window`` 1-minute candles."""
    recent = candles[-window:] if len(candles) > window else list(candles)
    n = len(recent)
    if n < 3:
        # Not enough data -> treat as choppy/unknown to stay conservative.
        return ChopResult(60.0, "MEDIUM", 0, 0.0, 0.0, {"insufficient_data": 60.0})

    vwap_series = running_vwap_series(recent)
    crosses = vwap_cross_count(recent, vwap_series)

    # 1) VWAP crosses vs the configured limit (capped at 1.0).
    cross_pen = min(crosses / max(vwap_cross_limit, 1), 1.0)

    # 2) Fraction of small-bodied candles.
    small_bodies = sum(1 for c in recent if candle_body_pct(c) < small_body_threshold)
    small_body_ratio = small_bodies / n
    small_body_pen = small_body_ratio

    # 3) Color alternation ratio (green/red flip-flopping).
    flips = 0
    for i in range(1, n):
        if recent[i].is_green != recent[i - 1].is_green:
            flips += 1
    alternation_ratio = flips / (n - 1)
    alternation_pen = alternation_ratio

    # 4) Low relative volume penalty (rel vol < 1 is choppy/illiquid).
    if relative_volume is None:
        rvol_pen = 0.5
    elif relative_volume >= 1.5:
        rvol_pen = 0.0
    elif relative_volume <= 0.5:
        rvol_pen = 1.0
    else:
        rvol_pen = (1.5 - relative_volume) / 1.0  # linear 0.5->1.0 vol => 1.0->0.0 pen

    # 5) Tight range around VWAP: closes hugging VWAP within a small band.
    last_vwap = vwap_series[-1]
    if last_vwap:
        avg_close = sum(c.close for c in recent) / n
        spread = sum(abs(c.close - last_vwap) for c in recent) / n
        tight_pen = 1.0 if (avg_close and (spread / avg_close) < 0.0008) else 0.0
    else:
        tight_pen = 0.0

    components = {
        "vwap_crosses": cross_pen * 30.0,
        "small_bodies": small_body_pen * 25.0,
        "alternation": alternation_pen * 20.0,
        "low_rvol": rvol_pen * 15.0,
        "tight_range": tight_pen * 10.0,
    }
    score = min(sum(components.values()), 100.0)
    return ChopResult(
        score=round(score, 1),
        band=_band(score),
        vwap_crosses=crosses,
        small_body_ratio=round(small_body_ratio, 3),
        alternation_ratio=round(alternation_ratio, 3),
        components={k: round(v, 2) for k, v in components.items()},
    )
