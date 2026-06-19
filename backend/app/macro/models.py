"""Pydantic models for the enhanced macro calendar system."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class MacroCalendarEvent(BaseModel):
    """Full macro event with dual timestamps and release data."""
    event_id: str
    name: str
    country: str = "US"
    importance: str = "high"
    release_time_et: Optional[str] = None
    release_time_gmt3: Optional[str] = None
    release_time_utc: Optional[datetime] = None
    source: str = "configured_provider"
    consensus: Optional[Any] = None
    prior: Optional[Any] = None
    actual: Optional[Any] = None
    status: str = "scheduled"
    trading_block_before_minutes: int = 3
    trading_block_after_minutes: int = 3
    requires_release_update: bool = True


class MacroReleaseUpdate(BaseModel):
    """Release result with economic interpretations."""
    event_id: str
    name: str
    release_time_et: Optional[str] = None
    release_time_gmt3: Optional[str] = None
    actual: Optional[Any] = None
    consensus: Optional[Any] = None
    prior: Optional[Any] = None
    revision: Optional[Any] = None
    surprise_direction: str = "unknown"
    risk_asset_interpretation: str = "unknown"
    rates_interpretation: str = "unknown"
    volatility_interpretation: str = "unknown"
    source: str = "configured_provider"
    fetched_at_et: Optional[str] = None
    fetched_at_gmt3: Optional[str] = None
    status: str = "released"
    # SPX reaction data.
    spx_1m_change_pct: Optional[float] = None
    spx_3m_change_pct: Optional[float] = None
    spx_5m_change_pct: Optional[float] = None
    price_action: Optional[str] = None


class MacroCalendarDay(BaseModel):
    """A day's full calendar."""
    date_gmt3: str
    date_et: str
    events: list[MacroCalendarEvent] = Field(default_factory=list)
    fetched_at: Optional[datetime] = None
    provider: str = "database"


class MacroDailyRequest(BaseModel):
    """Log of when the calendar was fetched."""
    date: str
    provider: str
    event_count: int
    fetched_at: datetime
