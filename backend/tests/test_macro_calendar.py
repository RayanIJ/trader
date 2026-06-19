"""Tests for the macro calendar system."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config.schema import MacroConfig
from app.core.enums import RejectCode
from app.macro.calendar import MacroEventDTO, MacroGuard
from app.macro.calendar_provider import StaticMacroProvider
from app.macro.models import MacroCalendarDay, MacroCalendarEvent
from app.macro.release_monitor import ReleaseMonitor


class TestMacroGuardBlockTypes:
    """MacroGuard should distinguish pre_release vs post_release."""

    def _guard(self, **kw) -> MacroGuard:
        return MacroGuard(MacroConfig(**kw))

    def test_pre_release_block(self):
        now = datetime(2024, 7, 15, 13, 25, 0, tzinfo=timezone.utc)
        event_time = datetime(2024, 7, 15, 13, 30, 0, tzinfo=timezone.utc)
        guard = self._guard()
        guard.set_events([MacroEventDTO("CPI", event_time, "HIGH", 10, 5)])
        status = guard.status(now)
        assert status.blocked
        assert status.block_type == "pre_release"
        assert guard.reject_code(now) == RejectCode.BLOCKED_MACRO_PRE_RELEASE

    def test_post_release_block(self):
        now = datetime(2024, 7, 15, 13, 32, 0, tzinfo=timezone.utc)
        event_time = datetime(2024, 7, 15, 13, 30, 0, tzinfo=timezone.utc)
        guard = self._guard()
        guard.set_events([MacroEventDTO("CPI", event_time, "HIGH", 10, 5)])
        status = guard.status(now)
        assert status.blocked
        assert status.block_type == "post_release"
        assert guard.reject_code(now) == RejectCode.BLOCKED_MACRO_POST_RELEASE

    def test_not_blocked_outside_window(self):
        now = datetime(2024, 7, 15, 14, 0, 0, tzinfo=timezone.utc)
        event_time = datetime(2024, 7, 15, 13, 30, 0, tzinfo=timezone.utc)
        guard = self._guard()
        guard.set_events([MacroEventDTO("CPI", event_time, "HIGH", 10, 5)])
        status = guard.status(now)
        assert not status.blocked
        assert status.block_type is None


class TestMacroCalendarProvider:
    """StaticMacroProvider returns configured events."""

    @pytest.mark.asyncio
    async def test_static_provider_returns_events(self):
        events = [
            MacroCalendarEvent(
                event_id="CPI_0830",
                name="CPI",
                importance="high",
                status="scheduled",
            ),
        ]
        provider = StaticMacroProvider(events)
        cal = await provider.fetch_daily()
        assert len(cal.events) == 1
        assert cal.events[0].name == "CPI"

    @pytest.mark.asyncio
    async def test_static_provider_empty(self):
        provider = StaticMacroProvider([])
        cal = await provider.fetch_daily()
        assert len(cal.events) == 0


class TestReleaseMonitor:
    """Release monitor tracks events and manages update cycles."""

    def _monitor(self) -> ReleaseMonitor:
        return ReleaseMonitor(update_delays=[1, 3, 5])

    def _event(self, minutes_ago: float = 0.0) -> MacroCalendarEvent:
        now = datetime.now(timezone.utc)
        release = now - timedelta(minutes=minutes_ago)
        return MacroCalendarEvent(
            event_id="CPI_0830",
            name="CPI",
            importance="high",
            release_time_utc=release,
            status="scheduled",
        )

    def test_no_updates_before_release(self):
        monitor = self._monitor()
        event = self._event(minutes_ago=-10)  # 10 minutes in the future
        cal = MacroCalendarDay(
            date_et="2024-07-15",
            date_gmt3="2024-07-15",
            events=[event],
        )
        monitor.set_calendar(cal)
        assert len(monitor.get_events_needing_update()) == 0

    def test_update_at_1_minute(self):
        monitor = self._monitor()
        event = self._event(minutes_ago=1.5)  # 1.5 min after release
        cal = MacroCalendarDay(
            date_et="2024-07-15",
            date_gmt3="2024-07-15",
            events=[event],
        )
        monitor.set_calendar(cal)
        needing = monitor.get_events_needing_update()
        assert len(needing) == 1
        assert needing[0][1] == 1  # delay = 1 minute

    def test_update_at_3_minutes(self):
        monitor = self._monitor()
        event = self._event(minutes_ago=3.5)
        cal = MacroCalendarDay(
            date_et="2024-07-15",
            date_gmt3="2024-07-15",
            events=[event],
        )
        monitor.set_calendar(cal)
        # First fetch at delay=1.
        needing = monitor.get_events_needing_update()
        assert needing[0][1] == 1
        monitor.record_update(event, 1)
        # Second fetch at delay=3.
        needing = monitor.get_events_needing_update()
        assert len(needing) == 1
        assert needing[0][1] == 3

    def test_record_release(self):
        monitor = self._monitor()
        event = self._event(minutes_ago=2)
        update = monitor.record_update(event, 1, actual="3.1%")
        assert update.status == "released"
        assert update.actual == "3.1%"
        assert event.status == "released"

    def test_unavailable_after_final_retry(self):
        monitor = self._monitor()
        event = self._event(minutes_ago=6)
        monitor.record_update(event, 1)
        monitor.record_update(event, 3)
        update = monitor.record_update(event, 5)  # final retry, no actual
        assert update.status == "unavailable"
        assert event.status == "unavailable"

    def test_released_event_skipped(self):
        monitor = self._monitor()
        event = self._event(minutes_ago=2)
        cal = MacroCalendarDay(
            date_et="2024-07-15",
            date_gmt3="2024-07-15",
            events=[event],
        )
        monitor.set_calendar(cal)
        monitor.record_update(event, 1, actual="3.1%")
        # After release, no more updates needed.
        needing = monitor.get_events_needing_update()
        assert len(needing) == 0

    def test_get_latest_released(self):
        monitor = self._monitor()
        event = self._event(minutes_ago=2)
        monitor.record_update(event, 1, actual="3.1%")
        latest = monitor.get_latest_released()
        assert latest is not None
        assert latest.actual == "3.1%"
