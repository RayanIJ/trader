"""Full-day intraday bar collector.

Retrieves the complete set of *completed* 1-minute candles for the current
trading session from the active :class:`MarketDataSource`. Only bars whose
close time is strictly before ``now`` are included — the partial live candle
is never sent to the LLM.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.logging import get_logger
from app.core.timezone import ET, market_session_bounds, to_et, current_et_date
from app.features import indicators as ind
from app.market_data.models import Candle, Quote, ReferenceLevels
from app.market_data.source import MarketDataSource

logger = get_logger("intraday_bars")

# Maximum bars in a full regular session (9:30–16:00 = 390 minutes).
MAX_SESSION_BARS = 390


async def get_session_bars(
    source: MarketDataSource,
    symbol: str,
    now: datetime | None = None,
) -> list[Candle]:
    """Return completed 1-minute bars for the current session.

    Filters out bars outside today's regular session and bars whose bar-open
    time is >= ``now`` (incomplete candles).
    """
    now = now or datetime.now(timezone.utc)
    today = current_et_date()
    session_open, session_close = market_session_bounds(today)

    # Request enough lookback to cover the full session.
    candles = await source.get_candles_1m(symbol, MAX_SESSION_BARS)
    if not candles:
        return []

    # Filter to today's session and only completed bars.
    # A bar is "completed" if its open time + 1 min <= now.
    from datetime import timedelta

    out: list[Candle] = []
    for c in candles:
        bar_et = to_et(c.ts)
        # Must be within today's session bounds.
        if bar_et < session_open or bar_et >= session_close:
            continue
        # Bar must be completed (open + 1min < now).
        bar_close_time = c.ts + timedelta(minutes=1)
        if bar_close_time > now:
            continue
        out.append(c)

    return out


def enrich_bars(
    candles: list[Candle],
) -> list[dict]:
    """Compute per-bar indicators and return enriched bar dicts.

    Returns a list of dicts matching the spec's 1-minute bar fields.
    """
    if not candles:
        return []

    from app.core.timezone import dual_timestamp

    closes = [c.close for c in candles]
    vwap_series = ind.running_vwap_series(candles)
    ema10_series = ind.running_ema_series(closes, 10)
    ema20_series = ind.running_ema_series(closes, 20)
    rsi_series = ind.running_rsi_series(closes, 14)
    atr_series = ind.running_atr_series(candles, 14)

    enriched: list[dict] = []
    for i, c in enumerate(candles):
        vwap_val = vwap_series[i] if i < len(vwap_series) else None
        above_vwap = (c.close > vwap_val) if vwap_val is not None else None
        dist_points = (c.close - vwap_val) if vwap_val is not None else None
        dist_pct = ((c.close - vwap_val) / vwap_val * 100.0) if (vwap_val and vwap_val != 0) else None

        ts = dual_timestamp(c.ts)
        enriched.append({
            "timestamp_et": ts["timestamp_et"],
            "timestamp_gmt3": ts["timestamp_gmt3"],
            "open": round(c.open, 2),
            "high": round(c.high, 2),
            "low": round(c.low, 2),
            "close": round(c.close, 2),
            "volume": int(c.volume),
            "vwap": round(vwap_val, 4) if vwap_val is not None else None,
            "ema_10": round(ema10_series[i], 4) if (i < len(ema10_series) and ema10_series[i] is not None) else None,
            "ema_20": round(ema20_series[i], 4) if (i < len(ema20_series) and ema20_series[i] is not None) else None,
            "rsi_14": round(rsi_series[i], 2) if (i < len(rsi_series) and rsi_series[i] is not None) else None,
            "atr_14": round(atr_series[i], 4) if (i < len(atr_series) and atr_series[i] is not None) else None,
            "above_vwap": above_vwap,
            "distance_from_vwap_points": round(dist_points, 4) if dist_points is not None else None,
            "distance_from_vwap_percent": round(dist_pct, 4) if dist_pct is not None else None,
        })
    return enriched
