"""Exit engine — fast scalp exits before end-of-day holds."""
from __future__ import annotations

from datetime import datetime

from app.config.schema import AppConfig, ExecutionConfig
from app.core.enums import ExitReason
from app.execution.models import ActivePosition
from app.macro.calendar import MacroGuard


def evaluate_exit(
    pos: ActivePosition,
    *,
    mark_bid: float | None,
    mark_ask: float | None,
    cfg: ExecutionConfig,
    macro: MacroGuard,
    now: datetime,
    daily_lockout: bool,
    health_ok: bool,
) -> ExitReason | None:
    """Return an exit reason if the position should be flattened now."""
    if daily_lockout:
        return ExitReason.DAILY_LOSS_LOCKOUT
    if not health_ok:
        return ExitReason.BROKER_UNSTABLE

    macro_st = macro.status(now)
    if cfg.exit_before_macro and macro_st.should_exit_open:
        return ExitReason.MACRO_GUARD

    mark = mark_bid or mark_ask
    if mark is None or mark <= 0:
        return None

    if mark > pos.peak_premium:
        pos.peak_premium = mark

    elapsed = pos.time_in_trade_sec(now)

    if mark <= pos.stop_price:
        return ExitReason.STOP_LOSS
    if mark >= pos.target_price:
        return ExitReason.PROFIT_TARGET

    # Profit giveback from peak after target zone touched.
    if pos.peak_premium >= pos.target_price:
        giveback = ((pos.peak_premium - mark) / pos.peak_premium) * 100.0
        if giveback >= cfg.profit_giveback_pct:
            return ExitReason.PROFIT_TARGET

    if elapsed >= cfg.hard_time_stop_sec:
        return ExitReason.TIME_STOP

    if cfg.no_movement_exit_sec <= elapsed <= cfg.fast_failure_max_sec:
        if pos.premium_change_pct(mark) < 2.0:
            return ExitReason.MOMENTUM_FADE

    return None
