"""Release monitor — tracks scheduled releases and fetches updates.

At release_time + 0 minutes: marks as RELEASE_WINDOW.
At release_time + 1 minute: first fetch of actual result.
At release_time + 3 minutes: retry if no actual.
At release_time + 5 minutes: final retry → DELAYED or UNAVAILABLE.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.enums import MacroEventStatus
from app.core.logging import get_logger
from app.core.timezone import dual_timestamp, to_et, to_utc
from app.macro.models import MacroCalendarDay, MacroCalendarEvent, MacroReleaseUpdate

logger = get_logger("release_monitor")

# Default delays (minutes after release time) for update attempts.
DEFAULT_UPDATE_DELAYS = [1, 3, 5]


class ReleaseMonitor:
    """Monitors scheduled macro releases and manages update cycles."""

    def __init__(
        self,
        update_delays: list[int] | None = None,
    ) -> None:
        self._update_delays = update_delays or DEFAULT_UPDATE_DELAYS
        self._calendar: MacroCalendarDay | None = None
        self._release_updates: dict[str, MacroReleaseUpdate] = {}
        self._attempted: dict[str, list[int]] = {}  # event_id -> list of attempted delays

    def set_calendar(self, calendar: MacroCalendarDay) -> None:
        """Set today's calendar for monitoring."""
        self._calendar = calendar
        logger.info("release monitor loaded %d events", len(calendar.events))

    @property
    def calendar(self) -> MacroCalendarDay | None:
        return self._calendar

    @property
    def release_updates(self) -> dict[str, MacroReleaseUpdate]:
        return dict(self._release_updates)

    def get_events_needing_update(self, now: datetime | None = None) -> list[tuple[MacroCalendarEvent, int]]:
        """Return events that need a release update fetch, with the delay minute.

        Each item is (event, delay_minutes) where delay_minutes is 1, 3, or 5.
        """
        now = now or datetime.now(timezone.utc)
        if not self._calendar:
            return []

        results: list[tuple[MacroCalendarEvent, int]] = []
        for event in self._calendar.events:
            if not event.requires_release_update:
                continue
            if not event.release_time_utc:
                continue

            # Skip if already fully resolved.
            existing = self._release_updates.get(event.event_id)
            if existing and existing.status in ("released", "unavailable"):
                continue

            elapsed_min = (now - event.release_time_utc).total_seconds() / 60.0
            if elapsed_min < 0:
                # Not yet released.
                continue

            # Check which delays we should attempt.
            attempted = self._attempted.get(event.event_id, [])
            for delay in self._update_delays:
                if delay in attempted:
                    continue
                if elapsed_min >= delay:
                    results.append((event, delay))
                    break  # Only the next un-attempted delay.

        return results

    def mark_release_window(self, event: MacroCalendarEvent, now: datetime | None = None) -> None:
        """Mark an event as being in the release window (release_time + 0)."""
        now = now or datetime.now(timezone.utc)
        if event.release_time_utc and (now - event.release_time_utc).total_seconds() >= 0:
            event.status = MacroEventStatus.RELEASE_WINDOW.value
            logger.info("event %s entered release window", event.event_id)

    def record_update(
        self,
        event: MacroCalendarEvent,
        delay_min: int,
        *,
        actual: Any = None,
        consensus: Any = None,
        prior: Any = None,
        revision: Any = None,
        surprise_direction: str = "unknown",
        risk_asset_interpretation: str = "unknown",
        rates_interpretation: str = "unknown",
        volatility_interpretation: str = "unknown",
    ) -> MacroReleaseUpdate:
        """Record a release update fetch result."""
        now = datetime.now(timezone.utc)
        ts = dual_timestamp(now)

        # Track attempt.
        self._attempted.setdefault(event.event_id, []).append(delay_min)

        if actual is not None:
            status = "released"
            event.actual = actual
            event.status = MacroEventStatus.RELEASED.value
        elif delay_min >= max(self._update_delays):
            status = "unavailable" if actual is None else "delayed"
            event.status = MacroEventStatus.UNAVAILABLE.value
        else:
            status = "delayed"
            event.status = MacroEventStatus.DELAYED.value

        release_ts = dual_timestamp(event.release_time_utc) if event.release_time_utc else {}

        update = MacroReleaseUpdate(
            event_id=event.event_id,
            name=event.name,
            release_time_et=release_ts.get("timestamp_et"),
            release_time_gmt3=release_ts.get("timestamp_gmt3"),
            actual=actual,
            consensus=consensus or event.consensus,
            prior=prior or event.prior,
            revision=revision,
            surprise_direction=surprise_direction,
            risk_asset_interpretation=risk_asset_interpretation,
            rates_interpretation=rates_interpretation,
            volatility_interpretation=volatility_interpretation,
            source="configured_provider",
            fetched_at_et=ts["timestamp_et"],
            fetched_at_gmt3=ts["timestamp_gmt3"],
            status=status,
        )

        self._release_updates[event.event_id] = update
        logger.info(
            "release update for %s delay=%dmin status=%s actual=%s",
            event.event_id, delay_min, status, actual,
        )
        return update

    def get_latest_released(self) -> MacroReleaseUpdate | None:
        """Return the most recently released event update."""
        released = [u for u in self._release_updates.values() if u.status == "released"]
        if not released:
            return None
        return released[-1]

    def check_release_windows(self, now: datetime | None = None) -> None:
        """Mark any events that have entered their release window."""
        now = now or datetime.now(timezone.utc)
        if not self._calendar:
            return
        for event in self._calendar.events:
            if event.status == "scheduled" and event.release_time_utc:
                if (now - event.release_time_utc).total_seconds() >= 0:
                    self.mark_release_window(event, now)
