"""Order state machine — explicit transitions only."""
from __future__ import annotations

from app.core.enums import OrderState

_TERMINAL = {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED, OrderState.EXPIRED}

_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.CANDIDATE: {OrderState.RISK_APPROVED, OrderState.REJECTED},
    OrderState.RISK_APPROVED: {OrderState.PREPARED, OrderState.REJECTED},
    OrderState.PREPARED: {OrderState.SUBMITTED, OrderState.REJECTED},
    OrderState.SUBMITTED: {
        OrderState.PARTIALLY_FILLED,
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
        OrderState.EXPIRED,
    },
    OrderState.PARTIALLY_FILLED: {
        OrderState.FILLED,
        OrderState.CANCELLED,
        OrderState.REJECTED,
    },
}


class OrderStateMachine:
    def __init__(self, initial: OrderState = OrderState.CANDIDATE) -> None:
        self.state = initial

    def can_transition(self, nxt: OrderState) -> bool:
        if self.state in _TERMINAL:
            return False
        return nxt in _TRANSITIONS.get(self.state, set())

    def transition(self, nxt: OrderState) -> None:
        if not self.can_transition(nxt):
            raise ValueError(f"invalid transition {self.state.value} -> {nxt.value}")
        self.state = nxt
