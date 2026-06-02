"""Execution DTOs shared by the engine, broker adapter, and API."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from app.core.enums import Direction, ExitReason, OrderState


@dataclass
class OrderRequest:
    underlying: str
    expiry: str
    strike: float
    right: str                    # C / P
    direction: Direction
    quantity: int
    limit_price: float
    side: str                     # BUY_TO_OPEN / SELL_TO_CLOSE
    multiplier: float = 100.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["direction"] = self.direction.value
        return d


@dataclass
class OrderResult:
    broker_order_id: int | None
    state: OrderState
    filled_qty: int = 0
    avg_fill_price: float | None = None
    message: str | None = None

    def to_dict(self) -> dict:
        return {
            "broker_order_id": self.broker_order_id,
            "state": self.state.value,
            "filled_qty": self.filled_qty,
            "avg_fill_price": self.avg_fill_price,
            "message": self.message,
        }


@dataclass
class ActivePosition:
    underlying: str
    expiry: str
    strike: float
    right: str
    direction: Direction
    quantity: int
    entry_price: float
    entry_ts: datetime
    multiplier: float
    stop_price: float
    target_price: float
    peak_premium: float
    signal_type: str = ""
    broker_order_id: int | None = None
    is_shadow: bool = False

    @property
    def contract_key(self) -> str:
        return f"{self.underlying}:{self.expiry}:{self.strike}:{self.right}"

    def unrealized_pnl(self, mark: float) -> float:
        return (mark - self.entry_price) * self.quantity * self.multiplier

    def premium_change_pct(self, mark: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        return ((mark - self.entry_price) / self.entry_price) * 100.0

    def time_in_trade_sec(self, now: datetime) -> float:
        return (now - self.entry_ts).total_seconds()

    def to_dict(self, *, mark: float | None = None) -> dict:
        d = {
            "underlying": self.underlying,
            "expiry": self.expiry,
            "strike": self.strike,
            "right": self.right,
            "direction": self.direction.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "entry_ts": self.entry_ts.isoformat(),
            "multiplier": self.multiplier,
            "stop_price": self.stop_price,
            "target_price": self.target_price,
            "peak_premium": self.peak_premium,
            "signal_type": self.signal_type,
            "is_shadow": self.is_shadow,
        }
        if mark is not None:
            d["mark"] = mark
            d["unrealized_pnl"] = round(self.unrealized_pnl(mark), 2)
            d["premium_change_pct"] = round(self.premium_change_pct(mark), 2)
            d["time_in_trade_sec"] = round(self.time_in_trade_sec(datetime.now(self.entry_ts.tzinfo)), 1)
        return d


@dataclass
class ExecutionSnapshot:
    enabled: bool
    mode: str
    active_position: ActivePosition | None = None
    last_order: OrderResult | None = None
    last_exit_reason: ExitReason | None = None
    messages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "automation_enabled": self.enabled,
            "mode": self.mode,
            "active_position": (
                self.active_position.to_dict() if self.active_position else None
            ),
            "last_order": self.last_order.to_dict() if self.last_order else None,
            "last_exit_reason": self.last_exit_reason.value if self.last_exit_reason else None,
            "messages": self.messages[-10:],
        }
