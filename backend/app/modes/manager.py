"""Mode manager.

Owns the active :class:`TradingMode` and the broker adapter bound to it. Default
is SHADOW. Switching to LIVE is deliberately hard:

* requires an explicit ``confirm_live=True`` acknowledgement,
* requires the broker session to be tradable (gateway + session + account),
* is refused while a daily lockout is active.

When a lockout, session failure, data failure, or risk breach occurs, callers
invoke :meth:`force_safe_mode` which drops the app back to SHADOW. This is the
single chokepoint that decides whether orders may ever be transmitted.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.brokers.adapter import BrokerStatus
from app.brokers.modes import make_broker
from app.brokers.tws import TwsBroker
from app.config.schema import BrokerConfig
from app.core.enums import TradingMode
from app.core.events import Topic, bus
from app.core.logging import get_logger

logger = get_logger("modes")


def _tradable_failure_reason(status: BrokerStatus) -> str:
    parts: list[str] = []
    if not status.gateway_reachable:
        parts.append(status.last_error or "IB Gateway socket not reachable")
    elif not status.session_connected:
        parts.append("broker not connected — click IBKR Connect and complete 2FA")
    elif not status.next_valid_id_received:
        parts.append("session handshake incomplete (waiting for nextValidId)")
    elif not status.account_available:
        parts.append("no account id from gateway yet")
    if not parts:
        parts.append("pre-trade health check failed")
    return "LIVE blocked: " + "; ".join(parts)


@dataclass
class ModeSwitchResult:
    ok: bool
    mode: TradingMode
    reason: str | None = None


class ModeManager:
    def __init__(self, broker_cfg: BrokerConfig, default_mode: TradingMode = TradingMode.SHADOW) -> None:
        if default_mode == TradingMode.LIVE:
            default_mode = TradingMode.SHADOW  # never default to live
        self._broker_cfg = broker_cfg
        self._mode = default_mode
        self._lockout = False
        self._lockout_reason: str | None = None
        self._broker: TwsBroker = make_broker(self._mode, broker_cfg)

    @property
    def mode(self) -> TradingMode:
        return self._mode

    @property
    def broker(self) -> TwsBroker:
        return self._broker

    @property
    def is_live(self) -> bool:
        return self._mode == TradingMode.LIVE

    @property
    def locked_out(self) -> bool:
        return self._lockout

    @property
    def lockout_reason(self) -> str | None:
        return self._lockout_reason

    async def _emit(self) -> None:
        await bus.publish(
            Topic.MODE,
            {
                "mode": self._mode.value,
                "locked_out": self._lockout,
                "lockout_reason": self._lockout_reason,
            },
        )

    async def switch_mode(
        self,
        target: TradingMode,
        *,
        confirm_live: bool = False,
        broker_status: BrokerStatus | None = None,
    ) -> ModeSwitchResult:
        if target == self._mode:
            return ModeSwitchResult(ok=True, mode=self._mode, reason="already in mode")

        if self._lockout and target != TradingMode.SHADOW:
            return ModeSwitchResult(
                ok=False, mode=self._mode,
                reason=f"locked out: {self._lockout_reason}; only SHADOW allowed",
            )

        if target == TradingMode.LIVE:
            if not confirm_live:
                return ModeSwitchResult(
                    ok=False, mode=self._mode,
                    reason="LIVE requires explicit confirmation (confirm_live=True)",
                )
            status = broker_status or await self._broker.status()
            if not status.is_tradable:
                status = await self._broker.connect()
            if not status.is_tradable:
                return ModeSwitchResult(
                    ok=False, mode=self._mode,
                    reason=_tradable_failure_reason(status),
                )

        # Tear down the old broker, bind a new one for the target mode and
        # connect it immediately. Without an eager reconnect the next health
        # poll would see a disconnected broker and force us back to SHADOW.
        await self._broker.disconnect()
        # Give the gateway a moment to release the client id before reconnecting.
        await asyncio.sleep(0.5)
        self._mode = target
        self._broker = make_broker(target, self._broker_cfg)
        logger.warning("MODE SWITCH -> %s", target.value)

        if target != TradingMode.SHADOW:
            new_status = await self._broker.connect()
            if target == TradingMode.LIVE and not new_status.is_tradable:
                # Could not re-establish a tradable LIVE session; roll back safely.
                await self._broker.disconnect()
                self._mode = TradingMode.SHADOW
                self._broker = make_broker(TradingMode.SHADOW, self._broker_cfg)
                await self._broker.connect()
                await self._emit()
                return ModeSwitchResult(
                    ok=False, mode=self._mode,
                    reason=(
                        "LIVE session did not become tradable after connect: "
                        f"{new_status.last_error or 'session not ready'}"
                    ),
                )

        await self._emit()
        return ModeSwitchResult(ok=True, mode=self._mode)

    async def force_safe_mode(self, reason: str) -> None:
        """Drop to SHADOW and raise a session lockout (non-bypassable until reset)."""
        self._lockout = True
        self._lockout_reason = reason
        if self._mode != TradingMode.SHADOW:
            await self._broker.disconnect()
            self._mode = TradingMode.SHADOW
            self._broker = make_broker(TradingMode.SHADOW, self._broker_cfg)
        logger.critical("FORCED SAFE MODE (SHADOW): %s", reason)
        await self._emit()

    def clear_lockout(self) -> None:
        """Manual reset, intended for a new trading session (not mid-session)."""
        self._lockout = False
        self._lockout_reason = None
        logger.info("lockout cleared")
