"""All 17 persisted entities.

These mirror the domain objects flowing through the pipeline: instruments and
contracts, point-in-time market/option data, signals and their features, trade
candidates, the order/fill/position/exit lifecycle, risk and macro events,
health events, config versions, the journal, and daily summaries.

JSON columns store flexible payloads (feature vectors, reason-code lists, raw
broker messages) without prematurely normalizing the schema in the MVP.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PKMixin, TimestampMixin, utcnow


class Instrument(Base, PKMixin, TimestampMixin):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(16), index=True, unique=True)
    sec_type: Mapped[str] = mapped_column(String(8), default="STK")
    con_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    multiplier: Mapped[float] = mapped_column(Float, default=1.0)
    exchange: Mapped[str | None] = mapped_column(String(16), nullable=True)
    role: Mapped[str] = mapped_column(String(24), default="tradable")  # tradable/confirmation
    is_approved: Mapped[bool] = mapped_column(Boolean, default=True)


class OptionContract(Base, PKMixin, TimestampMixin):
    __tablename__ = "option_contracts"

    con_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    expiry: Mapped[str] = mapped_column(String(8))           # YYYYMMDD
    strike: Mapped[float] = mapped_column(Float)
    right: Mapped[str] = mapped_column(String(1))            # C / P
    multiplier: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_zero_dte: Mapped[bool] = mapped_column(Boolean, default=False)


class MarketSnapshot(Base, PKMixin):
    __tablename__ = "market_snapshots"

    symbol: Mapped[str] = mapped_column(String(16), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    vwap: Mapped[float | None] = mapped_column(Float, nullable=True)
    opening_range_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    opening_range_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    premarket_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    premarket_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    relative_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    data_feed_status: Mapped[str | None] = mapped_column(String(16), nullable=True)


class OptionQuote(Base, PKMixin):
    __tablename__ = "option_quotes"

    option_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("option_contracts.id"), nullable=True, index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    last: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_interest: Mapped[float | None] = mapped_column(Float, nullable=True)
    iv: Mapped[float | None] = mapped_column(Float, nullable=True)
    delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    gamma: Mapped[float | None] = mapped_column(Float, nullable=True)
    theta: Mapped[float | None] = mapped_column(Float, nullable=True)
    vega: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_stale: Mapped[bool] = mapped_column(Boolean, default=False)


class Signal(Base, PKMixin):
    __tablename__ = "signals"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    setup_type: Mapped[str] = mapped_column(String(32))
    direction: Mapped[str] = mapped_column(String(4))       # CALL / PUT
    score: Mapped[float] = mapped_column(Float, default=0.0)
    band: Mapped[str] = mapped_column(String(16), default="NO_TRADE")
    status: Mapped[str] = mapped_column(String(16), default="GENERATED")
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(8), default="SHADOW")


class SignalFeature(Base, PKMixin):
    __tablename__ = "signal_features"

    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    features: Mapped[dict] = mapped_column(JSON, default=dict)  # full feature vector


class TradeCandidate(Base, PKMixin):
    __tablename__ = "trade_candidates"

    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"), nullable=True, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    direction: Mapped[str] = mapped_column(String(4))
    option_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("option_contracts.id"), nullable=True
    )
    premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    spread_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    sized_contracts: Mapped[int] = mapped_column(Integer, default=0)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    reject_codes: Mapped[list] = mapped_column(JSON, default=list)


class OrderRecord(Base, PKMixin):
    __tablename__ = "orders"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    candidate_id: Mapped[int | None] = mapped_column(
        ForeignKey("trade_candidates.id"), nullable=True, index=True
    )
    broker_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    direction: Mapped[str] = mapped_column(String(4))
    side: Mapped[str] = mapped_column(String(16), default="BUY_TO_OPEN")
    order_type: Mapped[str] = mapped_column(String(16), default="LMT")
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(24), default="CANDIDATE")
    mode: Mapped[str] = mapped_column(String(8), default="SHADOW")
    message: Mapped[str | None] = mapped_column(Text, nullable=True)


class Fill(Base, PKMixin):
    __tablename__ = "fills"

    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    slippage: Mapped[float | None] = mapped_column(Float, nullable=True)


class PositionRecord(Base, PKMixin):
    __tablename__ = "positions"

    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    underlying: Mapped[str] = mapped_column(String(16), index=True)
    option_contract_id: Mapped[int | None] = mapped_column(
        ForeignKey("option_contracts.id"), nullable=True
    )
    direction: Mapped[str] = mapped_column(String(4))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN")
    mode: Mapped[str] = mapped_column(String(8), default="SHADOW")


class ExitRecord(Base, PKMixin):
    __tablename__ = "exits"

    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    reason: Mapped[str] = mapped_column(String(32))
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_in_trade_sec: Mapped[float | None] = mapped_column(Float, nullable=True)


class RiskEvent(Base, PKMixin):
    __tablename__ = "risk_events"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    lockout: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class MacroEvent(Base, PKMixin, TimestampMixin):
    __tablename__ = "macro_events"

    name: Mapped[str] = mapped_column(String(48), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    impact: Mapped[str] = mapped_column(String(16), default="HIGH")
    block_minutes_before: Mapped[int] = mapped_column(Integer, default=10)
    block_minutes_after: Mapped[int] = mapped_column(Integer, default=5)
    source: Mapped[str] = mapped_column(String(32), default="manual")
    # Enhanced fields for the macro calendar system.
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    consensus: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prior: Mapped[str | None] = mapped_column(String(32), nullable=True)
    actual: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str | None] = mapped_column(String(16), nullable=True, default="scheduled")
    country: Mapped[str | None] = mapped_column(String(8), nullable=True, default="US")
    importance: Mapped[str | None] = mapped_column(String(8), nullable=True)


class SystemHealthEvent(Base, PKMixin):
    __tablename__ = "system_health_events"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    component: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class ConfigurationVersion(Base, PKMixin):
    __tablename__ = "configuration_versions"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    version_hash: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class JournalEntry(Base, PKMixin):
    __tablename__ = "journal_entries"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # SIGNAL/ORDER/FILL/EXIT/RULE/...
    symbol: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    mode: Mapped[str] = mapped_column(String(8), default="SHADOW")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class DailySummary(Base, PKMixin):
    __tablename__ = "daily_summaries"

    trade_date: Mapped[str] = mapped_column(String(10), index=True, unique=True)  # YYYY-MM-DD
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    trades: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    lockouts: Mapped[int] = mapped_column(Integer, default=0)
    top_rejections: Mapped[dict] = mapped_column(JSON, default=dict)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# LLM + macro calendar persistence tables
# ---------------------------------------------------------------------------

class MacroCalendarRequest(Base, PKMixin):
    """Log of daily macro calendar fetches."""
    __tablename__ = "macro_calendar_requests"

    date: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    provider: Mapped[str] = mapped_column(String(32), default="database")
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class MacroReleaseUpdateRecord(Base, PKMixin):
    """Per-event release results with economic interpretations."""
    __tablename__ = "macro_release_updates"

    event_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(48))
    release_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual: Mapped[str | None] = mapped_column(String(32), nullable=True)
    consensus: Mapped[str | None] = mapped_column(String(32), nullable=True)
    prior: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    surprise_direction: Mapped[str | None] = mapped_column(String(16), nullable=True)
    risk_asset_interpretation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    rates_interpretation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    volatility_interpretation: Mapped[str | None] = mapped_column(String(16), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="configured_provider")
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(16), default="released")
    reaction_data: Mapped[dict] = mapped_column(JSON, default=dict)


class LLMGuidanceRequestRecord(Base, PKMixin):
    """Full LLM guidance request metadata and chart snapshot."""
    __tablename__ = "llm_guidance_requests"

    request_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    chart_bars_count: Mapped[int] = mapped_column(Integer, default=0)
    compression_method: Mapped[str] = mapped_column(String(16), default="full")
    chart_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    macro_events_count: Mapped[int] = mapped_column(Integer, default=0)
    trading_mode: Mapped[str] = mapped_column(String(8), default="SHADOW")
    session_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    chart_issues: Mapped[list] = mapped_column(JSON, default=list)


class LLMGuidanceResponseRecord(Base, PKMixin):
    """LLM guidance output."""
    __tablename__ = "llm_guidance_responses"

    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("llm_guidance_requests.id"), nullable=True, index=True
    )
    response_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    validation_status: Mapped[str] = mapped_column(String(16), default="valid")
    trade_permission: Mapped[str] = mapped_column(String(16), default="no_trade")
    direction: Mapped[str | None] = mapped_column(String(4), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    risk_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

