"""Signal engine — deterministic setup approval on top of scanner candidates.

Combines no-trade filters, entry-timing gates, macro blocking, and score-band
rules. A good scanner score alone is not enough; every gate must pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.config.schema import AppConfig
from app.core.enums import Direction, RejectCode, ScoreBand
from app.features.engine import FeatureSet
from app.market_data.models import Candle, Quote
from app.scanner.regime import MarketRegime
from app.signals.entry_timing import collect_entry_timing_filters
from app.signals.filters import collect_no_trade_filters


@dataclass
class SignalDecision:
    approved: bool
    reject_codes: list[RejectCode] = field(default_factory=list)
    band: ScoreBand = ScoreBand.NO_TRADE
    score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "approved": self.approved,
            "reject_codes": [rc.value for rc in self.reject_codes],
            "band": self.band.value,
            "score": self.score,
        }


class SignalEngine:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def evaluate(
        self,
        fs: FeatureSet,
        direction: Direction,
        regime: MarketRegime,
        *,
        score: float,
        is_index: bool,
        quote: Quote | None,
        candles: list[Candle],
        macro_blocked: bool,
        data_feed_live: bool = True,
        option_ask: float | None = None,
        option_bid: float | None = None,
        prior_option_mid: float | None = None,
        now: datetime | None = None,
    ) -> SignalDecision:
        now = now or fs.ts
        band = ScoreBand.from_score(score)
        codes: list[RejectCode] = []

        if macro_blocked:
            codes.append(RejectCode.BLOCKED_MACRO_EVENT)

        quote_stale = False
        if quote is not None:
            quote_stale = quote.is_stale(now, self._cfg.data_quality.underlying_stale_sec)

        codes.extend(
            collect_no_trade_filters(
                fs,
                direction,
                regime,
                self._cfg.signal,
                is_index=is_index,
                quote_stale=quote_stale,
                data_feed_live=data_feed_live,
                require_live=self._cfg.data_quality.require_live_data,
            )
        )
        codes.extend(
            collect_entry_timing_filters(
                fs,
                direction,
                candles,
                self._cfg.entry,
                option_ask=option_ask,
                option_bid=option_bid,
                prior_option_mid=prior_option_mid,
            )
        )

        if score < self._cfg.signal.min_score_to_trade:
            if RejectCode.BLOCKED_LOW_SCORE not in codes:
                codes.append(RejectCode.BLOCKED_LOW_SCORE)

        # De-dupe while preserving order.
        seen: set[RejectCode] = set()
        unique: list[RejectCode] = []
        for rc in codes:
            if rc not in seen:
                seen.add(rc)
                unique.append(rc)

        approved = len(unique) == 0 and band != ScoreBand.NO_TRADE
        return SignalDecision(approved=approved, reject_codes=unique, band=band, score=score)
