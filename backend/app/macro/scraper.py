"""Investing.com economic calendar scraper.

Hybrid approach:
1. Try internal API endpoint (fastest, structured JSON)
2. Fall back to HTML scraping (BeautifulSoup)
3. Fall back to empty result with error logged

Rate-limited: max 1 request per 30 seconds, cached for 4 hours.
US-only: filters to country=5 (United States).
"""
from __future__ import annotations

import asyncio
import random
import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.core.logging import get_logger
from app.core.timezone import ET, RIYADH, dual_timestamp

logger = get_logger("macro_scraper")

# Rotating user agents to reduce fingerprinting.
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

# Known high-impact US macro events for normalization.
_KNOWN_EVENTS = {
    "cpi", "ppi", "nfp", "non-farm", "nonfarm", "fomc",
    "jobless claims", "initial claims", "continuing claims",
    "pmi", "ism", "gdp", "retail sales", "durable goods",
    "existing home", "new home", "housing starts", "building permits",
    "consumer confidence", "michigan", "treasury", "fed",
    "core cpi", "core ppi", "core pce", "pce price",
    "empire state", "philly fed", "industrial production",
    "trade balance", "jolts",
}


class ScraperError(Exception):
    """General scraper failure."""


class CloudflareBlockError(ScraperError):
    """Cloudflare challenge detected."""


class RateLimitError(ScraperError):
    """Rate limit exceeded."""


@dataclass
class RawCalendarEvent:
    """Raw scraped event before normalization."""
    event_id: str
    name: str
    time_str: str | None  # raw time string like "08:30"
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None
    importance: int = 1  # 1=low, 2=medium, 3=high
    country: str = "US"
    currency: str = "USD"


