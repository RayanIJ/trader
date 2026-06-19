"""Timezone utilities — IANA-based, DST-aware.

Converts between America/New_York (market time) and Asia/Riyadh (user time).
Never hardcodes a fixed +7 hour offset; uses proper zoneinfo so EST/EDT
transitions are handled correctly.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone, timedelta
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RIYADH = ZoneInfo("Asia/Riyadh")
UTC = timezone.utc

# US equity regular session bounds (ET).
_MARKET_OPEN = time(9, 30)
_MARKET_CLOSE = time(16, 0)
_PREMARKET_OPEN = time(4, 0)


def to_et(dt: datetime) -> datetime:
    """Convert any timezone-aware datetime to America/New_York."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ET)


def to_riyadh(dt: datetime) -> datetime:
    """Convert any timezone-aware datetime to Asia/Riyadh (GMT+3)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(RIYADH)


def to_utc(dt: datetime) -> datetime:
    """Convert any datetime to UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def dual_timestamp(dt: datetime) -> dict[str, str]:
    """Return both ET and GMT+3 ISO-8601 strings for a single instant."""
    return {
        "timestamp_et": to_et(dt).isoformat(),
        "timestamp_gmt3": to_riyadh(dt).isoformat(),
    }


def market_session_bounds(d: date) -> tuple[datetime, datetime]:
    """Return (open_et, close_et) for the regular US equity session on *d*."""
    open_et = datetime.combine(d, _MARKET_OPEN, tzinfo=ET)
    close_et = datetime.combine(d, _MARKET_CLOSE, tzinfo=ET)
    return open_et, close_et


def premarket_open(d: date) -> datetime:
    """Pre-market open (4:00 AM ET) for date *d*."""
    return datetime.combine(d, _PREMARKET_OPEN, tzinfo=ET)


def is_market_open(dt: datetime | None = None) -> bool:
    """True if *dt* falls within regular session hours (9:30–16:00 ET)."""
    dt = dt or datetime.now(UTC)
    et = to_et(dt)
    # Weekday check: Mon=0 .. Fri=4.
    if et.weekday() >= 5:
        return False
    return _MARKET_OPEN <= et.time() < _MARKET_CLOSE


def is_premarket(dt: datetime | None = None) -> bool:
    """True if *dt* is in pre-market (4:00–9:30 ET) on a weekday."""
    dt = dt or datetime.now(UTC)
    et = to_et(dt)
    if et.weekday() >= 5:
        return False
    return _PREMARKET_OPEN <= et.time() < _MARKET_OPEN


def validate_timezone_offset(et_dt: datetime, riyadh_dt: datetime) -> bool:
    """Verify that the two datetimes represent the same instant.

    Returns False if they differ by more than 1 second, which would indicate
    a timezone conversion bug.
    """
    diff = abs((to_utc(et_dt) - to_utc(riyadh_dt)).total_seconds())
    return diff < 1.0


def current_et_date() -> date:
    """Today's date in ET (the trading calendar date)."""
    return to_et(datetime.now(UTC)).date()
