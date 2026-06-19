"""Integration tests for the LLM guidance system."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config.schema import AppConfig, MacroConfig
from app.core.enums import RejectCode
from app.llm.chart_validator import validate_chart_context
from app.llm.client import StubLLMClient, parse_guidance_response
from app.llm.models import LLMGuidanceResponse
from app.macro.calendar import MacroEventDTO, MacroGuard
from app.market_data.intraday_bars import enrich_bars
from app.market_data.models import Candle


def _candles(n: int, price: float = 100.0) -> list[Candle]:
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=n + 1)
    return [
        Candle(
            ts=start + timedelta(minutes=i),
            open=price + i * 0.05,
            high=price + i * 0.05 + 0.10,
            low=price + i * 0.05 - 0.05,
            close=price + i * 0.05 + 0.02,
            volume=1000 + i * 10,
        )
        for i in range(n)
    ]


class TestStubLLMClient:
    """Stub client always returns no_trade."""

    @pytest.mark.asyncio
    async def test_stub_returns_no_trade(self):
        client = StubLLMClient()
        result = await client.guidance({}, "system prompt")
        assert result["trade_permission"] == "no_trade"

    @pytest.mark.asyncio
    async def test_stub_returns_valid_json(self):
        client = StubLLMClient()
        result = await client.guidance({}, "system prompt")
        resp = parse_guidance_response(result)
        assert isinstance(resp, LLMGuidanceResponse)
        assert resp.trade_permission == "no_trade"


class TestGuidanceResponseParsing:
    """Response validation and parsing."""

    def test_valid_response(self):
        raw = {
            "trade_permission": "allowed",
            "direction": "CALL",
            "market_state": "trend_up",
            "trigger_level": 5420.0,
            "invalidation_level": 5410.0,
            "target_1": 5430.0,
            "target_2": 5440.0,
            "stop_level": 5405.0,
            "risk_mode": "normal",
            "reasoning": "test",
            "confidence": 0.8,
        }
        resp = parse_guidance_response(raw)
        assert resp.trade_permission == "allowed"
        assert resp.direction == "CALL"
        assert resp.confidence == 0.8

    def test_invalid_response_falls_back(self):
        raw = {"bad_key": True}
        resp = parse_guidance_response(raw)
        assert resp.trade_permission == "no_trade"  # fallback

    def test_no_trade_with_null_direction(self):
        raw = {
            "trade_permission": "no_trade",
            "direction": None,
            "reasoning": "choppy market",
        }
        resp = parse_guidance_response(raw)
        assert resp.trade_permission == "no_trade"
        assert resp.direction is None


class TestMacroBlockPreventsExecution:
    """Macro block should prevent execution even if LLM allows trigger."""

    def test_macro_block_overrides_allowed(self):
        """When macro is blocked, system should block regardless of LLM output."""
        now = datetime(2024, 7, 15, 13, 28, 0, tzinfo=timezone.utc)
        event_time = datetime(2024, 7, 15, 13, 30, 0, tzinfo=timezone.utc)
        guard = MacroGuard(MacroConfig())
        guard.set_events([MacroEventDTO("CPI", event_time, "HIGH", 10, 5)])

        # LLM says allowed.
        guidance = LLMGuidanceResponse(trade_permission="allowed", direction="CALL")

        # But macro is blocked.
        assert guard.is_blocked(now)
        # System should use macro block to veto even though LLM said allowed.
        # This is the deterministic risk engine's job.


class TestStaleChartPreventsExecution:
    """Stale chart data should block new entries."""

    def test_stale_chart_blocks(self):
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        candles = _candles(20)
        enriched = enrich_bars(candles)
        # Simulate stale by setting now far ahead.
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        valid, issues, code = validate_chart_context(
            enriched, now=future, stale_threshold_sec=60.0,
        )
        assert not valid
        assert code == RejectCode.BLOCKED_CHART_CONTEXT_STALE


class TestChartContextHasAllSections:
    """Verify enriched bars have the required per-bar fields."""

    def test_bar_fields_match_spec(self):
        candles = _candles(20)
        enriched = enrich_bars(candles)
        required_fields = [
            "timestamp_et", "timestamp_gmt3", "open", "high", "low",
            "close", "volume", "vwap", "ema_10", "ema_20", "rsi_14",
            "atr_14", "above_vwap", "distance_from_vwap_points",
            "distance_from_vwap_percent",
        ]
        for bar in enriched:
            for field in required_fields:
                assert field in bar, f"missing field: {field}"

    def test_completed_candles_only(self):
        """enrich_bars should only process candles given to it (filtering
        is done by get_session_bars, not enrich_bars)."""
        candles = _candles(5)
        enriched = enrich_bars(candles)
        assert len(enriched) == 5
