"""Trade persistence + macro store tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.config.manager import ConfigManager
from app.core.enums import Direction, OrderState
from app.execution.models import ActivePosition, OrderRequest, OrderResult
from app.macro.calendar import MacroGuard
from app.macro.store import add_event, load_events, refresh_guard
from app.persistence.trades import TradeStore
from app.db.models import ExitRecord, OrderRecord, PositionRecord
from app.db.session import get_session, init_db


@pytest.fixture
def data_dir(tmp_path):
    init_db(tmp_path)
    return tmp_path


def test_trade_store_entry_and_exit(data_dir) -> None:
    store = TradeStore(mode_fn=lambda: "SHADOW")
    order = OrderRequest(
        underlying="NVDA",
        expiry="20260602",
        strike=225.0,
        right="C",
        direction=Direction.CALL,
        quantity=1,
        limit_price=2.05,
        side="BUY_TO_OPEN",
    )
    result = OrderResult(None, OrderState.FILLED, 1, 2.0, "shadow fill")
    now = datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc)
    pos = ActivePosition(
        underlying="NVDA",
        expiry="20260602",
        strike=225.0,
        right="C",
        direction=Direction.CALL,
        quantity=1,
        entry_price=2.0,
        entry_ts=now,
        multiplier=100.0,
        stop_price=1.5,
        target_price=2.4,
        peak_premium=2.0,
        is_shadow=True,
    )
    order_id, position_id = store.record_entry(order, result, pos, shadow=True)
    assert order_id > 0
    assert position_id > 0

    exit_id = store.record_exit(pos, exit_price=2.2, realized_pnl=20.0, reason="PROFIT_TARGET")
    assert exit_id is not None

    with get_session() as s:
        assert s.query(OrderRecord).count() == 1
        assert s.query(PositionRecord).filter_by(status="CLOSED").count() == 1
        assert s.query(ExitRecord).count() == 1


def test_macro_store_load_and_refresh(data_dir) -> None:
    event_time = datetime(2026, 6, 2, 18, 30, tzinfo=timezone.utc)
    add_event(name="CPI", event_time=event_time)
    loaded = load_events()
    assert any(e.name == "CPI" for e in loaded)

    cfg = ConfigManager().config
    guard = MacroGuard(cfg.macro)
    count = refresh_guard(guard)
    assert count >= 1
    assert guard.events[0].name == "CPI"
