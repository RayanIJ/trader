"""Macro-specific timezone helpers.

Delegates to ``app.core.timezone`` for the actual conversions. Provides
convenience functions specific to macro event handling.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.timezone import dual_timestamp, to_et, to_riyadh, validate_timezone_offset
from app.macro.calendar import MacroEventDTO


def event_to_dual_tz(event: MacroEventDTO) -> dict:
    """Convert a MacroEventDTO into a dict with both ET and GMT+3 timestamps."""
    ts = dual_timestamp(event.event_time)
    return {
        "name": event.name,
        "impact": event.impact,
        "event_time_et": ts["timestamp_et"],
        "event_time_gmt3": ts["timestamp_gmt3"],
        "block_minutes_before": event.block_minutes_before,
        "block_minutes_after": event.block_minutes_after,
    }


def is_within_block_window(
    event: MacroEventDTO,
    now: datetime,
) -> tuple[bool, str | None]:
    """Check if *now* is within the macro block window of *event*.

    Returns ``(blocked, reason)`` where reason is ``'pre_release'`` or
    ``'post_release'`` or ``None``.
    """
    diff_sec = (now - event.event_time).total_seconds()
    before_sec = (event.block_minutes_before or 3) * 60
    after_sec = (event.block_minutes_after or 3) * 60

    if -before_sec <= diff_sec < 0:
        return True, "pre_release"
    if 0 <= diff_sec <= after_sec:
        return True, "post_release"
    return False, None
