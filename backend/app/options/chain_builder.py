"""Option chain filtering + contract selection.

Takes a raw :class:`OptionChain` and a direction, applies the liquidity/premium/
spread/delta filters, and selects a single best long-call or long-put contract
near the money (or slightly OTM when momentum supports it). Every rejection is
captured with a :class:`RejectCode` so the scanner can show *why* a contract was
not chosen.

The premium cap is enforced via ``max_ask = max_premium / multiplier`` and a
missing multiplier blocks the contract — never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.config.schema import OptionFilterConfig, RiskConfig
from app.core.enums import Direction, OptionRight, RejectCode
from app.market_data.models import OptionChain, OptionQuote
from app.risk.premium import is_within_premium_cap


@dataclass
class ContractEvaluation:
    quote: OptionQuote
    passed: bool
    reject_codes: list[RejectCode] = field(default_factory=list)
    premium: float | None = None
    spread_pct: float | None = None
    distance_pct: float | None = None  # |strike - spot| / spot * 100


def evaluate_contract(
    q: OptionQuote,
    spot: float,
    options_cfg: OptionFilterConfig,
    risk_cfg: RiskConfig,
) -> ContractEvaluation:
    codes: list[RejectCode] = []

    if not q.spec.is_defined:
        codes.append(RejectCode.BLOCKED_MISSING_MULTIPLIER)

    if not q.has_two_sided():
        codes.append(RejectCode.BLOCKED_STALE_QUOTE)

    mult = q.spec.multiplier
    ask = q.ask
    premium = (ask * mult) if (ask and mult) else None
    spread_pct = q.spread_pct

    # Premium cap ($200 / multiplier).
    if ask is not None and mult:
        if not is_within_premium_cap(ask, mult, risk_cfg.max_premium_per_contract_usd):
            codes.append(RejectCode.BLOCKED_CONTRACT_ABOVE_MAX_PRICE)

    # Spread filter.
    if spread_pct is not None and spread_pct > options_cfg.max_spread_pct:
        codes.append(RejectCode.BLOCKED_WIDE_SPREAD)

    # Liquidity: bid floor, volume, open interest.
    if q.bid is not None and q.bid < options_cfg.min_option_bid:
        codes.append(RejectCode.BLOCKED_LOW_VOLUME)
    if q.volume is not None and q.volume < options_cfg.min_option_volume:
        codes.append(RejectCode.BLOCKED_LOW_VOLUME)
    if q.open_interest is not None and q.open_interest < options_cfg.min_open_interest:
        codes.append(RejectCode.BLOCKED_LOW_VOLUME)

    # Delta range (absolute).
    if q.delta is not None:
        ad = abs(q.delta)
        if ad < options_cfg.delta_min or ad > options_cfg.delta_max:
            codes.append(RejectCode.BLOCKED_LOW_SCORE)  # delta out of band

    distance_pct = (abs(q.spec.strike - spot) / spot * 100.0) if spot else None

    # Deduplicate while preserving order.
    seen: dict[RejectCode, None] = {}
    for c in codes:
        seen[c] = None
    codes = list(seen.keys())

    return ContractEvaluation(
        quote=q,
        passed=len(codes) == 0,
        reject_codes=codes,
        premium=premium,
        spread_pct=spread_pct,
        distance_pct=distance_pct,
    )


@dataclass
class ChainSelection:
    direction: Direction
    has_zero_dte: bool
    chosen: ContractEvaluation | None
    evaluated: list[ContractEvaluation]
    reject_codes: list[RejectCode] = field(default_factory=list)


def select_contract(
    chain: OptionChain,
    direction: Direction,
    spot: float,
    options_cfg: OptionFilterConfig,
    risk_cfg: RiskConfig,
    today_yyyymmdd: str,
    prefer_zero_dte: bool = True,
) -> ChainSelection:
    """Pick the best liquid long contract for ``direction`` near the money.

    Preference: 0DTE when available, else the nearest supported expiry. Among
    passing contracts we choose the one closest to ATM (slightly OTM allowed),
    breaking ties by tighter spread.
    """
    right = OptionRight.CALL if direction == Direction.CALL else OptionRight.PUT
    has_zero_dte = chain.has_zero_dte(today_yyyymmdd)

    target_expiry: str | None = None
    if prefer_zero_dte and has_zero_dte:
        target_expiry = today_yyyymmdd
    elif chain.expiries:
        # Nearest supported expiry (lexical sort works for YYYYMMDD).
        future = sorted(e for e in chain.expiries if e >= today_yyyymmdd)
        target_expiry = future[0] if future else sorted(chain.expiries)[-1]

    if target_expiry is None:
        return ChainSelection(direction, has_zero_dte, None, [], [RejectCode.BLOCKED_NO_0DTE_EXPIRY])

    candidates = [
        q for q in chain.quotes
        if q.spec.right == right and q.spec.expiry == target_expiry
    ]
    evaluations = [evaluate_contract(q, spot, options_cfg, risk_cfg) for q in candidates]
    passing = [e for e in evaluations if e.passed]

    def _otm(e: ContractEvaluation) -> bool:
        k = e.quote.spec.strike
        return k >= spot if right == OptionRight.CALL else k <= spot

    # Prefer ATM / slightly-OTM, closest strike to spot; tie-break tighter spread.
    passing.sort(
        key=lambda e: (
            0 if _otm(e) else 1,
            e.distance_pct if e.distance_pct is not None else 9e9,
            e.spread_pct if e.spread_pct is not None else 9e9,
        )
    )
    chosen = passing[0] if passing else None
    reject_codes: list[RejectCode] = []
    if chosen is None:
        if not candidates:
            reject_codes.append(RejectCode.BLOCKED_NO_0DTE_EXPIRY)
        else:
            # Surface the most common rejection across evaluated contracts.
            tally: dict[RejectCode, int] = {}
            for e in evaluations:
                for c in e.reject_codes:
                    tally[c] = tally.get(c, 0) + 1
            if tally:
                reject_codes.append(max(tally, key=tally.get))

    return ChainSelection(
        direction=direction,
        has_zero_dte=has_zero_dte,
        chosen=chosen,
        evaluated=evaluations,
        reject_codes=reject_codes,
    )
