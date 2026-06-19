"""Load and persist macro calendar events."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.db.models import MacroEvent
from app.db.session import get_session
from app.macro.calendar import MacroEventDTO, MacroGuard


def load_events(
    *,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
) -> list[MacroEventDTO]:
    now = datetime.now(timezone.utc)
    from_ts = from_ts or (now - timedelta(days=1))
    to_ts = to_ts or (now + timedelta(days=30))
    with get_session() as s:
        rows = (
            s.query(MacroEvent)
            .filter(MacroEvent.event_time >= from_ts, MacroEvent.event_time <= to_ts)
            .order_by(MacroEvent.event_time.asc())
            .all()
        )
        return [
            MacroEventDTO(
                name=r.name,
                event_time=r.event_time,
                impact=r.impact,
                block_minutes_before=r.block_minutes_before,
                block_minutes_after=r.block_minutes_after,
            )
            for r in rows
        ]


def refresh_guard(guard: MacroGuard) -> int:
    events = load_events()
    guard.set_events(events)
    return len(events)


def add_event(
    *,
    name: str,
    event_time: datetime,
    impact: str = "HIGH",
    block_minutes_before: int | None = None,
    block_minutes_after: int | None = None,
    source: str = "manual",
) -> dict:
    if event_time.tzinfo is None:
        event_time = event_time.replace(tzinfo=timezone.utc)
    with get_session() as s:
        event_id = f"{name}_{event_time.strftime('%Y%m%d_%H%M')}"
        row = MacroEvent(
            name=name,
            event_time=event_time,
            impact=impact,
            block_minutes_before=block_minutes_before if block_minutes_before is not None else 10,
            block_minutes_after=block_minutes_after if block_minutes_after is not None else 5,
            source=source,
            event_id=event_id,
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        return {
            "id": row.id,
            "name": row.name,
            "event_time": row.event_time.isoformat(),
            "impact": row.impact,
            "block_minutes_before": row.block_minutes_before,
            "block_minutes_after": row.block_minutes_after,
            "source": row.source,
        }


def list_events(limit: int = 20) -> list[dict]:
    now = datetime.now(timezone.utc)
    with get_session() as s:
        rows = (
            s.query(MacroEvent)
            .filter(MacroEvent.event_time >= now - timedelta(days=1))
            .order_by(MacroEvent.event_time.asc())
            .limit(limit)
            .all()
        )
        return [
            {
                "id": r.id,
                "name": r.name,
                "event_time": r.event_time.isoformat(),
                "impact": r.impact,
                "block_minutes_before": r.block_minutes_before,
                "block_minutes_after": r.block_minutes_after,
                "source": r.source,
            }
            for r in rows
        ]
