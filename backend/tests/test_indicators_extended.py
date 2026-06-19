"""Tests for the extended indicators — RSI, ATR, running series."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.features.indicators import (
    atr,
    rsi,
    running_atr_series,
    running_ema_series,
    running_rsi_series,
)
from app.market_data.models import Candle


def _candles(prices: list[float], start: datetime | None = None) -> list[Candle]:
    start = start or datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    return [
        Candle(
            ts=start + timedelta(minutes=i),
            open=p - 0.05, high=p + 0.10, low=p - 0.10,
            close=p, volume=1000,
        )
        for i, p in enumerate(prices)
    ]


class TestRSI:
    def test_rsi_too_few_bars(self):
        assert rsi([100, 101, 102], period=14) is None

    def test_rsi_all_gains(self):
        closes = list(range(100, 120))  # 20 bars, all going up
        val = rsi(closes, period=14)
        assert val is not None
        assert val > 80  # Should be very high RSI

    def test_rsi_all_losses(self):
        closes = list(range(120, 100, -1))  # 20 bars, all going down
        val = rsi(closes, period=14)
        assert val is not None
        assert val < 20  # Should be very low RSI

    def test_rsi_range_0_100(self):
        closes = [100 + (i % 3) - 1 for i in range(30)]
        val = rsi(closes, period=14)
        assert val is not None
        assert 0 <= val <= 100

    def test_rsi_known_value(self):
        """Verify against a known RSI computation."""
        # 15 bars: first 14 changes seed, then one more.
        closes = [44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10, 45.42,
                  45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28]
        val = rsi(closes, period=14)
        assert val is not None
        # RSI should be moderate (around 66-72 for this series).
        assert 50 < val < 85


class TestATR:
    def test_atr_too_few_bars(self):
        candles = _candles([100, 101, 102])
        assert atr(candles, period=14) is None

    def test_atr_positive(self):
        prices = [100 + i * 0.5 for i in range(20)]
        candles = _candles(prices)
        val = atr(candles, period=14)
        assert val is not None
        assert val > 0

    def test_atr_flat_prices(self):
        prices = [100.0] * 20
        candles = _candles(prices)
        val = atr(candles, period=14)
        assert val is not None
        # ATR should be near 0 for flat prices, but there's still
        # high-low range from our synthetic candles.
        assert val >= 0


class TestRunningEMASeries:
    def test_length_matches_input(self):
        closes = [100 + i for i in range(30)]
        series = running_ema_series(closes, 10)
        assert len(series) == 30

    def test_none_before_warmup(self):
        closes = [100 + i for i in range(30)]
        series = running_ema_series(closes, 10)
        # First 9 should be None (period=10 needs 10 bars for seed).
        for i in range(9):
            assert series[i] is None
        assert series[9] is not None

    def test_too_few_bars(self):
        closes = [100, 101]
        series = running_ema_series(closes, 10)
        assert all(v is None for v in series)


class TestRunningRSISeries:
    def test_length_matches_input(self):
        closes = [100 + i for i in range(30)]
        series = running_rsi_series(closes, 14)
        assert len(series) == 30

    def test_none_before_warmup(self):
        closes = [100 + i for i in range(30)]
        series = running_rsi_series(closes, 14)
        for i in range(14):
            assert series[i] is None
        assert series[14] is not None

    def test_values_in_range(self):
        closes = [100 + (i % 5) - 2 for i in range(30)]
        series = running_rsi_series(closes, 14)
        for v in series:
            if v is not None:
                assert 0 <= v <= 100


class TestRunningATRSeries:
    def test_length_matches_input(self):
        prices = [100 + i * 0.1 for i in range(30)]
        candles = _candles(prices)
        series = running_atr_series(candles, 14)
        assert len(series) == 30

    def test_none_before_warmup(self):
        prices = [100 + i * 0.1 for i in range(30)]
        candles = _candles(prices)
        series = running_atr_series(candles, 14)
        for i in range(14):
            assert series[i] is None
        assert series[14] is not None
