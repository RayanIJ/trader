"""Order builders — marketable limit only (never naked market)."""
from __future__ import annotations

from app.config.schema import ExecutionConfig
from app.core.enums import Direction
from app.execution.models import ActivePosition, OrderRequest


def marketable_limit_price(ask: float, cfg: ExecutionConfig) -> float:
    """Price a buy limit at ask + allowed slippage (still a limit, not MKT)."""
    slip = cfg.max_slippage_pct / 100.0
    return round(ask * (1.0 + slip), 2)


def sell_limit_price(bid: float, cfg: ExecutionConfig) -> float:
    """Price a sell-to-close limit at bid − slippage."""
    slip = cfg.max_slippage_pct / 100.0
    return round(max(bid * (1.0 - slip), 0.01), 2)


def build_entry_order(
    *,
    underlying: str,
    expiry: str,
    strike: float,
    right: str,
    direction: Direction,
    quantity: int,
    ask: float,
    multiplier: float,
    cfg: ExecutionConfig,
) -> OrderRequest:
    if cfg.allow_naked_market_orders:
        raise ValueError("naked market orders are forbidden by spec")
    return OrderRequest(
        underlying=underlying,
        expiry=expiry,
        strike=strike,
        right=right,
        direction=direction,
        quantity=quantity,
        limit_price=marketable_limit_price(ask, cfg),
        side="BUY_TO_OPEN",
        multiplier=multiplier,
    )


def build_exit_order(
    pos: ActivePosition,
    bid: float,
    cfg: ExecutionConfig,
) -> OrderRequest:
    return OrderRequest(
        underlying=pos.underlying,
        expiry=pos.expiry,
        strike=pos.strike,
        right=pos.right,
        direction=pos.direction,
        quantity=pos.quantity,
        limit_price=sell_limit_price(bid, cfg),
        side="SELL_TO_CLOSE",
        multiplier=pos.multiplier,
    )


def exit_plan(entry_premium: float, cfg: ExecutionConfig) -> tuple[float, float]:
    """Return (stop_price, target_price) as absolute option premiums."""
    stop = entry_premium * (1.0 - cfg.stop_loss_pct / 100.0)
    target = entry_premium * (1.0 + cfg.first_profit_target_pct / 100.0)
    return round(max(stop, 0.01), 2), round(target, 2)
