"""Tests for entry-timing no-late-entry gates."""
from datetime import datetime, timezone

from app.config.schema import EntryTimingConfig
from app.core.enums import Direction, RejectCode
from app.features.chop import ChopResult
from app.features.engine import FeatureSet
from app.market_data.models import Candle
from app.signals.entry_timing import candle_extension_filter, collect_entry_timing_filters


def _chop(**kw) -> ChopResult:
    base = dict(
        score=20.0, band="LOW", vwap_crosses=1,
        small_body_ratio=0.2, alternation_ratio=0.3, components={},
    )
    base.update(kw)
    return ChopResult(**base)


def _fs(**kw) -> FeatureSet:
    base = dict(
        symbol="NVDA", ts=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc),
        price=100.0, vwap=99.0, ema_fast=100.0, ema_slow=99.0,
        opening_range_high=98.0, opening_range_low=96.0,
        prev_close=95.0, day_high=101.0, day_low=96.0,
        relative_volume=2.0, volume_impulse=1.5,
        candle_body_pct=50.0, upper_wick_pct=10.0, lower_wick_pct=10.0,
        trend_slope=0.1, dist_from_vwap_pct=1.0,
        dist_from_or_high_pct=2.0, dist_from_or_low_pct=-2.0,
        spread_pct=0.1, above_vwap=True, higher_highs=True, lower_lows=False,
        momentum_score=80.0, bias="UP",
        chop=_chop(),
    )
    base.update(kw)
    return FeatureSet(**base)


def test_oversized_candle_rejected():
    cfg = EntryTimingConfig(max_candle_extension_mult=2.0)
    candles = [
        Candle(datetime(2026, 6, 2, 13, i, tzinfo=timezone.utc), 100, 100.2, 99.8, 100.1, 1000)
        for i in range(10)
    ]
    candles.append(
        Candle(datetime(2026, 6, 2, 13, 10, tzinfo=timezone.utc), 100, 105, 99, 104, 5000)
    )
    rc = candle_extension_filter(_fs(), candles, cfg)
    assert rc == RejectCode.BLOCKED_OVEREXTENDED


def test_premium_expansion_rejected():
    cfg = EntryTimingConfig(max_premium_preexpansion_pct=20.0)
    codes = collect_entry_timing_filters(
        _fs(), Direction.CALL, [],
        cfg, option_ask=2.5, option_bid=2.4, prior_option_mid=2.0,
    )
    assert RejectCode.BLOCKED_OVEREXTENDED in codes
