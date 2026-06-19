"""Tests for the timezone module — DST-aware Riyadh ↔ New York conversions."""
from __future__ import annotations

from datetime import datetime, date, timezone, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.core.timezone import (
    ET,
    RIYADH,
    UTC,
    current_et_date,
    dual_timestamp,
    is_market_open,
    is_premarket,
    market_session_bounds,
    to_et,
    to_riyadh,
    to_utc,
    validate_timezone_offset,
)


class TestTimezoneConversions:
    """Verify no hardcoded +7 assumption — Riyadh offset changes with US DST."""

    def test_riyadh_to_ny_during_edt(self):
        """During EDT (UTC-4), Riyadh (UTC+3) is 7 hours ahead of NY."""
        # July 15 — firmly in EDT.
        riyadh_dt = datetime(2024, 7, 15, 17, 0, 0, tzinfo=RIYADH)  # 5 PM Riyadh
        ny_dt = to_et(riyadh_dt)
        assert ny_dt.hour == 10  # 10 AM ET
        # UTC offset difference: Riyadh=+3, EDT=-4 → gap=7.
        riyadh_offset = riyadh_dt.utcoffset().total_seconds() / 3600
        ny_offset = ny_dt.utcoffset().total_seconds() / 3600
        assert abs((riyadh_offset - ny_offset) - 7.0) < 0.01

    def test_riyadh_to_ny_during_est(self):
        """During EST (UTC-5), Riyadh (UTC+3) is 8 hours ahead of NY."""
        # January 15 — firmly in EST.
        riyadh_dt = datetime(2024, 1, 15, 18, 0, 0, tzinfo=RIYADH)  # 6 PM Riyadh
        ny_dt = to_et(riyadh_dt)
        assert ny_dt.hour == 10  # 10 AM ET
        # UTC offset difference: Riyadh=+3, EST=-5 → gap=8.
        riyadh_offset = riyadh_dt.utcoffset().total_seconds() / 3600
        ny_offset = ny_dt.utcoffset().total_seconds() / 3600
        assert abs((riyadh_offset - ny_offset) - 8.0) < 0.01

    def test_no_hardcoded_7(self):
        """The offset must not be a fixed 7 — EST and EDT produce different gaps."""
        edt_dt = datetime(2024, 7, 1, 12, 0, 0, tzinfo=RIYADH)
        est_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=RIYADH)
        edt_et = to_et(edt_dt)
        est_et = to_et(est_dt)
        offset_edt = RIYADH.utcoffset(edt_dt).total_seconds() - edt_et.utcoffset().total_seconds()
        offset_est = RIYADH.utcoffset(est_dt).total_seconds() - est_et.utcoffset().total_seconds()
        assert offset_edt != offset_est, "Offset should differ between EDT and EST"

    def test_dual_timestamp_produces_both(self):
        dt = datetime(2024, 7, 15, 14, 30, 0, tzinfo=UTC)
        ts = dual_timestamp(dt)
        assert "timestamp_et" in ts
        assert "timestamp_gmt3" in ts
        assert ts["timestamp_et"] != ts["timestamp_gmt3"]

    def test_dual_timestamp_same_instant(self):
        dt = datetime(2024, 7, 15, 14, 30, 0, tzinfo=UTC)
        ts = dual_timestamp(dt)
        et_dt = datetime.fromisoformat(ts["timestamp_et"])
        riyadh_dt = datetime.fromisoformat(ts["timestamp_gmt3"])
        assert validate_timezone_offset(et_dt, riyadh_dt)

    def test_validate_timezone_offset_correct(self):
        dt = datetime(2024, 7, 15, 14, 30, 0, tzinfo=UTC)
        assert validate_timezone_offset(to_et(dt), to_riyadh(dt))

    def test_validate_timezone_offset_wrong(self):
        """Different instants should fail validation."""
        dt1 = datetime(2024, 7, 15, 14, 30, 0, tzinfo=ET)
        dt2 = datetime(2024, 7, 15, 14, 35, 0, tzinfo=RIYADH)  # 5 min different
        assert not validate_timezone_offset(dt1, dt2)


class TestMarketSession:
    def test_market_open_weekday_regular_hours(self):
        # Wednesday at 10 AM ET.
        dt = datetime(2024, 7, 17, 10, 0, 0, tzinfo=ET)
        assert is_market_open(dt)

    def test_market_closed_weekend(self):
        # Saturday.
        dt = datetime(2024, 7, 20, 10, 0, 0, tzinfo=ET)
        assert not is_market_open(dt)

    def test_market_closed_after_hours(self):
        dt = datetime(2024, 7, 17, 17, 0, 0, tzinfo=ET)
        assert not is_market_open(dt)

    def test_premarket(self):
        dt = datetime(2024, 7, 17, 5, 0, 0, tzinfo=ET)
        assert is_premarket(dt)
        assert not is_market_open(dt)

    def test_session_bounds(self):
        d = date(2024, 7, 17)
        open_et, close_et = market_session_bounds(d)
        assert open_et.hour == 9 and open_et.minute == 30
        assert close_et.hour == 16 and close_et.minute == 0
