"""Pydantic models for the LLM guidance subsystem.

These define the strict schema for LLM guidance requests and responses.
The LLM must output JSON matching ``LLMGuidanceResponse``.
"""
from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class ChartBar(BaseModel):
    """Single 1-minute bar in the LLM chart context."""
    timestamp_et: str
    timestamp_gmt3: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: Optional[float] = None
    ema_10: Optional[float] = None
    ema_20: Optional[float] = None
    rsi_14: Optional[float] = None
    atr_14: Optional[float] = None
    above_vwap: Optional[bool] = None
    distance_from_vwap_points: Optional[float] = None
    distance_from_vwap_percent: Optional[float] = None
    bar_type: Optional[str] = None  # "5min_compressed" or "1min_tail" when compressed


class SessionSummary(BaseModel):
    current_price: Optional[float] = None
    prior_close: Optional[float] = None
    day_open: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    premarket_high: Optional[float] = None
    premarket_low: Optional[float] = None
    opening_range_high: Optional[float] = None
    opening_range_low: Optional[float] = None
    vwap: Optional[float] = None
    ema_10: Optional[float] = None
    ema_20: Optional[float] = None
    rsi_14: Optional[float] = None
    trend_slope: Optional[float] = None
    vwap_cross_count: int = 0
    current_range_position: str = "mid_range"
    market_state_hint: str = "range"
    last_completed_bar_time_et: Optional[str] = None
    last_completed_bar_time_gmt3: Optional[str] = None


class MacroEventPayload(BaseModel):
    event_id: str
    name: str
    country: str = "US"
    importance: str = "high"
    release_time_et: Optional[str] = None
    release_time_gmt3: Optional[str] = None
    source: str = "configured_provider"
    consensus: Optional[Any] = None
    prior: Optional[Any] = None
    actual: Optional[Any] = None
    status: str = "scheduled"
    trading_block_before_minutes: int = 3
    trading_block_after_minutes: int = 3
    requires_release_update: bool = True


class ReleaseReactionSummary(BaseModel):
    event_id: Optional[str] = None
    event_name: Optional[str] = None
    spx_1m_change_pct: Optional[float] = None
    spx_3m_change_pct: Optional[float] = None
    spx_5m_change_pct: Optional[float] = None
    price_action: Optional[str] = None  # reclaimed / rejected / broke_down / chopped
    surprise_direction: Optional[str] = None
    risk_asset_interpretation: Optional[str] = None
    rates_interpretation: Optional[str] = None
    volatility_interpretation: Optional[str] = None


class MacroContextPayload(BaseModel):
    todays_events: List[MacroEventPayload] = Field(default_factory=list)
    next_event: Optional[MacroEventPayload] = None
    active_macro_block: bool = False
    latest_released_event: Optional[MacroEventPayload] = None
    release_reaction_summary: Optional[ReleaseReactionSummary] = None


class RiskContextPayload(BaseModel):
    daily_realized_pnl: float = 0.0
    peak_daily_pnl: float = 0.0
    giveback_from_peak: float = 0.0
    round_trips_used: int = 0
    max_round_trips: int = 5
    losing_trades_used: int = 0
    max_losing_trades: int = 2
    current_open_position: Optional[dict] = None
    current_system_mode: str = "normal"


class RequestMetadata(BaseModel):
    request_time_et: str
    request_time_gmt3: str
    guidance_valid_for_seconds: int = 300
    market: str = "SPX"
    trading_mode: str = "shadow"


class LLMGuidanceRequest(BaseModel):
    """Full LLM guidance request payload."""
    request_metadata: RequestMetadata
    session_summary: SessionSummary
    one_minute_chart: List[dict] = Field(default_factory=list)
    macro_context: MacroContextPayload = Field(default_factory=MacroContextPayload)
    risk_context: RiskContextPayload = Field(default_factory=RiskContextPayload)
    chart_valid: bool = True
    chart_issues: List[str] = Field(default_factory=list)
    compression_method: str = "full"
    bar_count: int = 0


class LLMGuidanceResponse(BaseModel):
    """Expected strict JSON output from the LLM."""
    trade_permission: str = "no_trade"  # allowed | no_trade | exit_only | blocked
    direction: Optional[str] = None  # CALL | PUT | None
    market_state: Optional[str] = None
    trigger_level: Optional[float] = None
    invalidation_level: Optional[float] = None
    target_1: Optional[float] = None
    target_2: Optional[float] = None
    stop_level: Optional[float] = None
    risk_mode: Optional[str] = None  # normal | protect_day | blocked | exit_only
    reasoning: Optional[str] = None
    confidence: Optional[float] = None  # 0..1
    raw: Optional[dict] = None  # original LLM output if parsing succeeded
