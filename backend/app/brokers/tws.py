"""TWS socket-API transport, wrapping the existing ``src/ib`` TradingApp.

We deliberately reuse the legacy ``EClient/EWrapper`` wrapper as-is (it already
handles connect/retry, account summary, positions, market-data-type downgrade on
error 10089, and order placement). ``ibapi`` is imported lazily so the backend
boots without the legacy module's import-time dependencies (e.g. OpenAI key).

All blocking ibapi calls are dispatched off the event loop via ``asyncio.to_thread``.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

from app.brokers.adapter import (
    BrokerAdapter,
    BrokerStatus,
    ShadowModeError,
    probe_gateway,
)
from app.config.schema import BrokerConfig
from app.core.enums import DataFeedStatus, TradingMode
from app.core.logging import get_logger, mask_account

logger = get_logger("broker.tws")

# Repo root = backend/ parent. The legacy package lives at <root>/src and the
# bundled IB SDK at <root>/IB.1037.02/...
_REPO_ROOT = Path(__file__).resolve().parents[3]

_DATA_FEED_BY_TYPE = {
    1: DataFeedStatus.LIVE,
    2: DataFeedStatus.FROZEN,
    3: DataFeedStatus.DELAYED,
    4: DataFeedStatus.DELAYED,
}


class TwsBroker(BrokerAdapter):
    """Real TWS socket transport. Mode controls whether orders transmit."""

    def __init__(self, mode: TradingMode, cfg: BrokerConfig, *, transmit_orders: bool) -> None:
        self.mode = mode
        self._cfg = cfg
        self._transmit_orders = transmit_orders
        self._app: Any = None  # legacy TradingApp instance (lazy)
        self._lock = asyncio.Lock()

    @property
    def _port(self) -> int:
        if self.mode == TradingMode.PAPER:
            return self._cfg.paper_port
        # LIVE and SHADOW share the live API socket. Shadow never transmits orders
        # but still needs a live gateway session for status, account, and data.
        return self._cfg.live_port

    def _import_trading_app(self):
        """Lazy import of the legacy TradingApp + IB SDK path injection."""
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        sdk_path = _REPO_ROOT / "IB.1037.02" / "IBJts" / "source" / "pythonclient"
        if sdk_path.exists() and str(sdk_path) not in sys.path:
            sys.path.insert(0, str(sdk_path))
        from src.ib.trading_app import TradingApp  # noqa: WPS433 (lazy by design)

        return TradingApp

    @staticmethod
    def _install_account_capture(app: Any) -> None:
        """Capture the account id from the ``managedAccounts`` handshake message.

        The legacy TradingApp only sets ``account_id`` during a portfolio snapshot,
        so a bare connect would leave ``account_available`` false (blocking Live).
        We wrap the instance's ``managedAccounts`` to record the first account id
        as soon as it arrives, without modifying the legacy module.
        """
        orig = getattr(app, "managedAccounts", None)

        def managed(accounts_list: str) -> None:
            if callable(orig):
                try:
                    orig(accounts_list)
                except Exception:  # pragma: no cover - legacy handler is a no-op
                    pass
            if accounts_list:
                first = accounts_list.split(",")[0].strip()
                if first and not getattr(app, "account_id", None):
                    app.account_id = first

        app.managedAccounts = managed

    @staticmethod
    def _install_session_capture(app: Any) -> None:
        """Track true connectivity + market-data-farm health on the app instance.

        The legacy app sets ``is_connected=True`` on connect but never clears it,
        so a dropped socket would look healthy. We wrap ``connectionClosed`` and
        ``error`` to maintain ``is_connected`` and a ``data_farm_ok`` flag from the
        IB connectivity/farm status codes — the supervisor uses these to detect a
        broken session and re-initiate one.
        """
        app.data_farm_ok = True
        orig_closed = getattr(app, "connectionClosed", None)
        orig_error = getattr(app, "error", None)

        def connection_closed() -> None:
            app.is_connected = False
            app.data_farm_ok = False
            if callable(orig_closed):
                try:
                    orig_closed()
                except Exception:  # pragma: no cover
                    pass

        def error(req_id, error_time, code, msg, *args, **kwargs) -> None:
            # Market-data / HMDS farm connectivity status codes.
            if code in (2103, 2105, 2110, 2157):     # broken / connectivity lost
                app.data_farm_ok = False
            elif code in (2104, 2106, 2108, 2158):    # farm OK / inactive-but-available
                app.data_farm_ok = True
            elif code == 1100:                        # connectivity to TWS lost
                app.is_connected = False
                app.data_farm_ok = False
            elif code in (1101, 1102):                # connectivity restored
                app.is_connected = True
            if callable(orig_error):
                try:
                    orig_error(req_id, error_time, code, msg, *args, **kwargs)
                except Exception:  # pragma: no cover
                    pass

        app.connectionClosed = connection_closed
        app.error = error

    @staticmethod
    def _install_order_tracker(app: Any) -> None:
        """Track order status + completion events for fill waits."""
        import threading

        app._order_final: dict[int, dict] = {}
        app._order_events: dict[int, threading.Event] = {}
        orig = getattr(app, "orderStatus", None)

        def order_status(
            order_id, status, filled, remaining, avg_fill_price,
            perm_id, parent_id, last_fill_price, client_id, why_held, mkt_cap_price,
        ) -> None:
            entry = {
                "status": status,
                "filled": float(filled or 0),
                "remaining": float(remaining or 0),
                "avg_fill_price": float(avg_fill_price or 0),
            }
            app._order_final[int(order_id)] = entry
            ev = app._order_events.get(int(order_id))
            if ev and status in ("Filled", "Cancelled", "Inactive", "ApiCancelled"):
                ev.set()
            if callable(orig):
                try:
                    orig(
                        order_id, status, filled, remaining, avg_fill_price,
                        perm_id, parent_id, last_fill_price, client_id, why_held, mkt_cap_price,
                    )
                except Exception:
                    pass

        app.orderStatus = order_status

    def _connect_blocking(self) -> BrokerStatus:
        status = BrokerStatus(mode=self.mode)
        status.gateway_reachable = probe_gateway(self._cfg.host, self._port)
        if not status.gateway_reachable:
            status.last_error = (
                f"TWS/Gateway not reachable at {self._cfg.host}:{self._port}. "
                "Start TWS/IB Gateway and enable the API socket."
            )
            return status
        try:
            TradingApp = self._import_trading_app()
            if self._app is None:
                self._app = TradingApp()
                self._install_account_capture(self._app)
                self._install_session_capture(self._app)
                self._install_order_tracker(self._app)
            if not getattr(self._app, "is_connected", False):
                self._app.connect_and_start(
                    host=self._cfg.host, port=self._port, client_id=self._cfg.client_id
                )
            try:
                self._app.reqMarketDataType(self._cfg.market_data_type)
            except Exception:  # non-fatal; status will reflect it
                logger.debug("reqMarketDataType failed", exc_info=True)
        except Exception as exc:  # connection/import failure -> reported, not raised
            status.last_error = f"connect failed: {exc}"
            logger.error("TWS connect failed: %s", exc)
            return status
        return self._read_status_blocking()

    def _read_status_blocking(self) -> BrokerStatus:
        status = BrokerStatus(mode=self.mode)
        status.gateway_reachable = probe_gateway(self._cfg.host, self._port)
        if not status.gateway_reachable:
            status.last_error = (
                f"No TWS/IB Gateway socket at {self._cfg.host}:{self._port} "
                f"({self.mode.value} mode). Start TWS or IB Gateway, enable "
                "API → 'Enable ActiveX and Socket Clients', and confirm the "
                f"socket port matches {self._port}."
            )
        app = self._app
        if app is None:
            return status
        status.session_connected = bool(getattr(app, "is_connected", False))
        status.next_valid_id_received = getattr(app, "next_valid_order_id", None) is not None
        status.account_id = getattr(app, "account_id", None)
        status.account_available = status.account_id is not None
        status.data_farm_ok = bool(getattr(app, "data_farm_ok", True))
        mdt = self._cfg.market_data_type
        status.market_data_type = mdt
        status.data_feed = _DATA_FEED_BY_TYPE.get(mdt, DataFeedStatus.UNAVAILABLE)
        if not status.session_connected:
            status.data_feed = DataFeedStatus.UNAVAILABLE
        elif not status.data_farm_ok:
            # Connected, but the gateway lost its market-data link to IBKR
            # (commonly a competing session). Treat the feed as stale.
            status.data_feed = DataFeedStatus.STALE
            status.last_error = (
                "market-data farm disconnected (often a competing IBKR login "
                "elsewhere). Close other IBKR sessions; the gateway will reconnect."
            )
        if self.mode == TradingMode.SHADOW:
            status.positions_synced = True
        elif status.session_connected and app is not None:
            status.positions_synced = bool(getattr(app, "_positions_event", None) is None or app._positions_event.is_set())
        return status

    async def connect(self) -> BrokerStatus:
        async with self._lock:
            status = await asyncio.to_thread(self._connect_blocking)
        logger.info(
            "broker connect mode=%s reachable=%s session=%s acct=%s feed=%s",
            self.mode, status.gateway_reachable, status.session_connected,
            mask_account(status.account_id), status.data_feed,
        )
        return status

    async def disconnect(self) -> None:
        async with self._lock:
            app = self._app
            if app is not None and getattr(app, "is_connected", False):
                await asyncio.to_thread(app.disconnect)
            self._app = None

    async def status(self) -> BrokerStatus:
        async with self._lock:
            return await asyncio.to_thread(self._read_status_blocking)

    async def account_summary(self) -> dict[str, Any]:
        if self._app is None or not getattr(self._app, "is_connected", False):
            return {}

        def _fetch() -> dict[str, Any]:
            snap = self._app.get_portfolio_snapshot()
            acct = snap.account
            return {
                "account_id": acct.account_id,
                "net_liquidation": acct.net_liquidation,
                "total_cash_value": acct.total_cash_value,
                "buying_power": acct.buying_power,
                "gross_position_value": acct.gross_position_value,
            }

        async with self._lock:
            return await asyncio.to_thread(_fetch)

    async def positions(self) -> list[dict[str, Any]]:
        if self._app is None or not getattr(self._app, "is_connected", False):
            return []

        def _fetch() -> list[dict[str, Any]]:
            snap = self._app.get_portfolio_snapshot()
            return [
                {
                    "con_id": p.con_id,
                    "symbol": p.symbol,
                    "sec_type": p.sec_type,
                    "quantity": float(p.quantity),
                    "avg_cost": p.avg_cost,
                    "multiplier": p.multiplier,
                    "unrealized_pnl": p.unrealized_pnl,
                }
                for p in snap.positions
            ]

        async with self._lock:
            return await asyncio.to_thread(_fetch)

    def _place_order_blocking(self, req: dict[str, Any]) -> dict[str, Any]:
        import threading
        import time

        from src.ib.contracts import us_option_contract  # noqa: WPS433
        from src.ib.orders import limit_order

        app = self._app
        if app is None or not getattr(app, "is_connected", False):
            raise RuntimeError("broker not connected")

        contract = us_option_contract(
            req["underlying"], req["expiry"], float(req["strike"]), req["right"]
        )
        action = "BUY" if req.get("side") == "BUY_TO_OPEN" else "SELL"
        order = limit_order(action, int(req["quantity"]), float(req["limit_price"]))
        order.tif = "DAY"
        order.outsideRth = True

        oid = app.place_trade(contract, order)
        ev = threading.Event()
        app._order_events[oid] = ev
        timeout = float(req.get("timeout_sec", 5.0))
        ev.wait(timeout)

        final = app._order_final.get(oid, {})
        status = final.get("status", "Submitted")
        filled = int(final.get("filled", 0))
        avg = final.get("avg_fill_price") or None
        if avg == 0:
            avg = None

        state = "SUBMITTED"
        if status == "Filled":
            state = "FILLED"
        elif status in ("Cancelled", "ApiCancelled", "Inactive"):
            state = "CANCELLED"
        elif filled > 0 and final.get("remaining", 0) > 0:
            state = "PARTIALLY_FILLED"

        if state not in ("FILLED", "PARTIALLY_FILLED") and filled == 0:
            try:
                app.cancelOrder(oid)
            except Exception:
                pass
            time.sleep(0.5)

        app._order_events.pop(oid, None)
        return {
            "broker_order_id": oid,
            "state": state,
            "filled_qty": filled,
            "avg_fill_price": avg,
            "message": status,
        }

    async def place_order(self, order_req: dict[str, Any]) -> dict[str, Any]:
        if not self._transmit_orders:
            raise ShadowModeError("order transmission disabled for this mode")
        async with self._lock:
            if self._app is None or not getattr(self._app, "is_connected", False):
                await self.connect()
            return await asyncio.to_thread(self._place_order_blocking, order_req)

    async def cancel_order(self, broker_order_id: int) -> None:
        async with self._lock:
            app = self._app
            if app is not None and getattr(app, "is_connected", False):
                await asyncio.to_thread(app.cancelOrder, broker_order_id)
