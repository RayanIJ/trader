"""Tests for macro guard block windows."""
from datetime import datetime, timedelta, timezone

from app.config.schema import MacroConfig
from app.macro.calendar import MacroEventDTO, MacroGuard


def test_macro_blocks_inside_window():
    cfg = MacroConfig(enabled=True, block_minutes_before=10, block_minutes_after=5)
    guard = MacroGuard(cfg)
    event_time = datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc)
    guard.set_events([MacroEventDTO(name="CPI", event_time=event_time)])
    inside = event_time - timedelta(minutes=5)
    assert guard.is_blocked(inside)
    st = guard.status(inside)
    assert st.blocked
    assert st.active_event == "CPI"


def test_macro_not_blocked_outside_window():
    cfg = MacroConfig(enabled=True, block_minutes_before=10, block_minutes_after=5)
    guard = MacroGuard(cfg)
    event_time = datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc)
    guard.set_events([MacroEventDTO(name="CPI", event_time=event_time)])
    outside = event_time - timedelta(minutes=20)
    assert not guard.is_blocked(outside)


def test_macro_exit_before_event_flag():
    cfg = MacroConfig(
        enabled=True, exit_before_event=True, exit_before_event_minutes=10,
        block_minutes_before=10, block_minutes_after=5,
    )
    guard = MacroGuard(cfg)
    event_time = datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc)
    guard.set_events([MacroEventDTO(name="FOMC", event_time=event_time)])
    inside = event_time - timedelta(minutes=8)
    st = guard.status(inside)
    assert st.should_exit_open
    assert st.blocked
    outside = event_time - timedelta(minutes=11)
    st2 = guard.status(outside)
    assert not st2.should_exit_open
    assert not st2.blocked
