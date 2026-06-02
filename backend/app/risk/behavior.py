"""Behavior governor — CONTROLLED / CAUTION / RED.

RED blocks all new trades. Derived from daily loss proximity, recent losses,
trade frequency, and execution instability flags.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config.schema import RiskConfig
from app.core.enums import BehaviorState
from app.risk.day_state import TradingDayState


@dataclass
class BehaviorStatus:
    state: BehaviorState
    reasons: list[str]

    def to_dict(self) -> dict:
        return {"state": self.state.value, "reasons": self.reasons}


class BehaviorGovernor:
    def __init__(self, cfg: RiskConfig) -> None:
        self._cfg = cfg

    def evaluate(
        self,
        day: TradingDayState,
        *,
        now: datetime | None = None,
        health_degraded: bool = False,
        execution_unstable: bool = False,
    ) -> BehaviorStatus:
        now = now or datetime.now(timezone.utc)
        reasons: list[str] = []

        if day.lockout or day.total_pnl <= -self._cfg.max_daily_loss_usd:
            return BehaviorStatus(BehaviorState.RED, ["daily loss lockout"])

        if health_degraded or execution_unstable:
            reasons.append("system or execution instability")

        # Recent repeated losses.
        recent_losses = [s for s in day.recent_losses if (now - s.ts).total_seconds() < 3600]
        if len(recent_losses) >= self._cfg.block_setup_after_losses:
            reasons.append(f"{len(recent_losses)} recent losses in the last hour")

        # Rapid trading.
        hour_ago = now - timedelta(hours=1)
        trades_last_hour = sum(1 for s in day.recent_signals if s.ts >= hour_ago)
        if trades_last_hour >= self._cfg.caution_trades_per_hour:
            reasons.append(f"{trades_last_hour} signals in the last hour")

        if any("lockout" in r or "instability" in r for r in reasons):
            return BehaviorStatus(BehaviorState.RED, reasons)

        if reasons:
            return BehaviorStatus(BehaviorState.CAUTION, reasons)

        return BehaviorStatus(BehaviorState.CONTROLLED, [])
