"""Phase 6 journal + backtest tests."""
from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.config.manager import ConfigManager
from app.journal.service import JournalService
from app.journal.summary import build_daily_summary, get_daily_summary
from app.backtest.engine import BacktestEngine
from app.db.session import init_db


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    init_db(tmp_path)
    return tmp_path


def test_journal_record_and_recent(data_dir: Path) -> None:
    journal = JournalService(mode_fn=lambda: "SHADOW")
    entry = journal.record("TEST", {"foo": "bar"}, symbol="NVDA")
    assert entry["kind"] == "TEST"
    assert entry["symbol"] == "NVDA"
    rows = journal.recent(limit=10, kind="TEST")
    assert len(rows) == 1
    assert rows[0]["payload"]["foo"] == "bar"


@pytest.mark.asyncio
async def test_journal_record_async(data_dir: Path) -> None:
    journal = JournalService(mode_fn=lambda: "SHADOW")
    entry = await journal.record_async("SIGNAL", {"score": 72.0}, symbol="SPY")
    assert entry["kind"] == "SIGNAL"
    assert journal.recent(limit=1)[0]["id"] == entry["id"]


def test_daily_summary_from_exits(data_dir: Path) -> None:
    journal = JournalService(mode_fn=lambda: "SHADOW")
    trade_date = "2026-06-02"
    journal.record(
        "EXIT",
        {"realized_pnl": 25.0, "reason": "PROFIT_TARGET"},
        symbol="NVDA",
    )
    journal.record(
        "EXIT",
        {"realized_pnl": -15.0, "reason": "STOP_LOSS"},
        symbol="AMD",
    )
    journal.record(
        "REJECT",
        {"reject_codes": ["PREMIUM_TOO_HIGH", "CHOP_HIGH"]},
        symbol="SMCI",
    )
    summary = build_daily_summary(trade_date)
    assert summary["realized_pnl"] == 10.0
    assert summary["trades"] == 2
    assert summary["rejected"] == 1
    cached = get_daily_summary(trade_date)
    assert cached is not None
    assert cached["realized_pnl"] == 10.0


@pytest.mark.asyncio
async def test_backtest_engine_runs() -> None:
    cfg = ConfigManager().config
    engine = BacktestEngine(cfg)
    result = await engine.run(seed=42, steps=6, interval_minutes=5)
    assert result.steps == 6
    assert result.total_candidates >= 0
    d = result.to_dict()
    assert "approval_rate" in d
    assert isinstance(d["top_symbols"], list)
