"""Option chain filtering + contract selection tests."""
from datetime import datetime, timezone

from app.config.schema import OptionFilterConfig, RiskConfig
from app.core.enums import Direction, OptionRight, RejectCode
from app.market_data.models import OptionChain, OptionContractSpec, OptionQuote
from app.options.chain_builder import evaluate_contract, select_contract

TODAY = "20260602"
NEXT = "20260603"


def _q(strike, right, bid, ask, *, expiry=TODAY, mult=100.0, vol=1000, oi=5000, delta=0.5):
    return OptionQuote(
        spec=OptionContractSpec(underlying="NVDA", expiry=expiry, strike=strike, right=right, multiplier=mult),
        ts=datetime.now(timezone.utc),
        bid=bid, ask=ask, last=(bid + ask) / 2,
        volume=vol, open_interest=oi, delta=delta,
    )


def _opts(**over):
    return OptionFilterConfig(**over)


def _risk(**over):
    return RiskConfig(**over)


def test_premium_cap_uses_multiplier():
    # ask 2.50 x100 = $250 > $200 cap -> blocked.
    ev = evaluate_contract(_q(100, OptionRight.CALL, 2.40, 2.50), spot=100, options_cfg=_opts(), risk_cfg=_risk())
    assert RejectCode.BLOCKED_CONTRACT_ABOVE_MAX_PRICE in ev.reject_codes
    # ask 2.00 x100 = $200 -> allowed.
    ev2 = evaluate_contract(_q(100, OptionRight.CALL, 1.95, 2.00), spot=100, options_cfg=_opts(), risk_cfg=_risk())
    assert RejectCode.BLOCKED_CONTRACT_ABOVE_MAX_PRICE not in ev2.reject_codes


def test_missing_multiplier_blocks():
    ev = evaluate_contract(_q(100, OptionRight.CALL, 1.0, 1.1, mult=None), spot=100, options_cfg=_opts(), risk_cfg=_risk())
    assert RejectCode.BLOCKED_MISSING_MULTIPLIER in ev.reject_codes
    assert not ev.passed


def test_wide_spread_blocked():
    # bid 1.00 / ask 1.40 -> mid 1.20, spread 0.40 -> 33% > 12% cap.
    ev = evaluate_contract(_q(100, OptionRight.CALL, 1.00, 1.40), spot=100, options_cfg=_opts(), risk_cfg=_risk())
    assert RejectCode.BLOCKED_WIDE_SPREAD in ev.reject_codes


def test_low_liquidity_blocked():
    ev = evaluate_contract(
        _q(100, OptionRight.CALL, 1.00, 1.05, vol=1, oi=1),
        spot=100, options_cfg=_opts(min_option_volume=50, min_open_interest=100), risk_cfg=_risk(),
    )
    assert RejectCode.BLOCKED_LOW_VOLUME in ev.reject_codes


def test_select_prefers_zero_dte_and_nearest_atm():
    quotes = [
        _q(95, OptionRight.CALL, 1.00, 1.05, delta=0.65),
        _q(100, OptionRight.CALL, 1.00, 1.05, delta=0.50),
        _q(105, OptionRight.CALL, 0.50, 0.55, delta=0.35),
        _q(100, OptionRight.CALL, 1.00, 1.05, expiry=NEXT, delta=0.50),
    ]
    chain = OptionChain(underlying="NVDA", asof=datetime.now(timezone.utc), expiries=[TODAY, NEXT], quotes=quotes)
    sel = select_contract(chain, Direction.CALL, spot=100.0, options_cfg=_opts(), risk_cfg=_risk(), today_yyyymmdd=TODAY)
    assert sel.has_zero_dte
    assert sel.chosen is not None
    # ATM (strike 100) on the 0DTE expiry should win.
    assert sel.chosen.quote.spec.strike == 100
    assert sel.chosen.quote.spec.expiry == TODAY


def test_select_no_expiry_returns_reject():
    chain = OptionChain(underlying="NVDA", asof=datetime.now(timezone.utc), expiries=[], quotes=[])
    sel = select_contract(chain, Direction.CALL, spot=100.0, options_cfg=_opts(), risk_cfg=_risk(), today_yyyymmdd=TODAY)
    assert sel.chosen is None
    assert RejectCode.BLOCKED_NO_0DTE_EXPIRY in sel.reject_codes


def test_select_falls_back_to_near_expiry_when_no_zero_dte():
    quotes = [_q(100, OptionRight.PUT, 1.00, 1.05, expiry=NEXT, delta=-0.5)]
    chain = OptionChain(underlying="NVDA", asof=datetime.now(timezone.utc), expiries=[NEXT], quotes=quotes)
    sel = select_contract(chain, Direction.PUT, spot=100.0, options_cfg=_opts(), risk_cfg=_risk(), today_yyyymmdd=TODAY)
    assert not sel.has_zero_dte
    assert sel.chosen is not None
    assert sel.chosen.quote.spec.expiry == NEXT
