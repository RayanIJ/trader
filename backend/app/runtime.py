"""Application runtime container.

Holds the long-lived singletons (config manager, secret store, mode manager,
health monitor) and a background poller that periodically refreshes broker +
health status and publishes to the event bus. This is the composition root —
modules never import each other's singletons; they receive what they need.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from app.config.manager import ConfigManager
from app.config.secrets import SecretStore
from app.core.enums import HealthStatus, TradingMode
from app.core.events import Topic, bus
from app.core.logging import get_logger
from app.db.models import ConfigurationVersion
from app.db.session import get_session, init_db
from app.execution.engine import ExecutionEngine
from app.execution.position_manager import PositionManager
from app.health.monitor import HealthMonitor
from app.journal.service import JournalService
from app.journal.summary import build_daily_summary, get_daily_summary
from app.llm.engine import LLMGuidanceEngine
from app.macro.calendar import MacroGuard
from app.macro.calendar_provider import make_calendar_provider
from app.macro.release_monitor import ReleaseMonitor
from app.macro.store import refresh_guard
from app.market_data.factory import make_market_data_source
from app.modes.manager import ModeManager
from app.persistence.trades import TradeStore
from app.risk.day_state import TradingDayState
from app.risk.engine import RiskEngine
from app.scanner.engine import ScanResult, ScannerEngine
from app.signals.engine import SignalEngine

logger = get_logger("runtime")

# Data directory lives at <repo_root>/data (sibling of backend/ and src/).
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


class Runtime:
    def __init__(self) -> None:
        self.config_manager = ConfigManager()
        self.secrets = SecretStore(DATA_DIR)
        cfg = self.config_manager.config
        self.mode_manager = ModeManager(cfg.broker, default_mode=cfg.default_mode)
        self.journal = JournalService(mode_fn=lambda: self.mode_manager.mode.value)
        self.trade_store = TradeStore(mode_fn=lambda: self.mode_manager.mode.value)
        self.health_monitor = HealthMonitor(cfg.data_quality)
        self.market_data = make_market_data_source(cfg)
        self.macro_guard = MacroGuard(cfg.macro)
        self.day_state = TradingDayState.for_today()
        self.signal_engine = SignalEngine(cfg)
        self.risk_engine = RiskEngine(cfg)
        self.position_manager = PositionManager(self.day_state)
        self.execution = ExecutionEngine(
            cfg,
            self.mode_manager,
            self.day_state,
            self.macro_guard,
            self.position_manager,
            market_data=self.market_data,
            journal=self.journal,
            trade_store=self.trade_store,
        )
        self.scanner = ScannerEngine(
            cfg,
            self.market_data,
            signal_engine=self.signal_engine,
            risk_engine=self.risk_engine,
            macro_guard=self.macro_guard,
            day_state=self.day_state,
        )
        self.latest_scan: ScanResult | None = None
        self._poll_task: asyncio.Task | None = None
        self._scan_task: asyncio.Task | None = None
        self._exec_task: asyncio.Task | None = None
        self._llm_task: asyncio.Task | None = None
        self._release_task: asyncio.Task | None = None
        self._poll_interval = 5.0

        # LLM guidance subsystem.
        llm_provider = cfg.llm.provider if cfg.llm.enabled else "stub"
        self.llm_engine = LLMGuidanceEngine(self, provider=llm_provider)
        self.calendar_provider = make_calendar_provider(cfg.macro.calendar_provider)
        self.release_monitor = ReleaseMonitor(update_delays=cfg.macro.release_update_delays)
        self._latest_release_event: dict | None = None
        self._latest_release_reaction: dict | None = None

        # Session supervisor: once the user connects, we keep the broker session
        # alive — if it drops (socket close, farm break, competing login), we
        # re-initiate a new session automatically with simple backoff.
        self._want_connected = False
        self._last_reconnect_ts = 0.0
        self._reconnect_min_interval = 10.0
        self._eod_summary_built_for: str | None = None

    @property
    def config(self):
        return self.config_manager.config

    async def startup(self) -> None:
        init_db(DATA_DIR)
        self._record_config_version(note="startup")
        macro_count = refresh_guard(self.macro_guard)
        await self.journal.subscribe_bus()
        await self.journal.record_async(
            "STARTUP",
            {"market_data": self.market_data.name, "macro_events": macro_count},
        )
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._scan_task = asyncio.create_task(self._scan_loop())
        self._exec_task = asyncio.create_task(self._execution_loop())
        self._llm_task = asyncio.create_task(self._llm_guidance_loop())
        self._release_task = asyncio.create_task(self._release_monitor_loop())
        # Fetch today's macro calendar once at startup.
        asyncio.create_task(self._fetch_daily_calendar())
        logger.info(
            "runtime started (mode=%s, market_data=%s, llm=%s)",
            self.mode_manager.mode.value, self.market_data.name,
            "enabled" if cfg.llm.enabled else "stub",
        )

    async def shutdown(self) -> None:
        for task in (self._poll_task, self._scan_task, self._exec_task, self._llm_task, self._release_task):
            if task:
                task.cancel()
        await self.mode_manager.broker.disconnect()
        try:
            await self.market_data.close()
        except Exception:
            logger.debug("market data close failed", exc_info=True)
        logger.info("runtime stopped")

    def _record_config_version(self, note: str | None = None) -> None:
        try:
            with get_session() as s:
                s.add(
                    ConfigurationVersion(
                        version_hash=self.config_manager.version_hash,
                        payload=self.config.model_dump(mode="json"),
                        is_active=True,
                        note=note,
                    )
                )
                s.commit()
        except Exception:
            logger.exception("failed to record config version")

    def mark_connected(self) -> None:
        """Record that the user intends the broker session to stay up."""
        self._want_connected = True

    def mark_disconnected(self) -> None:
        self._want_connected = False

    async def _supervise_session(self, broker_status) -> None:
        """Re-initiate a broker session if it has dropped but should be up."""
        if not self._want_connected:
            return
        # A session is considered broken if the socket is down OR the gateway
        # lost its market-data farm link while we believe we're connected.
        broken = (not broker_status.session_connected) or (
            broker_status.session_connected and not broker_status.data_farm_ok
        )
        if not broken:
            return
        import time as _time

        now = _time.monotonic()
        if now - self._last_reconnect_ts < self._reconnect_min_interval:
            return
        self._last_reconnect_ts = now
        logger.warning(
            "broker session broken (connected=%s farm_ok=%s) — re-initiating session",
            broker_status.session_connected, broker_status.data_farm_ok,
        )
        try:
            # Drop the stale connection first so the gateway frees the client id,
            # then establish a fresh session.
            await self.mode_manager.broker.disconnect()
            await self.mode_manager.broker.connect()
        except Exception:
            logger.exception("session re-initiation failed")

    async def refresh_status(self):
        """Pull broker status, evaluate health, publish. Re-initiates a dropped
        session and auto-drops to safe mode if a live/paper session degrades."""
        broker_status = await self.mode_manager.broker.status()
        await self._supervise_session(broker_status)
        report = await self.health_monitor.evaluate_and_publish(broker_status)
        if (
            self.mode_manager.mode != TradingMode.SHADOW
            and report.overall == HealthStatus.DOWN
        ):
            await self.mode_manager.force_safe_mode(
                "system health DOWN — dropped to Shadow for safety"
            )
            await self.journal.record_async(
                "LOCKOUT",
                {"reason": "system health DOWN — dropped to Shadow for safety"},
            )
        await self._maybe_build_eod_summary()
        return broker_status, report

    async def _maybe_build_eod_summary(self) -> None:
        """Build end-of-day summary once after 21:00 UTC if not already done."""
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        trade_date = now.strftime("%Y-%m-%d")
        if now.hour < 21 or self._eod_summary_built_for == trade_date:
            return
        if get_daily_summary(trade_date) is not None:
            self._eod_summary_built_for = trade_date
            return
        build_daily_summary(trade_date)
        self._eod_summary_built_for = trade_date
        await self.journal.record_async("EOD_SUMMARY", {"trade_date": trade_date})

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.refresh_status()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("status poll failed")
            await asyncio.sleep(self._poll_interval)

    async def run_scan(self) -> ScanResult:
        """Run one scan, cache it, and publish to the event bus."""
        broker_status = await self.mode_manager.broker.status()
        report = self.health_monitor.evaluate(broker_status)
        health_ok = report.overall.value in ("OK", "DEGRADED")
        data_live = broker_status.data_feed.value == "LIVE" or not self.config.data_quality.require_live_data
        result = await self.scanner.scan(
            health_ok=health_ok,
            broker_tradable=broker_status.is_tradable,
            data_feed_live=data_live,
        )
        self.latest_scan = result
        await bus.publish(Topic.SCANNER, result.to_dict())
        approved = [c for c in result.candidates if c.approved]
        if approved:
            await self.journal.record_async(
                "SCAN",
                {
                    "asof": result.asof.isoformat(),
                    "source": result.source,
                    "candidates": len(result.candidates),
                    "approved": len(approved),
                    "top": [
                        {"symbol": c.symbol, "direction": c.direction, "score": c.score}
                        for c in sorted(approved, key=lambda x: x.score, reverse=True)[:5]
                    ],
                },
            )
        for c in result.candidates:
            if c.signal_ok and not c.approved and c.reject_codes:
                await self.journal.record_async(
                    "REJECT",
                    {"reject_codes": c.reject_codes, "score": c.score, "signal_type": c.signal_type},
                    symbol=c.symbol,
                )
        for c in approved[:3]:
            await self.journal.record_async(
                "SIGNAL",
                {
                    "direction": c.direction,
                    "signal_type": c.signal_type,
                    "score": c.score,
                    "band": c.band,
                    "reject_codes": c.reject_codes,
                },
                symbol=c.symbol,
            )
        return result

    async def _execution_loop(self) -> None:
        await asyncio.sleep(2.0)
        while True:
            try:
                broker_status = await self.mode_manager.broker.status()
                report = self.health_monitor.evaluate(broker_status)
                health_ok = report.overall.value in ("OK", "DEGRADED")
                await self.execution.tick(
                    self.latest_scan,
                    health_ok=health_ok,
                    broker_tradable=broker_status.is_tradable,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("execution tick failed")
            await asyncio.sleep(self.config.market_data.scan_interval_sec)

    async def _scan_loop(self) -> None:
        # Stagger slightly after startup so the first health poll lands first.
        await asyncio.sleep(1.0)
        while True:
            try:
                await self.run_scan()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scan failed")
            await asyncio.sleep(self.config.market_data.scan_interval_sec)

    async def _llm_guidance_loop(self) -> None:
        """Periodic LLM guidance — default every 5 minutes."""
        await asyncio.sleep(3.0)  # Let other subsystems warm up first.
        interval = self.config.llm.guidance_interval_sec
        while True:
            try:
                await self.llm_engine.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("LLM guidance tick failed")
            await asyncio.sleep(interval)

    async def _release_monitor_loop(self) -> None:
        """Check for macro releases that need updates every 60 seconds."""
        await asyncio.sleep(5.0)
        while True:
            try:
                self.release_monitor.check_release_windows()
                needing = self.release_monitor.get_events_needing_update()
                for event, delay in needing:
                    logger.info(
                        "release update needed: %s delay=%dmin", event.event_id, delay,
                    )
                    # In the future, this would fetch from a real provider.
                    # For now, record the attempt without actual data.
                    self.release_monitor.record_update(event, delay)

                # Publish latest release to event bus for dashboard.
                latest = self.release_monitor.get_latest_released()
                if latest:
                    self._latest_release_event = latest.model_dump()
                    await bus.publish(Topic.MACRO_CALENDAR, {
                        "latest_release": latest.model_dump(),
                    })
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("release monitor tick failed")
            await asyncio.sleep(60.0)

    async def _fetch_daily_calendar(self) -> None:
        """Fetch today's macro calendar once at startup."""
        try:
            cal = await self.calendar_provider.fetch_daily()
            self.release_monitor.set_calendar(cal)
            await self.journal.record_async("MACRO_CALENDAR_FETCHED", {
                "date_et": cal.date_et,
                "event_count": len(cal.events),
                "provider": cal.provider,
            })
            logger.info(
                "daily macro calendar fetched: %d events (provider=%s)",
                len(cal.events), cal.provider,
            )
        except Exception:
            logger.exception("failed to fetch daily macro calendar")


# Module-level holder set during app lifespan.
runtime: Runtime | None = None


def get_runtime() -> Runtime:
    if runtime is None:
        raise RuntimeError("runtime not initialized")
    return runtime
