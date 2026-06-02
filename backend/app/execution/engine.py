"""Execution engine — entry, fill monitoring, exit, shadow simulation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config.schema import AppConfig
from app.core.enums import ExitReason, OrderState, TradingMode
from app.core.events import Topic, bus
from app.core.logging import get_logger
from app.execution.exit import evaluate_exit
from app.execution.models import ActivePosition, ExecutionSnapshot, OrderRequest, OrderResult
from app.execution.orders import build_entry_order, build_exit_order, exit_plan
from app.execution.position_manager import PositionManager
from app.execution.state_machine import OrderStateMachine
from app.market_data.source import MarketDataSource
from app.macro.calendar import MacroGuard
from app.modes.manager import ModeManager
from app.persistence.trades import TradeStore
from app.risk.day_state import TradingDayState
from app.scanner.engine import ScanCandidate, ScanResult

if TYPE_CHECKING:
    from app.journal.service import JournalService

logger = get_logger("execution")


class ExecutionEngine:
    """Orchestrates automated entries/exits for approved scanner candidates."""

    def __init__(
        self,
        cfg: AppConfig,
        mode_manager: ModeManager,
        day_state: TradingDayState,
        macro: MacroGuard,
        positions: PositionManager,
        market_data: MarketDataSource | None = None,
        journal: JournalService | None = None,
        trade_store: TradeStore | None = None,
    ) -> None:
        self._cfg = cfg
        self._modes = mode_manager
        self._day = day_state
        self._macro = macro
        self._positions = positions
        self._mdata = market_data
        self._journal = journal
        self._trade_store = trade_store
        self._enabled = False
        self._snapshot = ExecutionSnapshot(enabled=False, mode=cfg.default_mode.value)
        self._last_order: OrderResult | None = None
        self._last_exit: ExitReason | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def snapshot(self) -> ExecutionSnapshot:
        self._snapshot.enabled = self._enabled
        self._snapshot.mode = self._modes.mode.value
        self._snapshot.active_position = self._positions.position
        self._snapshot.last_order = self._last_order
        self._snapshot.last_exit_reason = self._last_exit
        return self._snapshot

    def set_enabled(self, on: bool) -> None:
        self._enabled = on
        self._snapshot.enabled = on

    async def tick(
        self,
        scan: ScanResult | None,
        *,
        health_ok: bool = True,
        broker_tradable: bool = True,
    ) -> ExecutionSnapshot:
        """One execution cycle: monitor open position, maybe enter a new setup."""
        now = datetime.now(timezone.utc)
        mode = self._modes.mode

        if self._positions.has_open:
            await self._monitor_position(now, health_ok=health_ok)
        elif self._enabled and scan is not None and not self._day.lockout:
            await self._maybe_enter(scan, mode, now, broker_tradable=broker_tradable)

        snap = self.snapshot
        await bus.publish(Topic.EXECUTION, snap.to_dict())
        if snap.active_position:
            await bus.publish(Topic.POSITION, snap.active_position.to_dict())
        return snap

    async def emergency_close(self, reason: ExitReason = ExitReason.MANUAL_EMERGENCY) -> None:
        """Flatten any open position immediately."""
        pos = self._positions.position
        if pos is None:
            return
        if pos.is_shadow:
            mark = pos.entry_price
            pnl = pos.unrealized_pnl(mark)
            self._positions.close(pnl, pos.signal_type)
            self._last_exit = reason
            await self._log_exit(pos, pnl, reason, mark)
            if self._trade_store is not None:
                self._trade_store.record_exit(
                    pos, exit_price=mark, realized_pnl=pnl, reason=reason.value
                )
            return
        bid = await self._quote_option(pos)
        if bid is None:
            bid = pos.entry_price * 0.9
        await self._submit_exit(pos, bid, reason)

    async def _maybe_enter(
        self,
        scan: ScanResult,
        mode: TradingMode,
        now: datetime,
        *,
        broker_tradable: bool,
    ) -> None:
        approved = [c for c in scan.candidates if c.approved]
        if not approved:
            return
        best = max(approved, key=lambda c: c.score)
        if best.contract is None or best.contract.ask is None:
            return

        direction = best.direction
        from app.core.enums import Direction

        dir_enum = Direction.CALL if direction == "CALL" else Direction.PUT
        qty = int(best.risk_decision.get("contracts", 1) or 1)
        ask = float(best.contract.ask)
        mult = 100.0
        order = build_entry_order(
            underlying=best.symbol,
            expiry=best.contract.expiry,
            strike=best.contract.strike,
            right=best.contract.right,
            direction=dir_enum,
            quantity=max(qty, 1),
            ask=ask,
            multiplier=mult,
            cfg=self._cfg.execution,
        )

        if mode == TradingMode.SHADOW:
            await self._shadow_fill_entry(best, order, ask, dir_enum, now)
            return

        if not broker_tradable:
            self._snapshot.messages.append("broker not tradable — entry skipped")
            await self._log_reject(best, ["BROKER_NOT_TRADABLE"])
            return

        await self._broker_fill_entry(best, order, dir_enum, now)

    async def _shadow_fill_entry(
        self,
        cand: ScanCandidate,
        order: OrderRequest,
        fill_price: float,
        direction,
        now: datetime,
    ) -> None:
        stop, target = exit_plan(fill_price, self._cfg.execution)
        pos = ActivePosition(
            underlying=order.underlying,
            expiry=order.expiry,
            strike=order.strike,
            right=order.right,
            direction=direction,
            quantity=order.quantity,
            entry_price=fill_price,
            entry_ts=now,
            multiplier=order.multiplier,
            stop_price=stop,
            target_price=target,
            peak_premium=fill_price,
            signal_type=cand.signal_type,
            is_shadow=True,
        )
        self._positions.open(pos)
        self._day.record_signal(order.underlying, direction, cand.signal_type, now)
        self._last_order = OrderResult(None, OrderState.FILLED, order.quantity, fill_price, "shadow fill")
        self._snapshot.messages.append(f"shadow entry {order.underlying} @ {fill_price:.2f}")
        logger.info("shadow entry %s %s @ %.2f", order.underlying, direction.value, fill_price)
        await self._log_entry(order, fill_price, cand, shadow=True)
        if self._trade_store is not None:
            self._trade_store.record_entry(order, self._last_order, pos, shadow=True)

    async def _broker_fill_entry(self, cand: ScanCandidate, order: OrderRequest, direction, now: datetime) -> None:
        sm = OrderStateMachine()
        sm.transition(OrderState.RISK_APPROVED)
        sm.transition(OrderState.PREPARED)
        try:
            result = await self._modes.broker.place_order(order.to_dict())
        except Exception as exc:
            self._last_order = OrderResult(None, OrderState.REJECTED, message=str(exc))
            self._snapshot.messages.append(f"entry rejected: {exc}")
            await self._log_order(order, self._last_order, "entry")
            return

        self._last_order = OrderResult(
            result.get("broker_order_id"),
            OrderState(result.get("state", OrderState.SUBMITTED.value)),
            int(result.get("filled_qty", 0)),
            result.get("avg_fill_price"),
            result.get("message"),
        )
        fill = self._last_order.avg_fill_price or order.limit_price
        if self._last_order.state != OrderState.FILLED:
            self._snapshot.messages.append(f"entry not filled: {self._last_order.state.value}")
            return

        stop, target = exit_plan(fill, self._cfg.execution)
        pos = ActivePosition(
            underlying=order.underlying,
            expiry=order.expiry,
            strike=order.strike,
            right=order.right,
            direction=direction,
            quantity=order.quantity,
            entry_price=fill,
            entry_ts=now,
            multiplier=order.multiplier,
            stop_price=stop,
            target_price=target,
            peak_premium=fill,
            signal_type=cand.signal_type,
            broker_order_id=self._last_order.broker_order_id,
            is_shadow=False,
        )
        self._positions.open(pos)
        self._day.record_signal(order.underlying, direction, cand.signal_type, now)
        self._snapshot.messages.append(f"filled entry {order.underlying} @ {fill:.2f}")
        await self._log_order(order, self._last_order, "entry")
        await self._log_entry(order, fill, cand, shadow=False)
        if self._trade_store is not None:
            self._trade_store.record_entry(order, self._last_order, pos, shadow=False)

    async def _monitor_position(self, now: datetime, *, health_ok: bool) -> None:
        pos = self._positions.position
        if pos is None:
            return

        bid, ask = await self._quote_option_pair(pos)
        reason = evaluate_exit(
            pos,
            mark_bid=bid,
            mark_ask=ask,
            cfg=self._cfg.execution,
            macro=self._macro,
            now=now,
            daily_lockout=self._day.lockout,
            health_ok=health_ok,
        )
        if reason is None:
            return

        if pos.is_shadow:
            mark = bid or ask or pos.entry_price
            pnl = pos.unrealized_pnl(mark)
            self._positions.close(pnl, pos.signal_type)
            self._last_exit = reason
            self._snapshot.messages.append(f"shadow exit {reason.value} pnl={pnl:.2f}")
            await self._log_exit(pos, pnl, reason, mark)
            if self._trade_store is not None:
                self._trade_store.record_exit(
                    pos, exit_price=mark, realized_pnl=pnl, reason=reason.value
                )
            return

        if bid is None:
            bid = pos.entry_price * 0.95
        await self._submit_exit(pos, bid, reason)

    async def _submit_exit(self, pos: ActivePosition, bid: float, reason: ExitReason) -> None:
        order = build_exit_order(pos, bid, self._cfg.execution)
        try:
            result = await self._modes.broker.place_order(order.to_dict())
            fill = result.get("avg_fill_price") or order.limit_price
            pnl = (fill - pos.entry_price) * pos.quantity * pos.multiplier
            self._positions.close(pnl, pos.signal_type)
            self._last_exit = reason
            self._last_order = OrderResult(
                result.get("broker_order_id"),
                OrderState(result.get("state", OrderState.FILLED.value)),
                int(result.get("filled_qty", pos.quantity)),
                fill,
                reason.value,
            )
            self._snapshot.messages.append(f"exit {reason.value} pnl={pnl:.2f}")
            await self._log_order(order, self._last_order, "exit")
            await self._log_exit(pos, pnl, reason, fill)
            if self._trade_store is not None:
                self._trade_store.record_exit(
                    pos, exit_price=fill, realized_pnl=pnl, reason=reason.value
                )
        except Exception as exc:
            self._snapshot.messages.append(f"exit failed: {exc}")
            logger.exception("exit order failed")

    async def _log_entry(
        self, order: OrderRequest, fill: float, cand: ScanCandidate, *, shadow: bool
    ) -> None:
        if self._journal is None:
            return
        await self._journal.record_async(
            "ENTRY",
            {
                "underlying": order.underlying,
                "expiry": order.expiry,
                "strike": order.strike,
                "right": order.right,
                "direction": order.direction.value,
                "quantity": order.quantity,
                "fill_price": fill,
                "signal_type": cand.signal_type,
                "score": cand.score,
                "shadow": shadow,
            },
            symbol=order.underlying,
        )

    async def _log_exit(
        self, pos: ActivePosition, pnl: float, reason: ExitReason, mark: float
    ) -> None:
        if self._journal is None:
            return
        await self._journal.record_async(
            "EXIT",
            {
                "reason": reason.value,
                "realized_pnl": round(pnl, 2),
                "entry_price": pos.entry_price,
                "exit_mark": mark,
                "signal_type": pos.signal_type,
                "shadow": pos.is_shadow,
            },
            symbol=pos.underlying,
        )

    async def _log_order(self, order: OrderRequest, result: OrderResult, leg: str) -> None:
        if self._journal is None:
            return
        await self._journal.record_async(
            "ORDER",
            {
                "leg": leg,
                "state": result.state.value,
                "broker_order_id": result.broker_order_id,
                "filled_qty": result.filled_qty,
                "avg_fill_price": result.avg_fill_price,
                "message": result.message,
                "limit_price": order.limit_price,
            },
            symbol=order.underlying,
        )

    async def _log_reject(self, cand: ScanCandidate, codes: list[str]) -> None:
        if self._journal is None:
            return
        await self._journal.record_async(
            "REJECT",
            {"reject_codes": codes, "score": cand.score, "signal_type": cand.signal_type},
            symbol=cand.symbol,
        )

    async def _quote_option(self, pos: ActivePosition) -> float | None:
        bid, ask = await self._quote_option_pair(pos)
        return bid or ask

    async def _quote_option_pair(self, pos: ActivePosition) -> tuple[float | None, float | None]:
        if self._mdata is None:
            return None, None
        from app.core.enums import OptionRight

        right = OptionRight.CALL if pos.right in ("C", "CALL") else OptionRight.PUT
        q = await self._mdata.get_option_quote(pos.underlying, pos.expiry, pos.strike, right)
        if q is None:
            return None, None
        return q.bid, q.ask
