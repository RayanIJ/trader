"""Deterministic simulated market-data source tests."""
import pytest

from app.core.enums import OptionRight
from app.market_data.simulated import SimulatedMarketDataSource

pytestmark = pytest.mark.asyncio


async def test_candles_are_deterministic_for_a_seed():
    a = SimulatedMarketDataSource(seed=1337)
    b = SimulatedMarketDataSource(seed=1337)
    ca = await a.get_candles_1m("NVDA", 60)
    cb = await b.get_candles_1m("NVDA", 60)
    assert len(ca) == len(cb) == 60
    assert [c.close for c in ca] == [c.close for c in cb]


async def test_candles_ohlc_consistency():
    src = SimulatedMarketDataSource(seed=42)
    for sym in ("SPX", "NVDA", "AMD"):
        for c in await src.get_candles_1m(sym, 40):
            assert c.high >= max(c.open, c.close)
            assert c.low <= min(c.open, c.close)
            assert c.volume > 0


async def test_quote_two_sided_and_live():
    src = SimulatedMarketDataSource()
    q = await src.get_quote("NVDA")
    assert q is not None
    assert q.has_two_sided()
    assert q.ask >= q.bid
    assert q.feed.value == "LIVE"


async def test_option_chain_has_today_expiry_and_both_rights():
    from datetime import datetime, timezone

    src = SimulatedMarketDataSource()
    chain = await src.get_option_chain("NVDA", spot=120.0)
    assert chain is not None
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    assert chain.has_zero_dte(today)
    rights = {q.spec.right for q in chain.quotes}
    assert rights == {OptionRight.CALL, OptionRight.PUT}
    # Every quote is two-sided with a 100 multiplier.
    for q in chain.quotes:
        assert q.spec.multiplier == 100.0
        assert q.has_two_sided()
