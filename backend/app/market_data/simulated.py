"""Deterministic simulated market data source.

Generates plausible intraday 1-minute candles, quotes, reference levels, and a
0DTE option chain for any symbol — fully offline and reproducible from a seed.
This lets the entire Phase-2 pipeline (features, chain, scanner) run and be
tested without a broker connection, and it doubles as the seed for the Phase-6
replay/backtest engine.

It is NOT a market simulator for P&L; it only needs to exercise the data shapes
and produce a spread of regimes (trending up, trending down, choppy) across the
universe so the scanner surfaces varied candidates.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from app.core.enums import DataFeedStatus, OptionRight
from app.market_data.models import (
    Candle,
    OptionChain,
    OptionContractSpec,
    OptionQuote,
    Quote,
    ReferenceLevels,
)
from app.market_data.source import MarketDataSource

# Rough anchor prices so strikes/chains look realistic per symbol.
_ANCHOR_PRICE = {
    "SPX": 5400.0, "SPY": 540.0, "QQQ": 470.0, "SMH": 240.0, "SOXX": 230.0,
    "NVDA": 120.0, "AVGO": 1600.0, "AMD": 160.0, "TSM": 175.0, "ASML": 1000.0,
    "INTC": 35.0, "MU": 130.0, "ARM": 150.0, "MRVL": 75.0, "QCOM": 200.0,
    "TXN": 200.0, "AMAT": 220.0, "LRCX": 950.0, "KLAC": 800.0, "MCHP": 90.0,
    "ON": 75.0, "NXPI": 250.0, "ADI": 230.0, "VIX": 14.0,
}


def _symbol_seed(base_seed: int, symbol: str) -> int:
    return base_seed ^ (sum(ord(ch) for ch in symbol) * 2654435761 & 0xFFFFFFFF)


class SimulatedMarketDataSource(MarketDataSource):
    name = "simulated"

    def __init__(self, seed: int = 1337) -> None:
        self._seed = seed

    def _anchor(self, symbol: str) -> float:
        return _ANCHOR_PRICE.get(symbol.upper(), 100.0)

    def _series(self, symbol: str, bars: int) -> list[Candle]:
        rng = random.Random(_symbol_seed(self._seed, symbol))
        anchor = self._anchor(symbol)
        # Pick a regime deterministically per symbol.
        drift = rng.choice([+1.0, -1.0, 0.0, +1.0, -1.0]) * (anchor * 0.00015)
        vol = anchor * 0.0009
        price = anchor * (1.0 + rng.uniform(-0.004, 0.004))
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(minutes=bars)
        candles: list[Candle] = []
        for i in range(bars):
            o = price
            # Drift + mean-reverting noise; choppy regime when drift==0.
            step = drift + rng.gauss(0, vol)
            if drift == 0.0:
                step += -0.5 * (price - anchor) / anchor * anchor * 0.001
            c = max(o + step, 0.01)
            hi = max(o, c) + abs(rng.gauss(0, vol * 0.6))
            lo = min(o, c) - abs(rng.gauss(0, vol * 0.6))
            base_vol = 1000 + (anchor * 2)
            v = max(base_vol * rng.uniform(0.5, 2.2), 1.0)
            candles.append(Candle(ts=start + timedelta(minutes=i), open=o, high=hi, low=lo, close=c, volume=v))
            price = c
        return candles

    async def get_candles_1m(self, symbol: str, lookback: int) -> list[Candle]:
        return self._series(symbol, max(lookback, 30))

    async def get_quote(self, symbol: str) -> Quote | None:
        candles = self._series(symbol, 30)
        last = candles[-1].close
        rng = random.Random(_symbol_seed(self._seed, symbol) ^ 0xABCD)
        half = last * rng.uniform(0.0002, 0.0010)
        return Quote(
            symbol=symbol,
            ts=datetime.now(timezone.utc),
            bid=round(last - half, 2),
            ask=round(last + half, 2),
            last=round(last, 2),
            volume=sum(c.volume for c in candles),
            feed=DataFeedStatus.LIVE,
        )

    async def get_reference_levels(self, symbol: str) -> ReferenceLevels:
        candles = self._series(symbol, 60)
        anchor = self._anchor(symbol)
        return ReferenceLevels(
            prev_close=round(anchor, 2),
            premarket_high=round(max(c.high for c in candles[:15]), 2),
            premarket_low=round(min(c.low for c in candles[:15]), 2),
            day_high=round(max(c.high for c in candles), 2),
            day_low=round(min(c.low for c in candles), 2),
        )

    async def get_historical_avg_volume(self, symbol: str) -> float | None:
        # Average cumulative session volume; today's rel-vol varies around 1.0.
        candles = self._series(symbol, 60)
        return sum(c.volume for c in candles) * 0.85

    async def get_option_chain(self, underlying: str, spot: float) -> OptionChain | None:
        rng = random.Random(_symbol_seed(self._seed, underlying) ^ 0x0D7E)
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        # Strikes around spot. Cheap names get $1 spacing; expensive get wider.
        step = max(round(spot * 0.005, 0), 1.0)
        strikes = [round(spot + step * k, 0) for k in range(-6, 7)]
        quotes: list[OptionQuote] = []
        now = datetime.now(timezone.utc)
        for k in strikes:
            for right in (OptionRight.CALL, OptionRight.PUT):
                # Crude intrinsic + time value so some contracts fit under $200.
                if right == OptionRight.CALL:
                    intrinsic = max(spot - k, 0.0)
                    moneyness = (spot - k) / spot
                else:
                    intrinsic = max(k - spot, 0.0)
                    moneyness = (k - spot) / spot
                time_value = max(spot * 0.0015 * math.exp(-abs(moneyness) * 40), 0.01)
                mid = round((intrinsic + time_value), 2)
                # Keep ATM-ish premiums small enough to be tradable under the cap.
                mid = max(min(mid, spot * 0.02), 0.05)
                spread = max(round(mid * rng.uniform(0.02, 0.10), 2), 0.01)
                bid = round(max(mid - spread / 2, 0.01), 2)
                ask = round(bid + spread, 2)
                delta_mag = max(0.05, min(0.95, 0.5 + moneyness * 8))
                quotes.append(
                    OptionQuote(
                        spec=OptionContractSpec(
                            underlying=underlying, expiry=today, strike=k,
                            right=right, multiplier=100.0, con_id=None,
                        ),
                        ts=now,
                        bid=bid, ask=ask, last=mid,
                        volume=float(rng.randint(50, 4000)),
                        open_interest=float(rng.randint(100, 20000)),
                        iv=round(rng.uniform(0.2, 0.8), 3),
                        delta=round(delta_mag if right == OptionRight.CALL else -delta_mag, 3),
                        gamma=round(rng.uniform(0.001, 0.05), 4),
                        theta=round(-rng.uniform(0.01, 0.4), 3),
                        vega=round(rng.uniform(0.01, 0.2), 3),
                        feed=DataFeedStatus.LIVE,
                    )
                )
        return OptionChain(underlying=underlying, asof=now, expiries=[today], quotes=quotes)

    async def get_option_quote(
        self, underlying: str, expiry: str, strike: float, right: OptionRight
    ) -> OptionQuote | None:
        chain = await self.get_option_chain(underlying, strike)
        if not chain:
            return None
        for q in chain.quotes:
            if (
                q.spec.expiry == expiry
                and abs(q.spec.strike - strike) < 0.01
                and q.spec.right == right
            ):
                return q
        return None
