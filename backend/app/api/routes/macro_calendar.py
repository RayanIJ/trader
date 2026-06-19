"""Macro calendar API routes."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.logging import get_logger
from app.core.timezone import dual_timestamp

router = APIRouter(prefix="/api/macro", tags=["macro"])
logger = get_logger("api.macro_calendar")


@router.get("/calendar")
async def get_calendar():
    """Return today's full macro calendar."""
    from app.runtime import get_runtime

    rt = get_runtime()
    monitor = getattr(rt, "release_monitor", None)
    if monitor is None or monitor.calendar is None:
        return {"date_et": None, "date_gmt3": None, "events": []}

    cal = monitor.calendar
    return {
        "date_et": cal.date_et,
        "date_gmt3": cal.date_gmt3,
        "events": [e.model_dump() for e in cal.events],
    }


@router.get("/releases")
async def get_releases():
    """Return release updates for today."""
    from app.runtime import get_runtime

    rt = get_runtime()
    monitor = getattr(rt, "release_monitor", None)
    if monitor is None:
        return {"updates": []}

    updates = monitor.release_updates
    return {
        "updates": [u.model_dump() for u in updates.values()],
    }


@router.get("/next-event")
async def get_next_event():
    """Return the next upcoming macro event with countdown."""
    from datetime import datetime, timezone
    from app.runtime import get_runtime

    rt = get_runtime()
    now = datetime.now(timezone.utc)
    macro_status = rt.macro_guard.status(now)

    ts = dual_timestamp(now)
    return {
        "current_time_et": ts["timestamp_et"],
        "current_time_gmt3": ts["timestamp_gmt3"],
        "blocked": macro_status.blocked,
        "block_type": macro_status.block_type,
        "active_event": macro_status.active_event,
        "next_event": macro_status.next_event,
        "next_event_time": macro_status.next_event_time,
        "minutes_to_next": macro_status.minutes_to_next,
        "should_exit_open": macro_status.should_exit_open,
    }


@router.post("/calendar/refresh")
async def refresh_calendar():
    """Force re-fetch the daily calendar."""
    from app.runtime import get_runtime

    rt = get_runtime()
    provider = getattr(rt, "calendar_provider", None)
    if provider is None:
        return {"ok": False, "reason": "calendar provider not initialized"}

    cal = await provider.fetch_daily()
    monitor = getattr(rt, "release_monitor", None)
    if monitor:
        monitor.set_calendar(cal)

    # Also refresh the macro guard.
    from app.macro.store import refresh_guard
    refresh_guard(rt.macro_guard)

    return {
        "ok": True,
        "event_count": len(cal.events),
        "date_et": cal.date_et,
    }
