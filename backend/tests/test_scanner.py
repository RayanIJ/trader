"""Scanner engine + scoring tests (offline, simulated source)."""
from datetime import datetime, timezone

import pytest

from app.config.manager import ConfigManager
from app.market_data.simulated import SimulatedMarketDataSource
from app.scanner.engine import ScannerEngine
from app.scanner.scoring import time_of_day_points

pytestmark = pytest.mark.asyncio


def _engine(seed=1337):
    cfg = ConfigManager().config
    return ScannerEngine(cfg, SimulatedMarketDataSource(seed=seed)), cfg


async def test_time_of_day_outside_rth_is_zero():
    # 03:00 UTC = 23:00 prev-day NY -> closed.
    assert time_of_day_points(datetime(2026, 6, 2, 3, 0, tzinfo=timezone.utc)) == 0.0


async def test_time_of_day_prime_morning_full_points():
    # 14:00 UTC = 10:00 NY -> prime AM momentum window.
    assert time_of_day_points(datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc)) == 5.0


async def test_time_of_day_midday_lull_reduced():
    # 16:30 UTC = 12:30 NY -> lull -> half points.
    assert time_of_day_points(datetime(2026, 6, 2, 16, 30, tzinfo=timezone.utc)) == 2.5


async def test_scan_produces_candidates_for_tradable_universe():
    eng, cfg = _engine()
    res = await eng.scan(now=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc))
    assert res.source == "simulated"
    assert res.regime.overall in ("RISK_ON", "RISK_OFF", "MIXED")
    syms = {c.symbol for c in res.candidates}
    # Candidates only ever come from the tradable universe.
    assert syms.issubset(set(cfg.universe.all_tradable))
    assert len(res.candidates) > 0


async def test_candidate_invariants():
    eng, _ = _engine()
    res = await eng.scan(now=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc))
    for c in res.candidates:
        assert c.direction in ("CALL", "PUT")
        assert 0.0 <= c.score <= 100.0
        # Scanner-level tradable: contract selected and scanner gates passed.
        if c.tradable:
            assert c.contract is not None
        # Fully approved candidates pass signal + risk with no reject codes.
        if c.approved:
            assert c.reject_codes == []
        # Non-tradable candidates always explain why at scanner level.
        if not c.tradable:
            assert c.reject_codes


async def test_scan_is_deterministic_for_seed():
    eng_a, _ = _engine(seed=2024)
    eng_b, _ = _engine(seed=2024)
    now = datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc)
    a = await eng_a.scan(now=now)
    b = await eng_b.scan(now=now)
    sa = {(c.symbol, c.direction): c.score for c in a.candidates}
    sb = {(c.symbol, c.direction): c.score for c in b.candidates}
    assert sa == sb


async def test_to_dict_shape():
    eng, _ = _engine()
    d = (await eng.scan(now=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc))).to_dict()
    assert {"asof", "source", "regime", "candidates", "top_calls", "top_puts"} <= set(d)
    assert isinstance(d["top_calls"], list)
    assert "overall" in d["regime"]