class InvestingCalendarScraper:
    """Scrapes Investing.com economic calendar for US macro events.

    Uses a hybrid approach: internal API first, HTML fallback second.
    Rate-limited and cached.
    """

    BASE_URL = "https://www.investing.com/economic-calendar/"
    API_URL = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"

    # Rate limiting.
    MIN_REQUEST_INTERVAL = 30.0   # seconds between requests
    MAX_REQUESTS_PER_HOUR = 5

    # Cache TTL.
    CACHE_TTL_SECONDS = 4 * 3600  # 4 hours

    def __init__(self) -> None:
        self._last_request_ts: float = 0.0
        self._request_count_hour: int = 0
        self._hour_start: float = 0.0
        self._cache: dict[str, tuple[float, list[RawCalendarEvent]]] = {}
        self._client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=2),
        )

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(_USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": "https://www.investing.com/economic-calendar/",
            "Connection": "keep-alive",
            "DNT": "1",
        }

    def _api_headers(self) -> dict[str, str]:
        h = self._headers()
        h.update({
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json, text/javascript, */*; q=0.01",
        })
        return h

    async def _enforce_rate_limit(self) -> None:
        now = time.monotonic()

        # Reset hourly counter.
        if now - self._hour_start > 3600:
            self._hour_start = now
            self._request_count_hour = 0

        if self._request_count_hour >= self.MAX_REQUESTS_PER_HOUR:
            raise RateLimitError(
                f"hourly limit reached ({self.MAX_REQUESTS_PER_HOUR} requests/hour)"
            )

        elapsed = now - self._last_request_ts
        if elapsed < self.MIN_REQUEST_INTERVAL:
            wait = self.MIN_REQUEST_INTERVAL - elapsed + random.uniform(1, 3)
            logger.debug("rate limit: waiting %.1fs", wait)
            await asyncio.sleep(wait)

        self._last_request_ts = time.monotonic()
        self._request_count_hour += 1

    def _cache_key(self, d: date) -> str:
        return d.isoformat()

    def _get_cached(self, d: date) -> list[RawCalendarEvent] | None:
        key = self._cache_key(d)
        if key in self._cache:
            ts, events = self._cache[key]
            if time.time() - ts < self.CACHE_TTL_SECONDS:
                logger.debug("cache hit for %s (%d events)", key, len(events))
                return events
            del self._cache[key]
        return None

    def _set_cache(self, d: date, events: list[RawCalendarEvent]) -> None:
        self._cache[self._cache_key(d)] = (time.time(), events)

    async def fetch(self, d: date | None = None) -> list[RawCalendarEvent]:
        """Fetch today's US macro calendar. Hybrid: API → HTML → error."""
        d = d or date.today()

        cached = self._get_cached(d)
        if cached is not None:
            return cached

        events: list[RawCalendarEvent] = []
        try:
            events = await self._fetch_via_api(d)
            logger.info("API scrape OK: %d US events for %s", len(events), d)
        except CloudflareBlockError:
            logger.warning("API blocked by Cloudflare, trying HTML fallback")
            try:
                events = await self._fetch_via_html(d)
                logger.info("HTML scrape OK: %d US events for %s", len(events), d)
            except Exception as exc:
                logger.error("HTML scrape also failed: %s", exc)
                raise ScraperError(f"all scraping methods failed for {d}") from exc
        except Exception as exc:
            logger.warning("API scrape failed (%s), trying HTML fallback", exc)
            try:
                events = await self._fetch_via_html(d)
                logger.info("HTML scrape OK: %d US events for %s", len(events), d)
            except Exception as exc2:
                logger.error("HTML scrape also failed: %s", exc2)
                raise ScraperError(f"all scraping methods failed for {d}") from exc2

        self._set_cache(d, events)
        return events

    async def _fetch_via_api(self, d: date) -> list[RawCalendarEvent]:
        """POST to Investing.com internal API."""
        await self._enforce_rate_limit()

        date_from = d.strftime("%Y-%m-%d")
        date_to = d.strftime("%Y-%m-%d")

        data = {
            "country[]": "5",       # US
            "importance[]": "3",    # High impact (also fetch 2 for medium)
            "dateFrom": date_from,
            "dateTo": date_to,
            "timeZone": "8",        # Eastern Time
            "timeFilter": "timeRemain",
            "currentTab": "today",
            "limit_from": "0",
        }
        # Also fetch medium importance.
        data_list = [
            ("country[]", "5"),
            ("importance[]", "2"),
            ("importance[]", "3"),
            ("dateFrom", date_from),
            ("dateTo", date_to),
            ("timeZone", "8"),
            ("timeFilter", "timeRemain"),
            ("currentTab", "today"),
            ("limit_from", "0"),
        ]

        resp = await self._client.post(
            self.API_URL,
            data=data_list,
            headers=self._api_headers(),
        )

        if resp.status_code == 403:
            raise CloudflareBlockError("403 Forbidden — Cloudflare challenge")
        if resp.status_code == 503:
            raise CloudflareBlockError("503 — likely Cloudflare")
        resp.raise_for_status()

        body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
        if body is None:
            # Response might be HTML (Cloudflare challenge page).
            if "cf-" in resp.text.lower() or "cloudflare" in resp.text.lower():
                raise CloudflareBlockError("Cloudflare challenge in response body")
            # Try to parse as HTML table.
            return self._parse_html_table(resp.text, d)

        # Parse JSON response.
        html_content = body.get("data", "")
        if not html_content:
            return []

        return self._parse_html_table(html_content, d)

    async def _fetch_via_html(self, d: date) -> list[RawCalendarEvent]:
        """GET the calendar page and parse the HTML table."""
        await self._enforce_rate_limit()

        # Add random delay to look more human.
        await asyncio.sleep(random.uniform(2.0, 5.0))

        resp = await self._client.get(
            self.BASE_URL,
            headers=self._headers(),
        )

        if resp.status_code == 403 or resp.status_code == 503:
            raise CloudflareBlockError(f"HTTP {resp.status_code}")
        resp.raise_for_status()

        if "cf-" in resp.text[:2000].lower():
            raise CloudflareBlockError("Cloudflare challenge detected in page")

        return self._parse_html_table(resp.text, d)

    def _parse_html_table(self, html: str, d: date) -> list[RawCalendarEvent]:
        """Parse the economic calendar HTML table into raw events."""
        soup = BeautifulSoup(html, "lxml")
        events: list[RawCalendarEvent] = []

        # Investing.com uses <tr> rows with class "js-event-item".
        rows = soup.find_all("tr", class_=re.compile(r"js-event-item"))
        if not rows:
            # Alternative: look for data rows in a table.
            rows = soup.find_all("tr", attrs={"data-event-datetime": True})

        for row in rows:
            try:
                event = self._parse_row(row, d)
                if event and event.country == "US":
                    events.append(event)
            except Exception as exc:
                logger.debug("skipping row: %s", exc)
                continue

        return events

    def _parse_row(self, row, d: date) -> RawCalendarEvent | None:
        """Parse a single <tr> row into a RawCalendarEvent."""
        # Extract country flag.
        flag = row.find("td", class_=re.compile(r"flag"))
        if flag:
            flag_span = flag.find("span")
            if flag_span:
                flag_class = " ".join(flag_span.get("class", []))
                if "us" not in flag_class.lower() and "unitedstates" not in flag_class.lower().replace(" ", ""):
                    return None

        # Extract event ID.
        event_id = row.get("data-event-datetime", "") or row.get("id", "")
        if not event_id:
            event_id = f"unknown_{random.randint(1000, 9999)}"

        # Extract event name.
        name_td = row.find("td", class_=re.compile(r"event"))
        if not name_td:
            name_td = row.find("td", class_=re.compile(r"left"))
        name = name_td.get_text(strip=True) if name_td else None
        if not name:
            return None

        # Extract time.
        time_td = row.find("td", class_=re.compile(r"time"))
        time_str = time_td.get_text(strip=True) if time_td else None

        # Extract importance (bull icons count).
        impact_td = row.find("td", class_=re.compile(r"sentiment|impact"))
        importance = 1
        if impact_td:
            bulls = impact_td.find_all("i", class_=re.compile(r"bull"))
            if not bulls:
                bulls = impact_td.find_all("span", class_=re.compile(r"bull"))
            importance = len(bulls) if bulls else 1
            # Also check for grayFullBullishIcon vs fullBullishIcon count.
            icons_str = str(impact_td)
            importance = max(importance, icons_str.count("grayFullBullishIcon") + icons_str.count("greenFullBullishIcon"))
            if importance == 0:
                importance = 1

        # Extract actual/forecast/previous.
        cells = row.find_all("td")
        actual = forecast = previous = None
        for cell in cells:
            cell_id = cell.get("id", "") or ""
            cell_class = " ".join(cell.get("class", []))
            text = cell.get_text(strip=True)
            if "actual" in cell_id.lower() or "act" in cell_class.lower():
                actual = text if text and text != "\xa0" else None
            elif "forecast" in cell_id.lower() or "fore" in cell_class.lower():
                forecast = text if text and text != "\xa0" else None
            elif "previous" in cell_id.lower() or "prev" in cell_class.lower():
                previous = text if text and text != "\xa0" else None

        return RawCalendarEvent(
            event_id=str(event_id),
            name=name,
            time_str=time_str,
            actual=actual,
            forecast=forecast,
            previous=previous,
            importance=min(importance, 3),
            country="US",
        )

    async def close(self) -> None:
        await self._client.aclose()


def normalize_event_name(name: str) -> str:
    """Normalize event name for consistent matching."""
    name = name.strip()
    # Remove common suffixes.
    for suffix in (" (MoM)", " (YoY)", " (QoQ)", " (Prel)", " (Rev)", " (Final)"):
        name = name.replace(suffix, "")
    return name.strip()


def importance_to_str(importance: int) -> str:
    if importance >= 3:
        return "high"
    if importance >= 2:
        return "medium"
    return "low"


def parse_time_to_et(time_str: str | None, d: date) -> datetime | None:
    """Parse a time string like '08:30' into an ET-aware datetime."""
    if not time_str:
        return None
    time_str = time_str.strip()
    match = re.match(r"(\d{1,2}):(\d{2})", time_str)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    return datetime(d.year, d.month, d.day, hour, minute, 0, tzinfo=ET)
