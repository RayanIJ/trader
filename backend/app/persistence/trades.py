"""Persist orders, fills, positions, and exits to the trade lifecycle tables."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.core.logging import get_logger
from app.db.models import ExitRecord, Fill, OrderRecord, PositionRecord
from app.db.session import get_session

if TYPE_CHECKING:
    from app.execution.models import ActivePosition, OrderRequest, OrderResult

logger = get_logger("persistence")


class TradeStore:
    """Write-through store for the execution lifecycle."""

    def __init__(self, mode_fn) -> None:  # noqa: ANN001
        self._mode_fn = mode_fn
        self._open_position_ids: dict[str, int] = {}
        self._open_order_ids: dict[str, int] = {}

    def _pos_key(self, underlying: str) -> str:
        return underlying.upper()

    def record_entry(
        self,
        order: OrderRequest,
        result: OrderResult,
        pos: ActivePosition,
        *,
        shadow: bool,
    ) -> tuple[int, int]:
        mode = self._mode_fn()
        now = datetime.now(timezone.utc)
        with get_session() as s:
            order_row = OrderRecord(
                ts=now,
                broker_order_id=result.broker_order_id,
                symbol=order.underlying,
                direction=order.direction.value,
                side=order.side,
                order_type="LMT",
                limit_price=order.limit_price,
                quantity=order.quantity,
                state=result.state.value,
                mode=mode,
                message=result.message,
            )
            s.add(order_row)
            s.flush()

            if result.avg_fill_price is not None and result.filled_qty > 0:
                slippage = round(result.avg_fill_price - order.limit_price, 4)
                s.add(
                    Fill(
                        order_id=order_row.id,
                        ts=now,
                        quantity=result.filled_qty,
                        price=result.avg_fill_price,
                        slippage=slippage,
                    )
                )

            pos_row = PositionRecord(
                opened_at=pos.entry_ts,
                underlying=pos.underlying,
                direction=pos.direction.value,
                quantity=pos.quantity,
                entry_price=pos.entry_price,
                stop_price=pos.stop_price,
                target_price=pos.target_price,
                status="OPEN",
                mode=mode if not shadow else "SHADOW",
            )
            s.add(pos_row)
            s.commit()
            s.refresh(order_row)
            s.refresh(pos_row)

            key = self._pos_key(pos.underlying)
            self._open_order_ids[key] = order_row.id
            self._open_position_ids[key] = pos_row.id
            logger.debug(
                "persisted entry order=%s position=%s %s",
                order_row.id, pos_row.id, pos.underlying,
            )
            return order_row.id, pos_row.id

    def record_exit(
        self,
        pos: ActivePosition,
        *,
        exit_price: float,
        realized_pnl: float,
        reason: str,
    ) -> int | None:
        key = self._pos_key(pos.underlying)
        position_id = self._open_position_ids.pop(key, None)
        self._open_order_ids.pop(key, None)
        now = datetime.now(timezone.utc)
        time_in_trade = (now - pos.entry_ts).total_seconds()

        with get_session() as s:
            if position_id is not None:
                row = s.get(PositionRecord, position_id)
                if row:
                    row.status = "CLOSED"
            else:
                row = (
                    s.query(PositionRecord)
                    .filter(
                        PositionRecord.underlying == pos.underlying,
                        PositionRecord.status == "OPEN",
                    )
                    .order_by(PositionRecord.opened_at.desc())
                    .first()
                )
                if row:
                    row.status = "CLOSED"
                    position_id = row.id

            if position_id is None:
                logger.warning("no open position row for exit %s", pos.underlying)
                s.commit()
                return None

            exit_row = ExitRecord(
                position_id=position_id,
                ts=now,
                reason=reason,
                exit_price=exit_price,
                realized_pnl=round(realized_pnl, 2),
                time_in_trade_sec=round(time_in_trade, 1),
            )
            s.add(exit_row)
            s.commit()
            s.refresh(exit_row)
            logger.debug("persisted exit position=%s pnl=%.2f", position_id, realized_pnl)
            return exit_row.id
