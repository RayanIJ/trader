"""Self-contained TWS market-data client (equities + option chains/greeks).

The legacy ``src/ib/TradingApp`` only streams *last* prices and has no option-chain
callbacks. Rather than modify it, this module builds a small, dedicated
``EClient``/``EWrapper`` on its own client id that can:

* fetch 1-min / daily historical bars,
* take a snapshot equity quote (bid/ask/last/volume),
* enumerate option expiries + strikes (``reqSecDefOptParams``), and
* take snapshot option quotes with model greeks for selected strikes.

It is only used when ``market_data.source == "tws"`` and is imported lazily so the
backend boots without ibapi. Everything is wrapped in timeouts and degrades to
``None``/empty so a partial feed never crashes the scanner.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger("broker.mdata")

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ib tick types we care about.
_BID, _ASK, _LAST, _CLOSE = 1, 2, 4, 9
_DELAYED_BID, _DELAYED_ASK, _DELAYED_LAST, _DELAYED_CLOSE = 66, 67, 68, 75
_VOLUME, _DELAYED_VOLUME = 8, 74
_CALL_OI, _PUT_OI = 27, 28
_MODEL_OPTION_COMPUTATION = 13


def _ensure_ibapi_on_path() -> None:
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    sdk = _REPO_ROOT / "IB.1037.02" / "IBJts" / "source" / "pythonclient"
    if sdk.exists() and str(sdk) not in sys.path:
        sys.path.insert(0, str(sdk))


def build_market_data_client():
    """Factory that builds the ibapi-based client class lazily."""
    _ensure_ibapi_on_path()
    from ibapi.client import EClient
    from ibapi.contract import Contract
    from ibapi.wrapper import EWrapper

    class _MarketDataClient(EWrapper, EClient):
        def __init__(self) -> None:
            EClient.__init__(self, self)
            self._req_id = 9000
            self.is_connected_flag = False
            self._thread: threading.Thread | None = None
            self._market_data_type = 1
            self._usopt_warm = False

            # contract details (con_id resolution + option enumeration)
            self._con_id: dict[int, int] = {}
            self._con_done: dict[int, threading.Event] = {}
            self._cdetails: dict[int, list] = {}

            # secdef option params
            self._sec_def: dict[int, dict] = {}
            self._sec_def_done: dict[int, threading.Event] = {}

            # historical bars
            self._bars: dict[int, list] = {}
            self._bars_done: dict[int, threading.Event] = {}

            # snapshot ticks (greeks / volume / open-interest via reqMktData)
            self._ticks: dict[int, dict] = {}
            self._ticks_done: dict[int, threading.Event] = {}

            # tick-by-tick quotes (bid/ask/last). This gateway silently drops
            # streaming reqMktData top-of-book, but tick-by-tick works and also
            # streams during pre-market / post-market / overnight sessions.
            self._tbt: dict[int, tuple[dict, threading.Event]] = {}

        # --- lifecycle ---
        def connect_start(self, host: str, port: int, client_id: int, market_data_type: int = 1) -> bool:
            self._market_data_type = market_data_type
            self.connect(host, port, client_id)
            self._thread = threading.Thread(target=self.run, daemon=True)
            self._thread.start()
            for _ in range(60):
                if self.is_connected_flag:
                    try:
                        self.reqMarketDataType(market_data_type)
                    except Exception:
                        pass
                    return True
                time.sleep(0.1)
            return False

        def nextValidId(self, orderId: int) -> None:  # noqa: N802
            super().nextValidId(orderId)
            self.is_connected_flag = True

        def connectionClosed(self) -> None:  # noqa: N802
            # Reset the flag so the source's _ensure_connected reconnects lazily.
            self.is_connected_flag = False

        def error(self, reqId, errorTime, errorCode, errorString, advancedOrderRejectJson=""):  # noqa: N802
            # 2104/2106/2158 are benign "data farm OK" notices.
            if errorCode in (2104, 2106, 2158, 2107, 2119):
                return
            # End-of-stream / "no data" type errors should release any waiter.
            logger.debug("mdata client error req=%s code=%s %s", reqId, errorCode, errorString)
            for store in (self._bars_done, self._ticks_done, self._sec_def_done, self._con_done):
                ev = store.get(reqId)
                if ev:
                    ev.set()
            tbt = self._tbt.get(reqId)
            if tbt:
                tbt[1].set()

        def _next(self) -> int:
            self._req_id += 1
            return self._req_id

        def disconnect_safe(self) -> None:
            try:
                if self.isConnected():
                    self.disconnect()
            except Exception:
                pass
            self.is_connected_flag = False

        # --- contract details (resolve con_id + enumerate option contracts) ---
        def contractDetails(self, reqId, contractDetails):  # noqa: N802
            k = contractDetails.contract
            try:
                self._con_id.setdefault(reqId, int(k.conId))
            except Exception:
                pass
            self._cdetails.setdefault(reqId, []).append(
                {
                    "con_id": getattr(k, "conId", None),
                    "expiry": getattr(k, "lastTradeDateOrContractMonth", None),
                    "strike": getattr(k, "strike", None),
                    "right": getattr(k, "right", None),
                    "multiplier": getattr(k, "multiplier", None),
                    "trading_class": getattr(k, "tradingClass", None),
                }
            )

        def contractDetailsEnd(self, reqId):  # noqa: N802
            ev = self._con_done.get(reqId)
            if ev:
                ev.set()

        def fetch_con_id(self, contract, timeout: float = 6.0) -> int | None:
            rid = self._next()
            self._con_done[rid] = threading.Event()
            try:
                self.reqContractDetails(rid, contract)
            except Exception:
                logger.exception("reqContractDetails failed")
                self._con_done.pop(rid, None)
                return None
            self._con_done[rid].wait(timeout)
            con_id = self._con_id.pop(rid, None)
            self._cdetails.pop(rid, None)
            self._con_done.pop(rid, None)
            return con_id

        def fetch_contract_details(self, contract, timeout: float = 8.0) -> list[dict]:
            """Return every matching contract definition (expiry/strike/right/conId).

            Used to enumerate option chains: ``reqSecDefOptParams`` is silently
            dropped by this gateway, but bounded ``reqContractDetails`` queries
            (fixed strike+month, or fixed expiry) resolve quickly.
            """
            rid = self._next()
            self._con_done[rid] = threading.Event()
            try:
                self.reqContractDetails(rid, contract)
            except Exception:
                logger.exception("reqContractDetails (enumerate) failed")
                self._con_done.pop(rid, None)
                return []
            self._con_done[rid].wait(timeout)
            data = self._cdetails.pop(rid, [])
            self._con_id.pop(rid, None)
            self._con_done.pop(rid, None)
            return data

        # --- secdef option params (expiries + strikes) ---
        def securityDefinitionOptionalParameter(  # noqa: N802
            self, reqId, exchange, underlyingConId, tradingClass, multiplier, expirations, strikes
        ):
            entry = self._sec_def.setdefault(
                reqId,
                {"expirations": set(), "strikes": set(), "multiplier": multiplier, "trading_class": tradingClass},
            )
            entry["expirations"].update(expirations)
            entry["strikes"].update(strikes)

        def securityDefinitionOptionalParameterEnd(self, reqId):  # noqa: N802
            ev = self._sec_def_done.get(reqId)
            if ev:
                ev.set()

        def fetch_option_params(self, symbol: str, con_id: int, timeout: float = 8.0) -> dict | None:
            rid = self._next()
            self._sec_def_done[rid] = threading.Event()
            self.reqSecDefOptParams(rid, symbol, "", "STK", con_id)
            if not self._sec_def_done[rid].wait(timeout):
                logger.warning("secdef option params timeout for %s", symbol)
            data = self._sec_def.pop(rid, None)
            self._sec_def_done.pop(rid, None)
            if not data:
                return None
            return {
                "expirations": sorted(data["expirations"]),
                "strikes": sorted(float(s) for s in data["strikes"]),
                "multiplier": float(data["multiplier"]) if data["multiplier"] else None,
                "trading_class": data["trading_class"],
            }

        # --- historical bars ---
        def historicalData(self, reqId, bar):  # noqa: N802
            self._bars.setdefault(reqId, []).append(
                {
                    "date": bar.date,
                    "open": float(bar.open),
                    "high": float(bar.high),
                    "low": float(bar.low),
                    "close": float(bar.close),
                    "volume": float(bar.volume) if bar.volume is not None else 0.0,
                }
            )

        def historicalDataEnd(self, reqId, start, end):  # noqa: N802
            ev = self._bars_done.get(reqId)
            if ev:
                ev.set()

        def fetch_bars(
            self, contract, duration: str, bar_size: str, what: str = "TRADES",
            timeout: float = 12.0, use_rth: int = 1,
        ) -> list[dict]:
            rid = self._next()
            self._bars_done[rid] = threading.Event()
            self._bars[rid] = []
            try:
                # use_rth=0 includes pre-market / post-market / overnight bars.
                self.reqHistoricalData(rid, contract, "", duration, bar_size, what, use_rth, 1, False, [])
            except Exception:
                logger.exception("reqHistoricalData failed")
                self._bars_done.pop(rid, None)
                return []
            self._bars_done[rid].wait(timeout)
            data = self._bars.pop(rid, [])
            self._bars_done.pop(rid, None)
            return data

        # --- snapshot ticks (quote + greeks) ---
        def tickPrice(self, reqId, tickType, price, attrib):  # noqa: N802
            if price is None or price < 0:
                return
            d = self._ticks.setdefault(reqId, {})
            if tickType in (_BID, _DELAYED_BID):
                d["bid"] = price
            elif tickType in (_ASK, _DELAYED_ASK):
                d["ask"] = price
            elif tickType in (_LAST, _DELAYED_LAST):
                d["last"] = price
            elif tickType in (_CLOSE, _DELAYED_CLOSE):
                d["close"] = price

        def tickSize(self, reqId, tickType, size):  # noqa: N802
            d = self._ticks.setdefault(reqId, {})
            sz = float(size) if size is not None else 0.0
            if tickType in (_VOLUME, _DELAYED_VOLUME):
                d["volume"] = sz
            elif tickType in (_CALL_OI, _PUT_OI):
                d["open_interest"] = sz

        def tickOptionComputation(  # noqa: N802
            self, reqId, tickType, tickAttrib, impliedVol, delta, optPrice,
            pvDividend, gamma, vega, theta, undPrice,
        ):
            if tickType != _MODEL_OPTION_COMPUTATION:
                return
            d = self._ticks.setdefault(reqId, {})

            def _ok(x):
                return x if (x is not None and x == x and abs(x) < 1e6) else None

            d["iv"] = _ok(impliedVol)
            d["delta"] = _ok(delta)
            d["gamma"] = _ok(gamma)
            d["vega"] = _ok(vega)
            d["theta"] = _ok(theta)

        def tickSnapshotEnd(self, reqId):  # noqa: N802
            ev = self._ticks_done.get(reqId)
            if ev:
                ev.set()

        # --- tick-by-tick quotes (bid/ask/last, incl. extended hours) ---
        def tickByTickBidAsk(  # noqa: N802
            self, reqId, time_, bidPrice, askPrice, bidSize, askSize, tickAttribBidAsk
        ):
            tbt = self._tbt.get(reqId)
            if not tbt:
                return
            store, ev = tbt
            if bidPrice is not None and bidPrice > 0:
                store["bid"] = bidPrice
            if askPrice is not None and askPrice > 0:
                store["ask"] = askPrice
            if "bid" in store and "ask" in store:
                ev.set()

        def tickByTickAllLast(  # noqa: N802
            self, reqId, tickType, time_, price, size, tickAttribLast, exchange, specialConditions
        ):
            tbt = self._tbt.get(reqId)
            if not tbt:
                return
            if price is not None and price > 0:
                tbt[0]["last"] = price

        def _tbt_quote(self, contract, timeout: float) -> dict:
            """Equity/index quote via tick-by-tick (works in extended hours)."""
            store: dict = {}
            ev = threading.Event()
            rid_ba, rid_last = self._next(), self._next()
            self._tbt[rid_ba] = (store, ev)
            self._tbt[rid_last] = (store, ev)
            try:
                # numberOfTicks=0 -> live stream; ignoreSize=True. Routes to the
                # active session (incl. pre/post-market and overnight).
                self.reqTickByTickData(rid_ba, contract, "BidAsk", 0, True)
                self.reqTickByTickData(rid_last, contract, "Last", 0, True)
            except Exception:
                logger.exception("reqTickByTickData failed")
            ev.wait(timeout)
            for rid in (rid_ba, rid_last):
                try:
                    self.cancelTickByTickData(rid)
                except Exception:
                    pass
                self._tbt.pop(rid, None)
            return store

        def _stream_quote(self, contract, timeout: float) -> dict:
            """Streaming reqMktData quote (indices + anything tick-by-tick rejects)."""
            rid = self._next()
            self._ticks[rid] = {}
            try:
                self.reqMktData(rid, contract, "", False, False, [])
            except Exception:
                logger.exception("reqMktData (stream quote) failed")
                return {}
            time.sleep(timeout)
            data = self._ticks.pop(rid, {})
            try:
                self.cancelMktData(rid)
            except Exception:
                pass
            return data

        def fetch_quote(self, contract, with_greeks: bool = False, timeout: float = 3.0) -> dict:
            """Real-time quote for a single contract.

            Equities use tick-by-tick (extended-hours capable). Indices (SPX/VIX)
            and options reject tick-by-tick on this gateway (error 10189) and must
            use streaming reqMktData instead.
            """
            if with_greeks:
                return self.fetch_option_quotes([contract], timeout=max(timeout, 6.0))[0]
            sec = getattr(contract, "secType", "")
            if sec == "IND":
                return self._stream_quote(contract, timeout)
            return self._tbt_quote(contract, timeout)

        def fetch_option_quotes(self, contracts: list, timeout: float = 4.0) -> list[dict]:
            """Batch streaming reqMktData for option contracts (bid/ask/last/greeks).

            Streaming (snapshot=False) is used rather than one-shot snapshots: it
            reliably captures data even while the ``usopt`` OPRA farm is still
            connecting on the first request of a session. All lines are opened at
            once and cancelled after one wait window, so a full chain resolves in
            ~one ``timeout`` regardless of strike count.
            """
            if not contracts:
                return []
            # The first option request of a session wakes the usopt farm; give it
            # extra time so the initial chain isn't empty.
            if not self._usopt_warm:
                timeout = max(timeout, 6.0)
                self._usopt_warm = True
            rids: list[int] = []
            for c in contracts:
                rid = self._next()
                self._ticks[rid] = {}
                try:
                    self.reqMktData(rid, c, "100,101", False, False, [])
                except Exception:
                    logger.exception("reqMktData (option) failed")
                rids.append(rid)
            time.sleep(timeout)
            out: list[dict] = []
            for rid in rids:
                out.append(self._ticks.pop(rid, {}))
                try:
                    self.cancelMktData(rid)
                except Exception:
                    pass
            return out

    return _MarketDataClient, Contract
