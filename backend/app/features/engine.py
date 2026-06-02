"""Feature engine.

Assembles a deterministic :class:`FeatureSet` for one symbol from its intraday
1-minute candles, latest quote, and daily reference levels. These features feed
the Phase-3 signal engine and the scanner ranking. The engine itself makes NO
trading decision — it only measures.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from app.config.schema import MarketDataConfig, SignalConfig
from app.features import indicators as ind
from app.features.chop import ChopResult, compute_chop
from app.market_data.models import Candle, Quote, ReferenceLevels


@dataclass
class FeatureSet:
    symbol: str
    ts: datetime
    price: float | None
    vwap: float | None
    ema_fast: float | None
    ema_slow: float | None
    opening_range_high: float | None
    opening_range_low: float | None
    prev_close: float | None
    day_high: float | None
    day_low: float | None
    relative_volume: float | None
    volume_impulse: float | None
    candle_body_pct: float | None
    upper_wick_pct: float | None
    lower_wick_pct: float | None
    trend_slope: float | None
    dist_from_vwap_pct: float | None
    dist_from_or_high_pct: float | None
    dist_from_or_low_pct: float | None
    spread_pct: float | None
    above_vwap: bool | None
    higher_highs: bool
    lower_lows: bool
    momentum_score: float           # 0..100 directional strength (sign in `bias`)
    bias: str                       # UP / DOWN / FLAT
    chop: ChopResult
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ts"] = self.ts.isoformat()
        d["chop"] = {
            "score": self.chop.score,
            "band": self.chop.band,
            "vwap_crosses": self.chop.vwap_crosses,
        }
        return d


def _structure(candles: list[Candle], window: int = 6) -> tuple[bool, bool]:
    """Detect higher-highs/higher-lows vs lower-highs/lower-lows over a window."""
    seg = candles[-window:]
    if len(seg) < 3:
        return False, False
    mid = len(seg) // 2
    first_hi = max(c.high for c in seg[:mid])
    last_hi = max(c.high for c in seg[mid:])
    first_lo = min(c.low for c in seg[:mid])
    last_lo = min(c.low for c in seg[mid:])
    higher_highs = last_hi > first_hi and last_lo > first_lo
    lower_lows = last_lo < first_lo and last_hi < first_hi
    return higher_highs, lower_lows


def _momentum(
    price: float | None,
    vwap: float | None,
    ema_fast: float | None,
    ema_slow: float | None,
    slope: float | None,
    higher_highs: bool,
    lower_lows: bool,
) -> tuple[float, str]:
    """Combine alignment signals into a 0..100 magnitude and a direction bias."""
    if price is None:
        return 0.0, "FLAT"
    up = 0
    down = 0
    if vwap is not None:
        if price > vwap:
            up += 1
        else:
            down += 1
    if ema_fast is not None and ema_slow is not None:
        if ema_fast > ema_slow:
            up += 1
        else:
            down += 1
    if slope is not None:
        if slope > 0:
            up += 1
        elif slope < 0:
            down += 1
    if higher_highs:
        up += 1
    if lower_lows:
        down += 1

    total = up + down
    if total == 0:
        return 0.0, "FLAT"
    if up > down:
        return round((up / 5.0) * 100.0, 1), "UP"
    if down > up:
        return round((down / 5.0) * 100.0, 1), "DOWN"
    return 0.0, "FLAT"


class FeatureEngine:
    def __init__(self, md_cfg: MarketDataConfig, signal_cfg: SignalConfig) -> None:
        self._md = md_cfg
        self._sig = signal_cfg

    def build(
        self,
        symbol: str,
        candles_1m: list[Candle],
        quote: Quote | None,
        refs: ReferenceLevels | None = None,
        historical_avg_volume: float | None = None,
        now: datetime | None = None,
    ) -> FeatureSet:
        refs = refs or ReferenceLevels()
        now = now or (candles_1m[-1].ts if candles_1m else datetime.utcnow())
        price = (quote.last if quote and quote.last else None) or (
            candles_1m[-1].close if candles_1m else None
        )

        closes = [c.close for c in candles_1m]
        vwap = ind.session_vwap(candles_1m)
        ema_fast = ind.ema(closes, self._md.ema_fast)
        ema_slow = ind.ema(closes, self._md.ema_slow)
        or_hi, or_lo = ind.opening_range(candles_1m, self._sig.opening_range_minutes)
        today_vol = sum(c.volume for c in candles_1m)
        rvol = ind.relative_volume(today_vol, historical_avg_volume)
        vimp = ind.volume_impulse(candles_1m)
        last = candles_1m[-1] if candles_1m else None
        slope = ind.trend_slope(closes[-10:]) if len(closes) >= 2 else None
        higher_highs, lower_lows = _structure(candles_1m)

        momentum_score, bias = _momentum(
            price, vwap, ema_fast, ema_slow, slope, higher_highs, lower_lows
        )

        chop = compute_chop(
            candles_1m,
            relative_volume=rvol,
            vwap_cross_limit=self._sig.vwap_chop_cross_limit,
            window=self._sig.vwap_chop_window_min,
        )

        return FeatureSet(
            symbol=symbol,
            ts=now,
            price=price,
            vwap=vwap,
            ema_fast=ema_fast,
            ema_slow=ema_slow,
            opening_range_high=or_hi,
            opening_range_low=or_lo,
            prev_close=refs.prev_close,
            day_high=refs.day_high or (max(c.high for c in candles_1m) if candles_1m else None),
            day_low=refs.day_low or (min(c.low for c in candles_1m) if candles_1m else None),
            relative_volume=rvol,
            volume_impulse=vimp,
            candle_body_pct=ind.candle_body_pct(last) if last else None,
            upper_wick_pct=ind.upper_wick_pct(last) if last else None,
            lower_wick_pct=ind.lower_wick_pct(last) if last else None,
            trend_slope=slope,
            dist_from_vwap_pct=ind.distance_pct(price, vwap) if price else None,
            dist_from_or_high_pct=ind.distance_pct(price, or_hi) if price else None,
            dist_from_or_low_pct=ind.distance_pct(price, or_lo) if price else None,
            spread_pct=quote.spread_pct if quote else None,
            above_vwap=(price > vwap) if (price is not None and vwap is not None) else None,
            higher_highs=higher_highs,
            lower_lows=lower_lows,
            momentum_score=momentum_score,
            bias=bias,
            chop=chop,
        )
