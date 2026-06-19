"""Risk engine — mandatory gate between signal approval and execution.

A good signal cannot bypass risk. Enforces daily-loss lockout, premium cap,
stop-risk sizing, cooldowns, duplicate blocking, macro, behavior RED, and
position limits.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.config.schema import AppConfig
from app.core.enums import BehaviorState, Direction, RejectCode
from app.macro.calendar import MacroGuard
from app.risk.behavior import BehaviorGovernor, BehaviorStatus
from app.risk.day_state import TradingDayState
from app.risk.premium import MissingMultiplierError, size_position
from app.signals.engine import SignalDecision


@dataclass
class RiskDecision:
    approved: bool
    reject_codes: list[RejectCode] = field(default_factory=list)
    contracts: int = 0
    dollar_risk: float = 0.0
    cost_per_contract: float = 0.0
    behavior: BehaviorState = BehaviorState.CONTROLLED
    remaining_allowance: float = 0.0

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reject_codes": [rc.value for rc in self.reject_codes],
            "contracts": self.contracts,
            "dollar_risk": round(self.dollar_risk, 2),
            "cost_per_contract": round(self.cost_per_contract, 2),
            "behavior": self.behavior.value,
            "remaining_allowance": round(self.remaining_allowance, 2),
        }


class RiskEngine:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        self._behavior = BehaviorGovernor(cfg.risk)

    def evaluate(
        self,
        *,
        symbol: str,
        direction: Direction,
        signal_type: str,
        signal: SignalDecision,
        day: TradingDayState,
        macro: MacroGuard,
        behavior: BehaviorStatus,
        option_ask: float | None,
        multiplier: float | None,
        health_ok: bool = True,
        broker_tradable: bool = True,
        now: datetime | None = None,
    ) -> RiskDecision:
        now = now or datetime.now(timezone.utc)
        codes: list[RejectCode] = []
        remaining = day.remaining_loss_allowance(self._cfg.risk.max_daily_loss_usd)

        if not signal.approved:
            codes.extend(signal.reject_codes)

        if macro.is_blocked(now):
            rc = macro.reject_code(now)
            if rc not in codes:
                codes.append(rc)

        if not health_ok:
            codes.append(RejectCode.BLOCKED_SYSTEM_HEALTH)

        if not broker_tradable:
            codes.append(RejectCode.BLOCKED_BROKER_SESSION_INVALID)

        daily_rc = day.check_daily_loss(self._cfg.risk.max_daily_loss_usd)
        if daily_rc:
            codes.append(daily_rc)

        if behavior.state == BehaviorState.RED:
            codes.append(RejectCode.BLOCKED_BEHAVIOR_RED)

        for rc in (
            day.cooldown_reject(symbol, direction, self._cfg.risk, now),
            day.duplicate_signal_reject(symbol, direction, signal_type, now),
            day.direction_flip_reject(symbol, direction, now),
        ):
            if rc and rc not in codes:
                codes.append(rc)

        if day.has_position(symbol):
            codes.append(RejectCode.BLOCKED_EXISTING_POSITION)

        if len(day.open_positions) >= self._cfg.risk.max_open_positions:
            codes.append(RejectCode.BLOCKED_MAX_OPEN_POSITIONS)

        exposure = day.open_premium_exposure()
        if exposure >= self._cfg.risk.max_total_premium_exposure_usd:
            codes.append(RejectCode.BLOCKED_MAX_OPEN_POSITIONS)

        sizing = None
        if option_ask is not None and option_ask > 0:
            try:
                sizing = size_position(
                    option_ask,
                    multiplier,
                    self._cfg.execution.stop_loss_pct,
                    self._cfg.risk.max_premium_per_contract_usd,
                    remaining,
                )
            except MissingMultiplierError:
                codes.append(RejectCode.BLOCKED_MISSING_MULTIPLIER)
                sizing = None
            if sizing and sizing.rejected:
                if "exceeds cap" in (sizing.reason or ""):
                    codes.append(RejectCode.BLOCKED_CONTRACT_ABOVE_MAX_PRICE)
                elif "stop risk" in (sizing.reason or ""):
                    codes.append(RejectCode.BLOCKED_STOP_EXCEEDS_RISK)
                else:
                    codes.append(RejectCode.BLOCKED_CONTRACT_ABOVE_MAX_PRICE)
        elif signal.approved:
            codes.append(RejectCode.BLOCKED_CONTRACT_ABOVE_MAX_PRICE)

        seen: set[RejectCode] = set()
        unique = [rc for rc in codes if rc not in seen and not seen.add(rc)]  # type: ignore[func-returns-value]

        approved = len(unique) == 0 and sizing is not None and not sizing.rejected
        return RiskDecision(
            approved=approved,
            reject_codes=unique,
            contracts=sizing.contracts if sizing and approved else 0,
            dollar_risk=sizing.dollar_risk if sizing else 0.0,
            cost_per_contract=sizing.cost_per_contract if sizing else 0.0,
            behavior=behavior.state,
            remaining_allowance=remaining,
        )

    @property
    def behavior_governor(self) -> BehaviorGovernor:
        return self._behavior
