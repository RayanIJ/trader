"""Macro calendar provider interface and implementations.

Abstracts the source of daily economic calendar data. The database provider
reads from the existing ``macro_events`` table; the static provider reads from
a JSON config file for testing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, date, timezone
from typing import Any

from app.core.logging import get_logger
from app.core.timezone import dual_timestamp, to_et, current_et_date
from app.macro.models import MacroCalendarDay, MacroCalendarEvent

logger = get_logger("macro_provider")


class MacroCalendarProvider(ABC):
    """Abstract calendar provider."""

    @abstractmethod
    async def fetch_daily(self, d: date | None = None) -> MacroCalendarDay:
        """Fetch the macro calendar for a given date."""
        ...


class DatabaseMacroProvider(MacroCalendarProvider):
    """Reads events from the existing ``macro_events`` DB table."""

    async def fetch_daily(self, d: date | None = None) -> MacroCalendarDay:
        from app.macro.store import load_events
        from datetime import timedelta

        d = d or current_et_date()
        et_date_str = d.isoformat()

        # Load events for today +/- 1 day to catch timezone edge cases.
        from app.core.timezone import ET
        from datetime import datetime as _dt
        start = _dt.combine(d, _dt.min.time(), tzinfo=ET)
        end = start + timedelta(days=1)

        events = load_events(from_ts=start, to_ts=end)

        cal_events: list[MacroCalendarEvent] = []
        for e in events:
            ts = dual_timestamp(e.event_time)
            cal_events.append(MacroCalendarEvent(
                event_id=f"{e.name}_{e.event_time.strftime('%H%M')}",
                name=e.name,
                country="US",
                importance=e.impact.lower() if e.impact else "high",
                release_time_et=ts["timestamp_et"],
                release_time_gmt3=ts["timestamp_gmt3"],
                release_time_utc=e.event_time,
                source="database",
                trading_block_before_minutes=e.block_minutes_before or 3,
                trading_block_after_minutes=e.block_minutes_after or 3,
            ))

        from app.core.timezone import to_riyadh
        riyadh_now = to_riyadh(datetime.now(timezone.utc))
        return MacroCalendarDay(
            date_et=et_date_str,
            date_gmt3=riyadh_now.strftime("%Y-%m-%d"),
            events=cal_events,
            fetched_at=datetime.now(timezone.utc),
            provider="database",
        )


class StaticMacroProvider(MacroCalendarProvider):
    """Reads events from a list (for testing)."""

    def __init__(self, events: list[MacroCalendarEvent] | None = None) -> None:
        self._events = events or []

    async def fetch_daily(self, d: date | None = None) -> MacroCalendarDay:
        from app.core.timezone import to_riyadh
        d = d or current_et_date()
        riyadh_now = to_riyadh(datetime.now(timezone.utc))
        return MacroCalendarDay(
            date_et=d.isoformat(),
            date_gmt3=riyadh_now.strftime("%Y-%m-%d"),
            events=self._events,
            fetched_at=datetime.now(timezone.utc),
            provider="static",
        )


class InvestingCalendarProvider(MacroCalendarProvider):
    """Scrapes Investing.com for today's US macro calendar.

    Uses the hybrid scraper (API → HTML → error) with a 4-hour cache.
    Falls back to the database provider on scraper failure.
    """

    def __init__(self) -> None:
        from app.macro.scraper import InvestingCalendarScraper
        self._scraper = InvestingCalendarScraper()
        self._cache: MacroCalendarDay | None = None
        self._cache_date: date | None = None
        self._fallback = DatabaseMacroProvider()

    async def fetch_daily(self, d: date | None = None) -> MacroCalendarDay:
        from app.macro.scraper import (
            RawCalendarEvent as RawEvent,
            ScraperError,
            importance_to_str,
            normalize_event_name,
            parse_time_to_et,
        )
        from app.core.timezone import to_riyadh

        d = d or current_et_date()

        # Return cache if same date.
        if self._cache and self._cache_date == d:
            return self._cache

        try:
            raw_events = await self._scraper.fetch(d)
        except ScraperError as exc:
            logger.warning("scraper failed (%s), falling back to database provider", exc)
            return await self._fallback.fetch_daily(d)

        cal_events: list[MacroCalendarEvent] = []
        for raw in raw_events:
            release_et = parse_time_to_et(raw.time_str, d)
            ts = dual_timestamp(release_et) if release_et else {"timestamp_et": None, "timestamp_gmt3": None}

            status = "released" if raw.actual else "scheduled"
            event_id = f"{normalize_event_name(raw.name)}_{raw.time_str or 'ALLDAY'}".replace(" ", "_")

            cal_events.append(MacroCalendarEvent(
                event_id=event_id,
                name=normalize_event_name(raw.name),
                country="US",
                importance=importance_to_str(raw.importance),
                release_time_et=ts["timestamp_et"],
                release_time_gmt3=ts["timestamp_gmt3"],
                release_time_utc=release_et.astimezone(datetime.now(timezone.utc).tzinfo) if release_et else None,
                source="investing.com",
                consensus=raw.forecast,
                prior=raw.previous,
                actual=raw.actual,
                status=status,
                trading_block_before_minutes=3 if raw.importance < 3 else 5,
                trading_block_after_minutes=3 if raw.importance < 3 else 5,
                requires_release_update=raw.actual is None and release_et is not None,
            ))

        riyadh_now = to_riyadh(datetime.now(timezone.utc))
        cal = MacroCalendarDay(
            date_et=d.isoformat(),
            date_gmt3=riyadh_now.strftime("%Y-%m-%d"),
            events=cal_events,
            fetched_at=datetime.now(timezone.utc),
            provider="investing.com",
        )

        self._cache = cal
        self._cache_date = d
        logger.info(
            "investing.com calendar fetched: %d events for %s", len(cal_events), d,
        )
        return cal


def make_calendar_provider(provider: str = "database") -> MacroCalendarProvider:
    """Factory for macro calendar providers."""
    if provider == "database":
        return DatabaseMacroProvider()
    if provider == "static":
        return StaticMacroProvider()
    if provider == "investing":
        return InvestingCalendarProvider()
    logger.warning("unknown macro provider '%s', falling back to database", provider)
    return DatabaseMacroProvider()
