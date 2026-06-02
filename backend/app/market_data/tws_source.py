"""Live TWS market-data source.

Implements :class:`MarketDataSource` on top of the dedicated market-data client
(``app.brokers.options_client``). It connects on its own client id (broker
``client_id + 20``) so it never interferes with the trading session, and caches
contract ids + option params briefly to keep the per-scan request volume sane.

Designed to degrade gracefully: any failed/timeouted request returns ``None`` or
an empty result, so the scanner simply marks the symbol with a reason code rather
than crashing. Greeks/quotes require live OPRA data and an active market session;
outside RTH the chain may come back empty.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from app.brokers.options_client import build_market_data_client
from app.config.schema import BrokerConfig, MarketDataConfig
from app.core.enums import DataFeedStatus, OptionRight
from app.core.logging import get_logger
from app.market_data.models import (
    Candle,
    OptionChain,
    OptionContractSpec,
    OptionQuote,
    Quote,
    ReferenceLevels,
)
from app.market_data.source import MarketDataSource

logger = get_logger("mdata.tws")

_FEED_BY_TYPE = {1: DataFeedStatus.LIVE, 2: DataFeedStatus.FROZEN, 3: DataFeedStatus.DELAYED, 4: DataFeedStatus.DELAYED}
# How many strikes either side of spot to actually quote (keeps request count low).
_STRIKES_PER_SIDE = 4
_CHAIN_TTL_SEC = 30.0
_CONID_TTL_SEC = 3600.0

# Historical-data caching + pacing. IB throttles historical requests to ~60 per
# 10 minutes; exceeding it triggers pacing violations / disconnects. Live snapshot
# quotes (the displayed price) are NOT historical and are fetched every scan, so
# prices stay real-time while candles/refs are cached behind a rate limiter.
_CANDLE_TTL_SEC = 45.0
_REFS_TTL_SEC = 300.0
_AVGVOL_TTL_SEC = 900.0
_HIST_WINDOW_SEC = 600.0
_HIST_MAX_PER_WINDOW = 50
_HIST_MIN_SPACING_SEC = 0.25


class _HistoricalRateLimiter:
    """Token-aware limiter for IB historical-data requests (thread-safe)."""

    def __init__(self) -> None:
        self._times: deque[float] = deque()
        self._last: float = 0.0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = time.monotonic()
        with self._lock:
            while self._times and now - self._times[0] > _HIST_WINDOW_SEC:
                self._times.popleft()
            if len(self._times) >= _HIST_MAX_PER_WINDOW:
                return False
            if now - self._last < _HIST_MIN_SPACING_SEC:
                return False
            self._times.append(now)
            self._last = now
            return True


def _parse_bar_ts(raw) -> datetime:
    """Parse an ib historical bar date into a UTC datetime.

    formatDate=1 yields 'YYYYMMDD  HH:MM:SS' (intraday) or 'YYYYMMDD' (daily),
    sometimes with a trailing timezone. Falls back to now() on parse failure.
    """
    s = str(raw).strip()
    # Strip a trailing timezone token if present (e.g. 'US/Eastern').
    parts = s.split()
    try:
        if len(parts) >= 2 and len(parts[0]) == 8 and ":" in parts[1]:
            dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%Y%m%d %H:%M:%S")
            return dt.replace(tzinfo=timezone.utc)
        if len(parts[0]) == 8:
            dt = datetime.strptime(parts[0], "%Y%m%d")
            return dt.replace(tzinfo=timezone.utc)
        # epoch seconds form
        return datetime.fromtimestamp(int(s), tz=timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


class TwsMarketDataSource(MarketDataSource):
    name = "tws"

    def __init__(self, cfg: BrokerConfig, md_cfg: MarketDataConfig) -> None:
        self._cfg = cfg
        self._md = md_cfg
        self._client = None
        self._Contract = None
        self._lock = asyncio.Lock()
        self._con_id_cache: dict[str, tuple[int | None, float]] = {}
        self._params_cache: dict[str, tuple[dict | None, float]] = {}
        self._candle_cache: dict[str, tuple[list[Candle], float]] = {}
        self._refs_cache: dict[str, tuple[ReferenceLevels, float]] = {}
        self._avgvol_cache: dict[str, tuple[float | None, float]] = {}
        self._chain_cache: dict[str, tuple[OptionChain | None, float]] = {}
        self._hist = _HistoricalRateLimiter()

    @property
    def _client_id(self) -> int:
        return self._cfg.client_id + 20

    @property
    def _port(self) -> int:
        # Market data works in any mode; prefer the live relay port.
        return self._cfg.live_port

    def _ensure_connected_blocking(self) -> bool:
        if self._client is not None and getattr(self._client, "is_connected_flag", False):
            return True
        Client, Contract = build_market_data_client()
        self._Contract = Contract
        self._client = Client()
        ok = self._client.connect_start(
            self._cfg.host, self._port, self._client_id, self._md_market_data_type()
        )
        if not ok:
            logger.warning("TWS market-data client failed to connect at %s:%s", self._cfg.host, self._port)
        return ok

    def _md_market_data_type(self) -> int:
        return self._cfg.market_data_type

    def _stock(self, symbol: str):
        c = self._Contract()
        c.symbol = symbol.upper()
        c.secType = "IND" if symbol.upper() == "SPX" else "STK"
        c.currency = "USD"
        c.exchange = "CBOE" if symbol.upper() in ("SPX", "VIX") else "SMART"
        return c

    def _option(self, symbol: str, expiry: str, strike: float, right: OptionRight):
        c = self._Contract()
        c.symbol = symbol.upper()
        c.secType = "OPT"
        c.currency = "USD"
        c.exchange = "SMART"
        c.lastTradeDateOrContractMonth = expiry
        c.strike = strike
        c.right = right.value
        c.multiplier = "100"
        return c

    # ----------------------------------------------------------------- candles
    def _candles_blocking(self, symbol: str, lookback: int) -> list[Candle]:
        cached = self._candle_cache.get(symbol)
        now = time.time()
        if cached and now - cached[1] < _CANDLE_TTL_SEC:
            return cached[0]
        if not self._ensure_connected_blocking() or not self._hist.allow():
            # Throttled or disconnected: serve last known candles (possibly stale).
            return cached[0] if cached else []
        minutes = max(lookback, 30)
        duration = f"{max(minutes * 60, 3600)} S" if minutes <= 480 else "2 D"
        # use_rth=0 keeps pre-market / post-market / overnight bars in the series.
        bars = self._client.fetch_bars(self._stock(symbol), duration, "1 min", "TRADES", use_rth=0)
        out: list[Candle] = []
        for b in bars[-lookback:]:
            out.append(
                Candle(
                    ts=_parse_bar_ts(b["date"]),
                    open=b["open"], high=b["high"], low=b["low"], close=b["close"],
                    volume=b["volume"],
                )
            )
        if out:
            self._candle_cache[symbol] = (out, now)
            return out
        return cached[0] if cached else []

    async def get_candles_1m(self, symbol: str, lookback: int) -> list[Candle]:
        async with self._lock:
            return await asyncio.to_thread(self._candles_blocking, symbol, lookback)

    # ------------------------------------------------------------------ quote
    def _quote_blocking(self, symbol: str) -> Quote | None:
        if not self._ensure_connected_blocking():
            return None
        d = self._client.fetch_quote(self._stock(symbol))
        if not d:
            return None
        feed = _FEED_BY_TYPE.get(self._md_market_data_type(), DataFeedStatus.UNAVAILABLE)
        return Quote(
            symbol=symbol,
            ts=datetime.now(timezone.utc),
            bid=d.get("bid"),
            ask=d.get("ask"),
            last=d.get("last") or d.get("close"),
            volume=d.get("volume"),
            feed=feed,
        )

    async def get_quote(self, symbol: str) -> Quote | None:
        async with self._lock:
            return await asyncio.to_thread(self._quote_blocking, symbol)

    # -------------------------------------------------------- reference levels
    def _refs_blocking(self, symbol: str) -> ReferenceLevels:
        cached = self._refs_cache.get(symbol)
        now = time.time()
        if cached and now - cached[1] < _REFS_TTL_SEC:
            return cached[0]
        if not self._ensure_connected_blocking() or not self._hist.allow():
            return cached[0] if cached else ReferenceLevels()
        # Prior session close (RTH daily bars give the official close).
        daily = self._client.fetch_bars(self._stock(symbol), "5 D", "1 day", "TRADES", use_rth=1)
        if not daily:
            return cached[0] if cached else ReferenceLevels()
        prev_close = daily[-2]["close"] if len(daily) >= 2 else daily[-1]["close"]
        # Intraday extended-hours bars give pre-market/overnight + RTH highs/lows.
        intraday = self._client.fetch_bars(self._stock(symbol), "1 D", "1 min", "TRADES", use_rth=0)
        pre_hi = pre_lo = day_hi = day_lo = None
        for b in intraday:
            ts = _parse_bar_ts(b["date"])
            minutes_utc = ts.hour * 60 + ts.minute
            in_rth = 13 * 60 + 30 <= minutes_utc < 20 * 60  # 09:30–16:00 ET (EDT)
            if in_rth:
                day_hi = b["high"] if day_hi is None else max(day_hi, b["high"])
                day_lo = b["low"] if day_lo is None else min(day_lo, b["low"])
            else:
                pre_hi = b["high"] if pre_hi is None else max(pre_hi, b["high"])
                pre_lo = b["low"] if pre_lo is None else min(pre_lo, b["low"])
        if day_hi is None:  # before RTH open: fall back to the daily bar
            day_hi, day_lo = daily[-1]["high"], daily[-1]["low"]
        refs = ReferenceLevels(
            prev_close=prev_close,
            premarket_high=pre_hi, premarket_low=pre_lo,
            day_high=day_hi, day_low=day_lo,
        )
        self._refs_cache[symbol] = (refs, now)
        return refs

    async def get_reference_levels(self, symbol: str) -> ReferenceLevels:
        async with self._lock:
            return await asyncio.to_thread(self._refs_blocking, symbol)

    def _avgvol_blocking(self, symbol: str) -> float | None:
        cached = self._avgvol_cache.get(symbol)
        now = time.time()
        if cached and now - cached[1] < _AVGVOL_TTL_SEC:
            return cached[0]
        if not self._ensure_connected_blocking() or not self._hist.allow():
            return cached[0] if cached else None
        daily = self._client.fetch_bars(self._stock(symbol), "15 D", "1 day", "TRADES")
        if not daily or len(daily) < 2:
            return cached[0] if cached else None
        prior = daily[:-1]
        val = sum(b["volume"] for b in prior) / len(prior)
        self._avgvol_cache[symbol] = (val, now)
        return val

    async def get_historical_avg_volume(self, symbol: str) -> float | None:
        async with self._lock:
            return await asyncio.to_thread(self._avgvol_blocking, symbol)

    # ------------------------------------------------------------ option chain
    def _opt_enum_contract(self, symbol: str, *, strike: float | None = None,
                           expiry_or_month: str | None = None, right: str = "C"):
        """Partial OPT contract used to enumerate the chain via contractDetails.

        ``multiplier='100'`` is required or the gateway returns 'no security
        definition'. A fixed strike+month yields the valid expiries; a fixed
        expiry (no strike) yields the strike grid — both are small/fast queries.
        """
        c = self._Contract()
        c.symbol = symbol.upper()
        c.secType = "OPT"
        c.currency = "USD"
        c.exchange = "SMART"
        c.multiplier = "100"
        c.right = right
        if strike is not None:
            c.strike = float(strike)
        if expiry_or_month is not None:
            c.lastTradeDateOrContractMonth = expiry_or_month
        return c

    @staticmethod
    def _probe_strikes(spot: float) -> list[float]:
        """Candidate ATM strikes across common grids to find a listed strike."""
        out: list[float] = []
        seen: set[float] = set()
        for inc in (5.0, 1.0, 2.5, 10.0, 25.0, 50.0):
            x = round(round(spot / inc) * inc, 2)
            if x > 0 and x not in seen:
                seen.add(x)
                out.append(x)
        return out

    @staticmethod
    def _months(now: datetime) -> list[str]:
        cur = now.strftime("%Y%m")
        nxt = (now.replace(day=28) + timedelta(days=7)).strftime("%Y%m")
        return [cur, nxt] if nxt != cur else [cur]

    def _option_expiries(self, symbol: str, spot: float, now: datetime) -> list[str]:
        cached = self._params_cache.get(symbol)
        ts = time.time()
        if cached and ts - cached[1] < _CONID_TTL_SEC and cached[0]:
            return cached[0]
        expiries: set[str] = set()
        for strike in self._probe_strikes(spot):
            for month in self._months(now):
                rows = self._client.fetch_contract_details(
                    self._opt_enum_contract(symbol, strike=strike, expiry_or_month=month)
                )
                for r in rows:
                    e = r.get("expiry")
                    if e and len(str(e)) == 8:
                        expiries.add(str(e))
            if expiries:
                break
        result = sorted(expiries)
        self._params_cache[symbol] = (result, ts)
        return result

    def _option_strikes(self, symbol: str, expiry: str) -> list[float]:
        key = f"{symbol}:{expiry}"
        cached = self._con_id_cache.get(key)
        ts = time.time()
        if cached and ts - cached[1] < _CONID_TTL_SEC and cached[0]:
            return cached[0]
        rows = self._client.fetch_contract_details(
            self._opt_enum_contract(symbol, expiry_or_month=expiry)
        )
        strikes = sorted({float(r["strike"]) for r in rows if r.get("strike")})
        self._con_id_cache[key] = (strikes, ts)
        return strikes

    def _chain_blocking(self, underlying: str, spot: float) -> OptionChain | None:
        cached = self._chain_cache.get(underlying)
        now_ts = time.time()
        if cached and now_ts - cached[1] < _CHAIN_TTL_SEC:
            return cached[0]
        if not self._ensure_connected_blocking():
            return cached[0] if cached else None
        now = datetime.now(timezone.utc)
        expiries = self._option_expiries(underlying, spot, now)
        if not expiries:
            return OptionChain(underlying=underlying, asof=now, expiries=[], quotes=[])

        today = now.strftime("%Y%m%d")
        target = today if today in expiries else min((e for e in expiries if e >= today), default=expiries[0])

        all_strikes = self._option_strikes(underlying, target)
        if not all_strikes:
            return OptionChain(underlying=underlying, asof=now, expiries=expiries, quotes=[])
        # Pick the strikes nearest spot.
        strikes = sorted(all_strikes, key=lambda k: abs(k - spot))[: _STRIKES_PER_SIDE * 2 + 1]
        feed = _FEED_BY_TYPE.get(self._md_market_data_type(), DataFeedStatus.UNAVAILABLE)
        # Build every call/put contract, then fetch all snapshots in one batch.
        specs: list[tuple[float, OptionRight]] = [
            (k, right) for k in strikes for right in (OptionRight.CALL, OptionRight.PUT)
        ]
        contracts = [self._option(underlying, target, k, right) for k, right in specs]
        results = self._client.fetch_option_quotes(contracts)
        quotes: list[OptionQuote] = []
        for (k, right), d in zip(specs, results):
            if not d:
                continue
            quotes.append(
                OptionQuote(
                    spec=OptionContractSpec(
                        underlying=underlying, expiry=target, strike=k,
                        right=right, multiplier=100.0,
                    ),
                    ts=now,
                    bid=d.get("bid"), ask=d.get("ask"), last=d.get("last") or d.get("close"),
                    volume=d.get("volume"), open_interest=d.get("open_interest"),
                    iv=d.get("iv"), delta=d.get("delta"), gamma=d.get("gamma"),
                    theta=d.get("theta"), vega=d.get("vega"),
                    feed=feed,
                )
            )
        chain = OptionChain(underlying=underlying, asof=now, expiries=expiries, quotes=quotes)
        self._chain_cache[underlying] = (chain, now_ts)
        return chain

    async def get_option_chain(self, underlying: str, spot: float) -> OptionChain | None:
        async with self._lock:
            return await asyncio.to_thread(self._chain_blocking, underlying, spot)

    def _option_quote_blocking(
        self, underlying: str, expiry: str, strike: float, right: OptionRight
    ) -> OptionQuote | None:
        if not self._ensure_connected_blocking():
            return None
        now = datetime.now(timezone.utc)
        d = self._client.fetch_option_quotes(
            [self._option(underlying, expiry, strike, right)], timeout=4.0
        )[0]
        if not d:
            return None
        feed = _FEED_BY_TYPE.get(self._md_market_data_type(), DataFeedStatus.UNAVAILABLE)
        return OptionQuote(
            spec=OptionContractSpec(
                underlying=underlying, expiry=expiry, strike=strike,
                right=right, multiplier=100.0,
            ),
            ts=now,
            bid=d.get("bid"), ask=d.get("ask"), last=d.get("last") or d.get("close"),
            volume=d.get("volume"), open_interest=d.get("open_interest"),
            iv=d.get("iv"), delta=d.get("delta"),
            feed=feed,
        )

    async def get_option_quote(
        self, underlying: str, expiry: str, strike: float, right: OptionRight
    ) -> OptionQuote | None:
        async with self._lock:
            return await asyncio.to_thread(
                self._option_quote_blocking, underlying, expiry, strike, right
            )

    async def close(self) -> None:
        client = self._client
        if client is not None:
            await asyncio.to_thread(client.disconnect_safe)
        self._client = None
