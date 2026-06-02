"""Premium-cap math.

The user's "$200 max per contract" rule is expressed against the *quoted* option
price, which is per-share. We never hardcode the 100 multiplier: the maximum
allowable ask is ``max_premium / contract_multiplier``. If the multiplier is
missing or non-positive, the trade is blocked (we refuse to guess).

Per-contract dollar risk uses the configured stop-loss percentage so the risk
engine can reject any trade whose worst case exceeds the remaining daily-loss
allowance (default $100).
"""
from __future__ import annotations

from dataclasses import dataclass


class MissingMultiplierError(ValueError):
    """Raised when contract multiplier is missing/invalid — trade must be blocked."""


def max_allowed_ask(max_premium_usd: float, multiplier: float | None) -> float:
    """Maximum quoted ask allowed so that ask * multiplier <= max_premium_usd."""
    if multiplier is None or multiplier <= 0:
        raise MissingMultiplierError("contract multiplier missing or invalid")
    return max_premium_usd / multiplier


def contract_cost(ask: float, multiplier: float | None) -> float:
    """Total dollar cost of one contract at the given quoted ask."""
    if multiplier is None or multiplier <= 0:
        raise MissingMultiplierError("contract multiplier missing or invalid")
    return ask * multiplier


def is_within_premium_cap(ask: float, multiplier: float | None, max_premium_usd: float) -> bool:
    """True iff a single contract at ``ask`` costs <= the per-contract cap."""
    return contract_cost(ask, multiplier) <= max_premium_usd + 1e-9


@dataclass
class RiskSizing:
    contracts: int
    cost_per_contract: float
    dollar_risk: float
    rejected: bool
    reason: str | None = None


def size_position(
    ask: float,
    multiplier: float | None,
    stop_loss_pct: float,
    max_premium_per_contract_usd: float,
    remaining_daily_loss_usd: float,
) -> RiskSizing:
    """Conservatively size a long option position.

    Mirrors the spec example: ask 2.00 x100 = $200 cost; 25% stop => $50 risk;
    if remaining daily allowance < $50, the trade is rejected (size 0). v1 trades
    a single contract per setup (max_open_positions/per_underlying = 1).
    """
    try:
        cost = contract_cost(ask, multiplier)
    except MissingMultiplierError as exc:
        return RiskSizing(0, 0.0, 0.0, rejected=True, reason=str(exc))

    if cost > max_premium_per_contract_usd + 1e-9:
        return RiskSizing(
            0, cost, 0.0, rejected=True,
            reason=f"contract cost ${cost:.2f} exceeds cap ${max_premium_per_contract_usd:.2f}",
        )

    dollar_risk = cost * (stop_loss_pct / 100.0)
    if dollar_risk > remaining_daily_loss_usd + 1e-9:
        return RiskSizing(
            0, cost, dollar_risk, rejected=True,
            reason=(
                f"stop risk ${dollar_risk:.2f} exceeds remaining daily allowance "
                f"${remaining_daily_loss_usd:.2f}"
            ),
        )

    return RiskSizing(contracts=1, cost_per_contract=cost, dollar_risk=dollar_risk, rejected=False)
