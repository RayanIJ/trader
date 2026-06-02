"""Unit tests for the pure-Python intraday indicators."""
from datetime import datetime, timedelta, timezone

import pytest

from app.features import indicators as ind
from app.market_data.models import Candle


def _c(o, h, l, c, v, i=0):
    return Candle(
        ts=datetime(2026, 6, 2, 13, 30, tzinfo=timezone.utc) + timedelta(minutes=i),
        open=o, high=h, low=l, close=c, volume=v,
    )


def test_session_vwap_volume_weighted():
    candles = [_c(10, 10, 10, 10, 1, 0), _c(20, 20, 20, 20, 3, 1)]
    # typical prices are 10 and 20; weighted by 1 and 3 -> (10*1 + 20*3)/4 = 17.5
    assert ind.session_vwap(candles) == pytest.approx(17.5)


def test_session_vwap_zero_volume_returns_none():
    assert ind.session_vwap([_c(10, 10, 10, 10, 0)]) is None


def test_ema_matches_manual_for_flat_series():
    # A flat series' EMA equals the constant value.
    vals = [5.0] * 10
    assert ind.ema(vals, 3) == pytest.approx(5.0)


def test_ema_requires_enough_data():
    assert ind.ema([1.0, 2.0], 5) is None


def test_opening_range_window():
    candles = [_c(1, 5, 0.5, 2, 1, i) for i in range(10)]
    hi, lo = ind.opening_range(candles, 3)
    assert hi == 5
    assert lo == 0.5


def test_relative_volume():
    assert ind.relative_volume(150.0, 100.0) == pytest.approx(1.5)
    assert ind.relative_volume(100.0, None) is None
    assert ind.relative_volume(100.0, 0.0) is None


def test_volume_impulse_last_vs_prior_avg():
    candles = [_c(1, 1, 1, 1, 10, i) for i in range(5)] + [_c(1, 1, 1, 1, 40, 5)]
    # prior 5 avg = 10, last = 40 -> impulse 4.0
    assert ind.volume_impulse(candles, lookback=5) == pytest.approx(4.0)


def test_candle_body_and_wicks():
    c = _c(10, 12, 9, 11, 1)  # range 3, body 1, upper wick 1, lower wick 1
    assert ind.candle_body_pct(c) == pytest.approx(1 / 3)
    assert ind.upper_wick_pct(c) == pytest.approx(1 / 3)
    assert ind.lower_wick_pct(c) == pytest.approx(1 / 3)


def test_candle_body_pct_zero_range():
    assert ind.candle_body_pct(_c(10, 10, 10, 10, 1)) == 0.0


def test_trend_slope_sign():
    assert ind.trend_slope([1, 2, 3, 4]) > 0
    assert ind.trend_slope([4, 3, 2, 1]) < 0
    assert ind.trend_slope([2, 2, 2]) == pytest.approx(0.0)


def test_distance_pct_signed():
    assert ind.distance_pct(110, 100) == pytest.approx(10.0)
    assert ind.distance_pct(90, 100) == pytest.approx(-10.0)
    assert ind.distance_pct(100, None) is None


def test_vwap_cross_count():
    candles = [_c(1, 1, 1, c, 1, i) for i, c in enumerate([1, 3, 1, 3])]
    vwap = [2.0, 2.0, 2.0, 2.0]
    # sides: -1, +1, -1, +1 -> 3 crosses
    assert ind.vwap_cross_count(candles, vwap) == 3
