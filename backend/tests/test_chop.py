"""Chop detection tests: trending tape scores LOW, whipsaw scores HIGH."""
from datetime import datetime, timedelta, timezone

from app.features.chop import compute_chop
from app.market_data.models import Candle


def _c(o, h, l, c, v, i):
    return Candle(
        ts=datetime(2026, 6, 2, 13, 30, tzinfo=timezone.utc) + timedelta(minutes=i),
        open=o, high=h, low=l, close=c, volume=v,
    )


def test_insufficient_data_is_conservative():
    res = compute_chop([_c(1, 1, 1, 1, 1, 0)], relative_volume=2.0)
    assert res.band == "MEDIUM"


def test_strong_uptrend_is_low_chop():
    # Steady higher closes, full-bodied candles, rising tape, strong rel vol.
    candles = []
    price = 100.0
    for i in range(20):
        o = price
        c = price + 1.0
        candles.append(_c(o, c + 0.05, o - 0.05, c, 1000, i))
        price = c
    res = compute_chop(candles, relative_volume=2.0)
    assert res.band == "LOW"
    assert res.vwap_crosses <= 1
    assert not res.blocks_trade


def test_whipsaw_is_high_chop():
    # Alternating up/down small-body candles around a flat level, weak volume.
    candles = []
    for i in range(20):
        if i % 2 == 0:
            candles.append(_c(100.0, 100.4, 99.6, 100.05, 100, i))
        else:
            candles.append(_c(100.05, 100.4, 99.6, 99.95, 100, i))
    res = compute_chop(candles, relative_volume=0.4)
    assert res.band == "HIGH"
    assert res.blocks_trade
    assert res.vwap_crosses >= 3
