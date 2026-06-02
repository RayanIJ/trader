"""Macro-event guard.

Blocks new entries inside a window around high-impact events (CPI, FOMC, NFP,
…) and — for the scalping rules — signals that open positions should be flattened
*before* an event rather than held through it.

v1 uses a manually-maintained calendar (persisted in the ``macro_events`` table,
editable via the API). The architecture allows swapping in a real economic-calendar
feed later without touching callers: they only depend on :meth:`MacroGuard.status`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config.schema import MacroConfig
from app.core.enums import RejectCode


@dataclass(frozen=True)
class MacroEventDTO:
    name: str
    event_time: datetime          # timezone-aware UTC
    impact: str = "HIGH"
    block_minutes_before: int | None = None
    block_minutes_after: int | None = None


@dataclass
class MacroStatus:
    blocked: bool
    reason: str | None
    active_event: str | None
    next_event: str | None
    next_event_time: str | None
    minutes_to_next: float | None
    should_exit_open: bool        # flatten open positions before the upcoming event

    def to_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "reason": self.reason,
            "active_event": self.active_event,
            "next_event": self.next_event,
            "next_event_time": self.next_event_time,
            "minutes_to_next": self.minutes_to_next,
            "should_exit_open": self.should_exit_open,
        }


class MacroGuard:
    def __init__(self, cfg: MacroConfig) -> None:
        self._cfg = cfg
        self._events: list[MacroEventDTO] = []

    def set_events(self, events: list[MacroEventDTO]) -> None:
        self._events = sorted(events, key=lambda e: e.event_time)

    @property
    def events(self) -> list[MacroEventDTO]:
        return list(self._events)

    def _window(self, e: MacroEventDTO) -> tuple[datetime, datetime]:
        before = e.block_minutes_before if e.block_minutes_before is not None else self._cfg.block_minutes_before
        after = e.block_minutes_after if e.block_minutes_after is not None else self._cfg.block_minutes_after
        return e.event_time - timedelta(minutes=before), e.event_time + timedelta(minutes=after)

    def status(self, now: datetime | None = None) -> MacroStatus:
        now = now or datetime.now(timezone.utc)
        if not self._cfg.enabled or not self._events:
            return MacroStatus(False, None, None, None, None, None, False)

        active: MacroEventDTO | None = None
        for e in self._events:
            start, end = self._window(e)
            if start <= now <= end:
                active = e
                break

        upcoming = [e for e in self._events if e.event_time >= now]
        nxt = upcoming[0] if upcoming else None
        minutes_to_next = ((nxt.event_time - now).total_seconds() / 60.0) if nxt else None

        should_exit = False
        if self._cfg.exit_before_event and nxt is not None and minutes_to_next is not None:
            should_exit = 0 <= minutes_to_next <= self._cfg.exit_before_event_minutes

        return MacroStatus(
            blocked=active is not None,
            reason=(f"within macro block window for {active.name}" if active else None),
            active_event=active.name if active else None,
            next_event=nxt.name if nxt else None,
            next_event_time=nxt.event_time.isoformat() if nxt else None,
            minutes_to_next=round(minutes_to_next, 1) if minutes_to_next is not None else None,
            should_exit_open=should_exit,
        )

    def is_blocked(self, now: datetime | None = None) -> bool:
        return self.status(now).blocked

    def reject_code(self) -> RejectCode:
        return RejectCode.BLOCKED_MACRO_EVENT
