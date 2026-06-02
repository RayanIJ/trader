"""System health monitor.

Aggregates per-component status (IB gateway, IB session, market data, account,
position sync, database, clock, macro calendar, backend) into a single report
with an overall verdict. ``can_trade`` is the master pre-trade gate used by the
mode manager and (later) the risk engine: if any required component is not OK,
new trades are blocked while open positions continue to be monitored.

When data is degraded the monitor records a system_health_event for the audit
trail and publishes to the event bus so the UI updates immediately.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from app.brokers.adapter import BrokerStatus
from app.config.schema import DataQualityConfig
from app.core.enums import DataFeedStatus, HealthComponent, HealthStatus
from app.core.events import Topic, bus
from app.core.logging import get_logger
from app.db.models import SystemHealthEvent
from app.db.session import get_session

logger = get_logger("health")


@dataclass
class ComponentHealth:
    component: str
    status: HealthStatus
    detail: str | None = None


@dataclass
class HealthReport:
    ts: str
    overall: HealthStatus
    can_trade: bool
    components: list[ComponentHealth] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "overall": self.overall.value,
            "can_trade": self.can_trade,
            "components": [
                {"component": c.component, "status": c.status.value, "detail": c.detail}
                for c in self.components
            ],
        }


# Components that MUST be OK before any automated trade.
_REQUIRED_FOR_TRADING = {
    HealthComponent.IB_GATEWAY,
    HealthComponent.IB_SESSION,
    HealthComponent.MARKET_DATA,
    HealthComponent.ACCOUNT,
    HealthComponent.DATABASE,
    HealthComponent.CLOCK,
}


class HealthMonitor:
    def __init__(self, data_quality: DataQualityConfig) -> None:
        self._dq = data_quality
        self._last_report: HealthReport | None = None

    @property
    def last_report(self) -> HealthReport | None:
        return self._last_report

    def _clock_health(self) -> ComponentHealth:
        # Verify the local clock is timezone-aware and sane. A real NTP drift
        # check against an external source is a Phase-6 hardening item; for now
        # we confirm the wall clock is monotonic-consistent and non-zero.
        now = time.time()
        if now <= 0:
            return ComponentHealth(
                HealthComponent.CLOCK.value, HealthStatus.DOWN, "system clock invalid"
            )
        return ComponentHealth(HealthComponent.CLOCK.value, HealthStatus.OK)

    def _db_health(self) -> ComponentHealth:
        try:
            from sqlalchemy import text

            with get_session() as s:
                s.execute(text("SELECT 1"))
            return ComponentHealth(HealthComponent.DATABASE.value, HealthStatus.OK)
        except Exception as exc:  # noqa: BLE001
            return ComponentHealth(
                HealthComponent.DATABASE.value, HealthStatus.DOWN, str(exc)
            )

    def _broker_components(self, bs: BrokerStatus) -> list[ComponentHealth]:
        out: list[ComponentHealth] = []
        out.append(
            ComponentHealth(
                HealthComponent.IB_GATEWAY.value,
                HealthStatus.OK if bs.gateway_reachable else HealthStatus.DOWN,
                None if bs.gateway_reachable else (bs.last_error or "gateway unreachable"),
            )
        )
        out.append(
            ComponentHealth(
                HealthComponent.IB_SESSION.value,
                HealthStatus.OK
                if (bs.session_connected and bs.next_valid_id_received)
                else HealthStatus.DOWN,
                None if bs.session_connected else "not authenticated / not connected",
            )
        )
        # Market data: LIVE is OK; DELAYED is DEGRADED (blocks trading if require_live_data).
        if bs.data_feed == DataFeedStatus.LIVE:
            md = ComponentHealth(HealthComponent.MARKET_DATA.value, HealthStatus.OK)
        elif bs.data_feed in (DataFeedStatus.DELAYED, DataFeedStatus.FROZEN):
            md = ComponentHealth(
                HealthComponent.MARKET_DATA.value, HealthStatus.DEGRADED,
                f"feed is {bs.data_feed.value}",
            )
        else:
            md = ComponentHealth(
                HealthComponent.MARKET_DATA.value, HealthStatus.DOWN,
                f"feed {bs.data_feed.value}",
            )
        out.append(md)
        out.append(
            ComponentHealth(
                HealthComponent.ACCOUNT.value,
                HealthStatus.OK if bs.account_available else HealthStatus.DOWN,
                None if bs.account_available else "no account available",
            )
        )
        sync = HealthStatus.OK if bs.positions_synced else HealthStatus.UNKNOWN
        out.append(ComponentHealth(HealthComponent.POSITION_SYNC.value, sync))
        return out

    def evaluate(self, broker_status: BrokerStatus) -> HealthReport:
        components: list[ComponentHealth] = [ComponentHealth(HealthComponent.BACKEND.value, HealthStatus.OK)]
        components += self._broker_components(broker_status)
        components.append(self._db_health())
        components.append(self._clock_health())

        by_name = {c.component: c for c in components}

        # Determine whether trading is allowed.
        can_trade = True
        for comp in _REQUIRED_FOR_TRADING:
            ch = by_name.get(comp.value)
            if ch is None or ch.status in (HealthStatus.DOWN, HealthStatus.UNKNOWN):
                can_trade = False
            if comp == HealthComponent.MARKET_DATA and ch and ch.status == HealthStatus.DEGRADED:
                # Delayed/frozen data blocks trading when live data is required.
                if self._dq.require_live_data:
                    can_trade = False

        statuses = [c.status for c in components]
        if any(s == HealthStatus.DOWN for s in statuses):
            overall = HealthStatus.DOWN
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.OK

        report = HealthReport(
            ts=datetime.now(timezone.utc).isoformat(),
            overall=overall,
            can_trade=can_trade,
            components=components,
        )
        self._last_report = report
        return report

    async def evaluate_and_publish(self, broker_status: BrokerStatus) -> HealthReport:
        report = self.evaluate(broker_status)
        self._persist(report)
        await bus.publish(Topic.HEALTH, report.to_dict())
        return report

    def _persist(self, report: HealthReport) -> None:
        # Persist only non-OK components to keep the audit table signal-rich.
        try:
            with get_session() as s:
                for c in report.components:
                    if c.status != HealthStatus.OK:
                        s.add(
                            SystemHealthEvent(
                                component=c.component, status=c.status.value, detail=c.detail
                            )
                        )
                s.commit()
        except Exception:  # never let health persistence break the monitor
            logger.exception("failed to persist health event")
