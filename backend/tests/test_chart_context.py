"""Tests for chart context — validation, serialization, and compression."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.enums import ChartCompressionMethod, RejectCode
from app.llm.chart_serializer import serialize_chart, serialize_session_summary
from app.llm.chart_validator import validate_chart_context
from app.market_data.intraday_bars import enrich_bars
from app.market_data.models import Candle, Quote, ReferenceLevels


def _candles(n: int, start: datetime | None = None, price: float = 100.0) -> list[Candle]:
    """Generate n 1-minute candles."""
    start = start or (datetime.now(timezone.utc) - timedelta(minutes=n + 1))
    candles = []
    for i in range(n):
        ts = start + timedelta(minutes=i)
        p = price + i * 0.05
        candles.append(Candle(
            ts=ts, open=p, high=p + 0.10, low=p - 0.05,
            close=p + 0.02, volume=1000 + i * 10,
        ))
    return candles


class TestChartValidator:
    """Pre-flight chart validation checks."""

    def test_empty_bars_incomplete(self):
        valid, issues, code = validate_chart_context([], now=datetime.now(timezone.utc))
        assert not valid
        assert code == RejectCode.BLOCKED_CHART_CONTEXT_INCOMPLETE

    def test_stale_bars_rejected(self):
        """Bars older than threshold should trigger STALE."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        candles = _candles(10, start=old_time - timedelta(minutes=15))
        enriched = enrich_bars(candles)
        valid, issues, code = validate_chart_context(
            enriched, now=datetime.now(timezone.utc), stale_threshold_sec=60.0,
        )
        assert not valid
        assert code == RejectCode.BLOCKED_CHART_CONTEXT_STALE

    def test_fresh_bars_valid(self):
        """Recent bars should pass validation."""
        now = datetime.now(timezone.utc)
        candles = _candles(30, start=now - timedelta(minutes=31))
        enriched = enrich_bars(candles)
        valid, issues, code = validate_chart_context(
            enriched, now=now, stale_threshold_sec=120.0,
        )
        assert valid
        assert code is None

    def test_non_monotonic_rejected(self):
        """Timestamps out of order should trigger TIME_MISMATCH."""
        from app.core.timezone import dual_timestamp
        now = datetime.now(timezone.utc)
        bars = [
            {"timestamp_et": dual_timestamp(now - timedelta(minutes=2))["timestamp_et"],
             "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
            {"timestamp_et": dual_timestamp(now - timedelta(minutes=3))["timestamp_et"],
             "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ]
        valid, issues, code = validate_chart_context(bars, now=now, stale_threshold_sec=300)
        assert not valid
        assert code == RejectCode.BLOCKED_CHART_CONTEXT_TIME_MISMATCH

    def test_null_critical_fields_incomplete(self):
        """Null OHLCV in recent bars should trigger INCOMPLETE."""
        from app.core.timezone import dual_timestamp
        now = datetime.now(timezone.utc)
        bars = [
            {"timestamp_et": dual_timestamp(now - timedelta(minutes=1))["timestamp_et"],
             "open": None, "high": 101, "low": 99, "close": 100.5, "volume": 1000},
        ]
        valid, issues, code = validate_chart_context(bars, now=now, stale_threshold_sec=300)
        assert not valid
        assert code == RejectCode.BLOCKED_CHART_CONTEXT_INCOMPLETE


class TestChartSerializer:
    """Chart serialization and compression."""

    def test_full_bars_under_threshold(self):
        candles = _candles(50)
        enriched = enrich_bars(candles)
        bars, method = serialize_chart(enriched, max_full_bars=390)
        assert method == ChartCompressionMethod.FULL
        assert len(bars) == 50

    def test_compression_when_over_threshold(self):
        """When bars exceed threshold, should use tiered compression."""
        candles = _candles(200)
        enriched = enrich_bars(candles)
        bars, method = serialize_chart(enriched, max_full_bars=100)
        assert method == ChartCompressionMethod.TIERED_90M
        # Should have fewer bars than original.
        assert len(bars) < 200
        # Last 90 should be full.
        assert len(bars) >= 90

    def test_compression_deterministic(self):
        """Same input → same output."""
        candles = _candles(200)
        enriched = enrich_bars(candles)
        bars_a, method_a = serialize_chart(enriched, max_full_bars=100)
        bars_b, method_b = serialize_chart(enriched, max_full_bars=100)
        assert method_a == method_b
        assert len(bars_a) == len(bars_b)
        for a, b in zip(bars_a, bars_b):
            assert a["open"] == b["open"]
            assert a["close"] == b["close"]


class TestEnrichBars:
    """Per-bar indicator enrichment."""

    def test_enriched_fields(self):
        candles = _candles(30)
        enriched = enrich_bars(candles)
        assert len(enriched) == 30
        for bar in enriched:
            assert "timestamp_et" in bar
            assert "timestamp_gmt3" in bar
            assert "open" in bar
            assert "vwap" in bar

    def test_rsi_populated_after_warmup(self):
        candles = _candles(20)
        enriched = enrich_bars(candles)
        # RSI needs 14+1 bars to compute first value.
        assert enriched[14]["rsi_14"] is not None

    def test_atr_populated_after_warmup(self):
        candles = _candles(20)
        enriched = enrich_bars(candles)
        # ATR needs 14+1 bars.
        assert enriched[14]["atr_14"] is not None

    def test_vwap_populated_from_start(self):
        candles = _candles(5)
        enriched = enrich_bars(candles)
        assert enriched[0]["vwap"] is not None


class TestSessionSummary:
    """Session summary generation."""

    def test_summary_has_all_fields(self):
        candles = _candles(30)
        refs = ReferenceLevels(prev_close=99.5, premarket_high=100.5, premarket_low=99.0)
        quote = Quote(symbol="SPX", ts=datetime.now(timezone.utc), last=101.0, bid=100.9, ask=101.1)
        summary = serialize_session_summary(candles, refs, quote, fs=None)
        expected_fields = [
            "current_price", "prior_close", "day_open", "day_high", "day_low",
            "vwap", "ema_10", "ema_20", "current_range_position", "market_state_hint",
            "last_completed_bar_time_et", "last_completed_bar_time_gmt3",
        ]
        for field in expected_fields:
            assert field in summary, f"missing field: {field}"

    def test_summary_dual_timestamps(self):
        candles = _candles(10)
        summary = serialize_session_summary(candles, None, None, None)
        assert summary["last_completed_bar_time_et"] is not None
        assert summary["last_completed_bar_time_gmt3"] is not None
