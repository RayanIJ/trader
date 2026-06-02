"""In-memory position book (one open scalp at a time in v1)."""
from __future__ import annotations

from datetime import datetime, timezone

from app.execution.models import ActivePosition
from app.risk.day_state import OpenPositionStub, TradingDayState


class PositionManager:
    def __init__(self, day_state: TradingDayState) -> None:
        self._day = day_state
        self._position: ActivePosition | None = None

    @property
    def has_open(self) -> bool:
        return self._position is not None

    @property
    def position(self) -> ActivePosition | None:
        return self._position

    def open(self, pos: ActivePosition) -> None:
        if self._position is not None:
            raise RuntimeError("max one open position in v1")
        self._position = pos
        cost = pos.entry_price * pos.quantity * pos.multiplier
        self._day.open_positions.append(
            OpenPositionStub(
                symbol=pos.underlying,
                direction=pos.direction,
                premium_exposure=cost,
                entry_ts=pos.entry_ts,
            )
        )

    def close(self, realized_pnl: float, signal_type: str) -> ActivePosition | None:
        pos = self._position
        if pos is None:
            return None
        self._position = None
        self._day.open_positions = [
            p for p in self._day.open_positions if p.symbol != pos.underlying
        ]
        self._day.record_trade_exit(
            pos.underlying, pos.direction, realized_pnl, signal_type, datetime.now(timezone.utc)
        )
        return pos

    def clear(self) -> None:
        if self._position:
            sym = self._position.underlying
            self._day.open_positions = [p for p in self._day.open_positions if p.symbol != sym]
        self._position = None
