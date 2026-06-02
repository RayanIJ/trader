"""Max-premium calculation and conservative sizing (spec example included)."""
import pytest

from app.risk.premium import (
    MissingMultiplierError,
    contract_cost,
    is_within_premium_cap,
    max_allowed_ask,
    size_position,
)


def test_max_allowed_ask_uses_multiplier_not_hardcoded():
    assert max_allowed_ask(200.0, 100) == pytest.approx(2.0)
    # A non-100 multiplier must change the answer (no hardcoding).
    assert max_allowed_ask(200.0, 10) == pytest.approx(20.0)


def test_missing_multiplier_blocks():
    for bad in (None, 0, -5):
        with pytest.raises(MissingMultiplierError):
            max_allowed_ask(200.0, bad)
        with pytest.raises(MissingMultiplierError):
            contract_cost(2.0, bad)


def test_within_premium_cap_boundary():
    assert is_within_premium_cap(2.00, 100, 200.0) is True
    assert is_within_premium_cap(2.01, 100, 200.0) is False


def test_spec_sizing_example_accepts_when_allowance_sufficient():
    # ask 2.00 x100 = $200 cost; 25% stop => $50 risk; allowance $100 -> accept.
    s = size_position(2.00, 100, stop_loss_pct=25.0,
                      max_premium_per_contract_usd=200.0, remaining_daily_loss_usd=100.0)
    assert not s.rejected
    assert s.contracts == 1
    assert s.cost_per_contract == pytest.approx(200.0)
    assert s.dollar_risk == pytest.approx(50.0)


def test_spec_sizing_example_rejects_when_allowance_too_small():
    # Same trade, but only $40 remaining -> $50 risk exceeds allowance -> reject.
    s = size_position(2.00, 100, stop_loss_pct=25.0,
                      max_premium_per_contract_usd=200.0, remaining_daily_loss_usd=40.0)
    assert s.rejected
    assert s.contracts == 0


def test_sizing_rejects_above_premium_cap():
    s = size_position(2.50, 100, stop_loss_pct=25.0,
                      max_premium_per_contract_usd=200.0, remaining_daily_loss_usd=100.0)
    assert s.rejected
    assert "exceeds cap" in (s.reason or "")
