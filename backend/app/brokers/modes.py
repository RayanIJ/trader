"""Mode-specific broker adapters and a factory.

- ShadowBroker: may connect read-only for status/data, but NEVER transmits orders.
- PaperBroker: connects to the paper port; will transmit to the paper account.
- LiveBroker: connects to the live port; transmits only after explicit enablement
  (gated by the mode manager + pre-trade health checks in later phases).

All three share the TWS socket transport; only ``transmit_orders`` and the port
differ, which keeps the broker surface uniform.
"""
from __future__ import annotations

from typing import Any

from app.brokers.adapter import ShadowModeError
from app.brokers.tws import TwsBroker
from app.config.schema import BrokerConfig
from app.core.enums import TradingMode


class ShadowBroker(TwsBroker):
    def __init__(self, cfg: BrokerConfig) -> None:
        super().__init__(TradingMode.SHADOW, cfg, transmit_orders=False)

    async def place_order(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise ShadowModeError("Shadow mode never transmits orders")


class PaperBroker(TwsBroker):
    def __init__(self, cfg: BrokerConfig) -> None:
        super().__init__(TradingMode.PAPER, cfg, transmit_orders=True)


class LiveBroker(TwsBroker):
    def __init__(self, cfg: BrokerConfig) -> None:
        super().__init__(TradingMode.LIVE, cfg, transmit_orders=True)


def make_broker(mode: TradingMode, cfg: BrokerConfig) -> TwsBroker:
    if mode == TradingMode.SHADOW:
        return ShadowBroker(cfg)
    if mode == TradingMode.PAPER:
        return PaperBroker(cfg)
    if mode == TradingMode.LIVE:
        return LiveBroker(cfg)
    raise ValueError(f"unknown mode: {mode}")
