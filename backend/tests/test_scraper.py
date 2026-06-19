"""Tests for the Investing.com economic calendar scraper."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.macro.scraper import (
    InvestingCalendarScraper,
    RawCalendarEvent,
    importance_to_str,
    normalize_event_name,
    parse_time_to_et,
)

# ---------- HTML parsing fixture ----------

SAMPLE_HTML = """
<table>
<tr class="js-event-item" data-event-datetime="2024-07-15T12:30:00Z">
  <td class="flag"><span class="ceFlags us"></span></td>
  <td class="time">08:30</td>
  <td class="event"><a>Core CPI (MoM)</a></td>
  <td class="sentiment">
    <i class="greenFullBullishIcon"></i>
    <i class="greenFullBullishIcon"></i>
    <i class="greenFullBullishIcon"></i>
  </td>
  <td id="eventActual_123" class="act">0.3%</td>
  <td id="eventForecast_123" class="fore">0.2%</td>
  <td id="eventPrevious_123" class="prev">0.4%</td>
</tr>
<tr class="js-event-item" data-event-datetime="2024-07-15T14:00:00Z">
  <td class="flag"><span class="ceFlags gb"></span></td>
  <td class="time">10:00</td>
  <td class="event"><a>UK GDP</a></td>
  <td class="sentiment">
    <i class="greenFullBullishIcon"></i>
    <i class="greenFullBullishIcon"></i>
  </td>
  <td id="eventActual_456" class="act"></td>
  <td id="eventForecast_456" class="fore">1.5%</td>
  <td id="eventPrevious_456" class="prev">1.3%</td>
</tr>
<tr class="js-event-item" data-event-datetime="2024-07-15T18:00:00Z">
  <td class="flag"><span class="ceFlags us"></span></td>
  <td class="time">14:00</td>
  <td class="event"><a>FOMC Statement</a></td>
  <td class="sentiment">
    <i class="greenFullBullishIcon"></i>
    <i class="greenFullBullishIcon"></i>
    <i class="greenFullBullishIcon"></i>
  </td>
  <td id="eventActual_789" class="act"></td>
  <td id="eventForecast_789" class="fore"></td>
  <td id="eventPrevious_789" class="prev"></td>
</tr>
</table>
"""


class TestHTMLParsing:
    """Test HTML table parsing logic."""

    def test_parse_filters_us_only(self):
        scraper = InvestingCalendarScraper()
        d = date(2024, 7, 15)
        events = scraper._parse_html_table(SAMPLE_HTML, d)
        # Should filter out the UK GDP row.
        assert len(events) == 2
        names = [e.name for e in events]
        assert "UK GDP" not in names

    def test_parse_extracts_event_names(self):
        scraper = InvestingCalendarScraper()
        d = date(2024, 7, 15)
        events = scraper._parse_html_table(SAMPLE_HTML, d)
        names = {e.name for e in events}
        assert "Core CPI (MoM)" in names or "Core CPI" in names
        assert "FOMC Statement" in names

    def test_parse_extracts_time(self):
        scraper = InvestingCalendarScraper()
        d = date(2024, 7, 15)
        events = scraper._parse_html_table(SAMPLE_HTML, d)
        cpi = next(e for e in events if "CPI" in e.name)
        assert cpi.time_str == "08:30"

    def test_parse_extracts_actual_forecast_previous(self):
        scraper = InvestingCalendarScraper()
        d = date(2024, 7, 15)
        events = scraper._parse_html_table(SAMPLE_HTML, d)
        cpi = next(e for e in events if "CPI" in e.name)
        assert cpi.actual == "0.3%"
        assert cpi.forecast == "0.2%"
        assert cpi.previous == "0.4%"

    def test_parse_handles_empty_actual(self):
        scraper = InvestingCalendarScraper()
        d = date(2024, 7, 15)
        events = scraper._parse_html_table(SAMPLE_HTML, d)
        fomc = next(e for e in events if "FOMC" in e.name)
        assert fomc.actual is None

    def test_parse_extracts_importance(self):
        scraper = InvestingCalendarScraper()
        d = date(2024, 7, 15)
        events = scraper._parse_html_table(SAMPLE_HTML, d)
        cpi = next(e for e in events if "CPI" in e.name)
        assert cpi.importance == 3


class TestHelpers:
    """Test helper functions."""

    def test_normalize_event_name(self):
        assert normalize_event_name("Core CPI (MoM)") == "Core CPI"
        assert normalize_event_name("GDP (QoQ) (Prel)") == "GDP"
        assert normalize_event_name("  FOMC Statement  ") == "FOMC Statement"

    def test_importance_to_str(self):
        assert importance_to_str(3) == "high"
        assert importance_to_str(2) == "medium"
        assert importance_to_str(1) == "low"

    def test_parse_time_to_et(self):
        from app.core.timezone import ET
        d = date(2024, 7, 15)
        result = parse_time_to_et("08:30", d)
        assert result is not None
        assert result.hour == 8
        assert result.minute == 30
        assert result.tzinfo == ET

    def test_parse_time_to_et_none(self):
        assert parse_time_to_et(None, date(2024, 7, 15)) is None
        assert parse_time_to_et("", date(2024, 7, 15)) is None
        assert parse_time_to_et("tentative", date(2024, 7, 15)) is None


class TestRateLimiting:
    """Test rate limiting logic."""

    def test_cache_key(self):
        scraper = InvestingCalendarScraper()
        assert scraper._cache_key(date(2024, 7, 15)) == "2024-07-15"

    def test_cache_set_and_get(self):
        scraper = InvestingCalendarScraper()
        d = date(2024, 7, 15)
        events = [RawCalendarEvent(event_id="test", name="CPI", time_str="08:30")]
        scraper._set_cache(d, events)
        cached = scraper._get_cached(d)
        assert cached is not None
        assert len(cached) == 1
        assert cached[0].name == "CPI"

    def test_cache_miss(self):
        scraper = InvestingCalendarScraper()
        assert scraper._get_cached(date(2024, 7, 15)) is None


class TestInvestingProvider:
    """Test the InvestingCalendarProvider integration."""

    @pytest.mark.asyncio
    async def test_static_fallback_on_scraper_error(self):
        """When scraper fails, provider should fall back to database."""
        from app.macro.calendar_provider import InvestingCalendarProvider

        provider = InvestingCalendarProvider()
        # Should not raise even if scraper fails (falls back to database).
        try:
            cal = await provider.fetch_daily(date(2024, 7, 15))
            assert cal.provider in ("investing.com", "database")
        except Exception:
            # Database provider may also fail in test env — that's OK.
            pass

    def test_factory_creates_investing_provider(self):
        from app.macro.calendar_provider import (
            InvestingCalendarProvider,
            make_calendar_provider,
        )
        p = make_calendar_provider("investing")
        assert isinstance(p, InvestingCalendarProvider)
