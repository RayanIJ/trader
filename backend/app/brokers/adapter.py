"""Broker adapter interface and shared status types.

Keeping a narrow interface here means the trading logic never imports ``ibapi``
directly — it depends only on these abstractions, so Shadow/Paper/Live (and a
future backtest broker) are drop-in replacements.
"""
from __future__ import annotations

import socket
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.core.enums import DataFeedStatus, TradingMode


@dataclass
class BrokerStatus:
    """Snapshot of broker/session health used by the health monitor and gates."""

    mode: TradingMode
    gateway_reachable: bool = False        # TCP socket to TWS/Gateway opens
    session_connected: bool = False        # ibapi connection established
    next_valid_id_received: bool = False   # handshake completed
    account_available: bool = False
    account_id: str | None = None
    data_feed: DataFeedStatus = DataFeedStatus.UNAVAILABLE
    market_data_type: int | None = None
    positions_synced: bool = False
    data_farm_ok: bool = True               # gateway<->IBKR market-data farm link
    last_error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def is_tradable(self) -> bool:
        """True only when the full chain of broker prerequisites is satisfied."""
        return (
            self.gateway_reachable
            and self.session_connected
            and self.next_valid_id_received
            and self.account_available
        )


class BrokerError(Exception):
    pass


class ShadowModeError(BrokerError):
    """Raised if an order send is attempted while in Shadow mode."""


def probe_gateway(host: str, port: int, timeout: float = 1.5) -> bool:
    """Cheap TCP reachability check — does NOT require ibapi or a full session."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class BrokerAdapter(ABC):
    mode: TradingMode

    @abstractmethod
    async def connect(self) -> BrokerStatus:
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        ...

    @abstractmethod
    async def status(self) -> BrokerStatus:
        ...

    @abstractmethod
    async def account_summary(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def positions(self) -> list[dict[str, Any]]:
        ...

    @abstractmethod
    async def place_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Phase 5/6. Shadow must never transmit; Live requires explicit enable."""
        ...
