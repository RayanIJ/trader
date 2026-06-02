"""No-trade filters.

Each filter inspects the feature set / market state and, if a blocking condition
holds, contributes a :class:`RejectCode`. The signal engine runs them all and a
candidate is approvable only when none fire (and the score clears the threshold).

These encode the spec's "no-trade conditions": VWAP chop, low relative volume,
stale/delayed data, opposing cross-asset confirmation, and (via entry-timing)
over-extension. "No trade" is a normal, expected outcome.
"""
from __future__ import annotations

from app.config.schema import SignalConfig
from app.core.enums import Direction, RejectCode
from app.features.engine import FeatureSet
from app.scanner.regime import MarketRegime


def chop_filter(fs: FeatureSet) -> RejectCode | None:
    return RejectCode.BLOCKED_VWAP_CHOP if fs.chop.blocks_trade else None


def relative_volume_filter(fs: FeatureSet, cfg: SignalConfig) -> RejectCode | None:
    if fs.relative_volume is not None and fs.relative_volume < cfg.min_relative_volume:
        return RejectCode.BLOCKED_LOW_VOLUME
    return None


def stale_quote_filter(quote_stale: bool) -> RejectCode | None:
    return RejectCode.BLOCKED_STALE_QUOTE if quote_stale else None


def delayed_data_filter(data_feed_live: bool, require_live: bool) -> RejectCode | None:
    if require_live and not data_feed_live:
        return RejectCode.BLOCKED_DELAYED_DATA
    return None


def vwap_alignment_filter(fs: FeatureSet, direction: Direction) -> RejectCode | None:
    """Direction must agree with VWAP side (call above / put below)."""
    if fs.above_vwap is None:
        return None
    wants_up = direction == Direction.CALL
    if fs.above_vwap != wants_up:
        return RejectCode.BLOCKED_VWAP_CHOP
    return None


def opposing_confirmation_filter(
    regime: MarketRegime, direction: Direction, is_index: bool
) -> RejectCode | None:
    """Block when the market (and sector, for single names) strongly opposes.

    Strong opposition = combined market/tech alignment <= -0.5 (most confirmation
    tickers pointing the other way).
    """
    direction_up = direction == Direction.CALL
    market = regime.alignment("market", direction_up)
    tech = regime.alignment("tech", direction_up)
    combined = (market + tech) / 2.0
    if not is_index:
        sector = regime.alignment("sector", direction_up)
        combined = (combined + sector) / 2.0
    if combined <= -0.5:
        return RejectCode.BLOCKED_LOW_SCORE
    return None


def collect_no_trade_filters(
    fs: FeatureSet,
    direction: Direction,
    regime: MarketRegime,
    cfg: SignalConfig,
    *,
    is_index: bool,
    quote_stale: bool,
    data_feed_live: bool,
    require_live: bool,
) -> list[RejectCode]:
    codes: list[RejectCode] = []
    for rc in (
        chop_filter(fs),
        relative_volume_filter(fs, cfg),
        stale_quote_filter(quote_stale),
        delayed_data_filter(data_feed_live, require_live),
        vwap_alignment_filter(fs, direction),
        opposing_confirmation_filter(regime, direction, is_index),
    ):
        if rc is not None and rc not in codes:
            codes.append(rc)
    return codes
