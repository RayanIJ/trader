"""Scanner engine.

For each scan tick it:
  1. pulls candles/quote/refs for every scanned symbol from the active
     :class:`MarketDataSource`,
  2. builds a :class:`FeatureSet` per symbol via the feature engine,
  3. derives the cross-asset :class:`MarketRegime`,
  4. for each *tradable* symbol picks a direction from the bias, scores it,
     selects the best long contract (premium/spread/liquidity filtered), and
     attaches reason codes for anything that blocks it,
  5. ranks candidates and splits them into top calls / top puts.

The scanner makes NO trade. It produces ranked candidates + reasons; the Phase-3
signal engine and Phase-4 risk engine decide what (if anything) to act on.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from app.config.schema import AppConfig
from app.core.enums import Direction, RejectCode, ScoreBand, SignalType
from app.core.logging import get_logger
from app.features.engine import FeatureEngine, FeatureSet
from app.macro.calendar import MacroGuard
from app.market_data.source import MarketDataSource
from app.options.chain_builder import ChainSelection, select_contract
from app.risk.behavior import BehaviorStatus
from app.risk.day_state import TradingDayState
from app.risk.engine import RiskDecision, RiskEngine
from app.scanner.regime import MarketRegime, build_regime
from app.scanner.scoring import ScoreBreakdown, infer_signal_type, score_candidate
from app.signals.engine import SignalDecision, SignalEngine

logger = get_logger("scanner")


@dataclass
class ContractView:
    expiry: str
    strike: float
    right: str
    premium: float | None
    ask: float | None
    bid: float | None
    spread_pct: float | None
    volume: float | None
    open_interest: float | None
    delta: float | None
    has_zero_dte: bool


@dataclass
class ScanCandidate:
    symbol: str
    direction: str                       # CALL / PUT
    signal_type: str
    score: float
    band: str                            # NO_TRADE / WATCH / REDUCED_RISK / NORMAL
    tradable: bool                       # passed all scanner-level gates
    reject_codes: list[str] = field(default_factory=list)
    score_breakdown: dict = field(default_factory=dict)
    contract: ContractView | None = None
    price: float | None = None
    vwap: float | None = None
    relative_volume: float | None = None
    chop_band: str = "LOW"
    chop_score: float = 0.0
    signal_ok: bool = False
    risk_ok: bool = False
    approved: bool = False
    signal_decision: dict = field(default_factory=dict)
    risk_decision: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class ScanResult:
    asof: datetime
    source: str
    regime: MarketRegime
    candidates: list[ScanCandidate]

    @property
    def top_calls(self) -> list[ScanCandidate]:
        calls = [c for c in self.candidates if c.direction == Direction.CALL.value]
        return sorted(calls, key=lambda c: c.score, reverse=True)

    @property
    def top_puts(self) -> list[ScanCandidate]:
        puts = [c for c in self.candidates if c.direction == Direction.PUT.value]
        return sorted(puts, key=lambda c: c.score, reverse=True)

    def to_dict(self) -> dict:
        return {
            "asof": self.asof.isoformat(),
            "source": self.source,
            "regime": self.regime.to_dict(),
            "candidates": [c.to_dict() for c in sorted(self.candidates, key=lambda c: c.score, reverse=True)],
            "top_calls": [c.to_dict() for c in self.top_calls[:10]],
            "top_puts": [c.to_dict() for c in self.top_puts[:10]],
        }


class ScannerEngine:
    def __init__(
        self,
        cfg: AppConfig,
        source: MarketDataSource,
        *,
        signal_engine: SignalEngine | None = None,
        risk_engine: RiskEngine | None = None,
        macro_guard: MacroGuard | None = None,
        day_state: TradingDayState | None = None,
    ) -> None:
        self._cfg = cfg
        self._source = source
        self._features = FeatureEngine(cfg.market_data, cfg.signal)
        self._signal = signal_engine or SignalEngine(cfg)
        self._risk = risk_engine or RiskEngine(cfg)
        self._macro = macro_guard or MacroGuard(cfg.macro)
        self._day = day_state or TradingDayState.for_today()

    @property
    def source(self) -> MarketDataSource:
        return self._source

    async def _build_features(self, symbol: str, now: datetime):
        """Return (FeatureSet | None, candles, quote)."""
        try:
            candles = await self._source.get_candles_1m(symbol, self._cfg.market_data.candle_lookback_1m)
            if not candles:
                return None, [], None
            quote = await self._source.get_quote(symbol)
            refs = await self._source.get_reference_levels(symbol)
            avg_vol = await self._source.get_historical_avg_volume(symbol)
            fs = self._features.build(
                symbol, candles, quote, refs, historical_avg_volume=avg_vol, now=now
            )
            return fs, candles, quote
        except Exception:
            logger.exception("feature build failed for %s", symbol)
            return None, [], None

    async def scan(
        self,
        now: datetime | None = None,
        *,
        health_ok: bool = True,
        broker_tradable: bool = True,
        data_feed_live: bool = True,
    ) -> ScanResult:
        now = now or datetime.now(timezone.utc)
        today = now.strftime("%Y%m%d")
        uni = self._cfg.universe

        behavior = self._risk.behavior_governor.evaluate(
            self._day,
            health_degraded=not health_ok,
        )

        scanned = uni.all_scanned
        built = await asyncio.gather(*(self._build_features(s, now) for s in scanned))
        features: dict[str, FeatureSet] = {}
        candle_map: dict[str, list] = {}
        quote_map: dict[str, object] = {}
        for sym, (fs, candles, quote) in zip(scanned, built):
            if fs is not None:
                features[sym] = fs
                candle_map[sym] = candles
                quote_map[sym] = quote

        regime = build_regime(features, uni)

        index_set = set(uni.index_symbols)
        tradable_syms = uni.all_tradable
        cands = await asyncio.gather(
            *(
                self._candidate(
                    features[s],
                    regime,
                    s in index_set,
                    today,
                    now,
                    candles=candle_map.get(s, []),
                    quote=quote_map.get(s),
                    behavior=behavior,
                    health_ok=health_ok,
                    broker_tradable=broker_tradable,
                    data_feed_live=data_feed_live,
                )
                for s in tradable_syms
                if s in features
            )
        )
        candidates = [c for c in cands if c is not None]
        return ScanResult(asof=now, source=self._source.name, regime=regime, candidates=candidates)

    def _contract_view(self, sel: ChainSelection) -> ContractView | None:
        if sel.chosen is None:
            return None
        e = sel.chosen
        q = e.quote
        return ContractView(
            expiry=q.spec.expiry,
            strike=q.spec.strike,
            right=q.spec.right.value,
            premium=e.premium,
            ask=q.ask,
            bid=q.bid,
            spread_pct=e.spread_pct,
            volume=q.volume,
            open_interest=q.open_interest,
            delta=q.delta,
            has_zero_dte=sel.has_zero_dte,
        )

    async def _candidate(
        self,
        fs: FeatureSet,
        regime: MarketRegime,
        is_index: bool,
        today: str,
        now: datetime,
        *,
        candles: list,
        quote,
        behavior: BehaviorStatus,
        health_ok: bool = True,
        broker_tradable: bool = True,
        data_feed_live: bool = True,
    ) -> ScanCandidate | None:
        if fs.price is None or fs.bias == "FLAT":
            return ScanCandidate(
                symbol=fs.symbol,
                direction=Direction.CALL.value if (fs.above_vwap) else Direction.PUT.value,
                signal_type=SignalType.NO_SETUP.value,
                score=0.0,
                band=ScoreBand.NO_TRADE.value,
                tradable=False,
                reject_codes=[RejectCode.BLOCKED_LOW_SCORE.value],
                price=fs.price,
                vwap=fs.vwap,
                relative_volume=fs.relative_volume,
                chop_band=fs.chop.band,
                chop_score=fs.chop.score,
            )

        direction = Direction.CALL if fs.bias == "UP" else Direction.PUT
        reject_codes: list[RejectCode] = []

        # Hard chop gate.
        if fs.chop.blocks_trade:
            reject_codes.append(RejectCode.BLOCKED_VWAP_CHOP)

        # Preliminary score WITHOUT option liquidity. Only worthwhile candidates
        # warrant fetching an option chain (expensive over a live feed). Option
        # liquidity contributes up to 10 pts, so anything within 10 of the watch
        # floor is still in contention.
        prelim = score_candidate(
            fs, direction, regime=regime, is_index=is_index,
            min_relative_volume=self._cfg.signal.min_relative_volume,
            option_liquidity_ok=False, option_spread_pct=None,
            preferred_spread_pct=self._cfg.options.preferred_spread_pct, now_utc=now,
        )
        promising = (
            not fs.chop.blocks_trade
            and prelim.total >= (self._cfg.signal.watch_band_floor - 10.0)
        )

        sel: ChainSelection | None = None
        contract_view: ContractView | None = None
        option_liquidity_ok = False
        option_spread_pct: float | None = None
        if promising:
            chain = await self._source.get_option_chain(fs.symbol, fs.price)
            if chain is None or not chain.quotes:
                reject_codes.append(RejectCode.BLOCKED_NO_0DTE_EXPIRY)
            else:
                sel = select_contract(
                    chain, direction, fs.price, self._cfg.options, self._cfg.risk, today,
                    prefer_zero_dte=True,
                )
                for rc in sel.reject_codes:
                    if rc not in reject_codes:
                        reject_codes.append(rc)
                contract_view = self._contract_view(sel)
                if sel.chosen is not None:
                    option_liquidity_ok = True
                    option_spread_pct = sel.chosen.spread_pct

        breakdown: ScoreBreakdown = score_candidate(
            fs,
            direction,
            regime=regime,
            is_index=is_index,
            min_relative_volume=self._cfg.signal.min_relative_volume,
            option_liquidity_ok=option_liquidity_ok,
            option_spread_pct=option_spread_pct,
            preferred_spread_pct=self._cfg.options.preferred_spread_pct,
            now_utc=now,
        )
        score = breakdown.total
        band = ScoreBand.from_score(score)

        if score < self._cfg.signal.min_score_to_trade and RejectCode.BLOCKED_LOW_SCORE not in reject_codes:
            reject_codes.append(RejectCode.BLOCKED_LOW_SCORE)

        tradable = len(reject_codes) == 0 and contract_view is not None
        signal_type = infer_signal_type(fs, direction)

        option_ask = contract_view.ask if contract_view else None
        option_bid = contract_view.bid if contract_view else None
        sig_dec = self._signal.evaluate(
            fs,
            direction,
            regime,
            score=score,
            is_index=is_index,
            quote=quote,
            candles=candles,
            macro_blocked=self._macro.is_blocked(now),
            data_feed_live=data_feed_live,
            option_ask=option_ask,
            option_bid=option_bid,
            now=now,
        )
        risk_dec = self._risk.evaluate(
            symbol=fs.symbol,
            direction=direction,
            signal_type=signal_type.value,
            signal=sig_dec,
            day=self._day,
            macro=self._macro,
            behavior=behavior,
            option_ask=option_ask,
            multiplier=100.0 if contract_view else None,
            health_ok=health_ok,
            broker_tradable=broker_tradable,
            now=now,
        )

        all_rejects = list(reject_codes)
        for rc in sig_dec.reject_codes + risk_dec.reject_codes:
            if rc not in all_rejects:
                all_rejects.append(rc)

        return ScanCandidate(
            symbol=fs.symbol,
            direction=direction.value,
            signal_type=signal_type.value,
            score=score,
            band=band.value,
            tradable=tradable,
            reject_codes=[rc.value for rc in all_rejects],
            score_breakdown=breakdown.to_dict(),
            contract=contract_view,
            price=fs.price,
            vwap=fs.vwap,
            relative_volume=fs.relative_volume,
            chop_band=fs.chop.band,
            chop_score=fs.chop.score,
            signal_ok=sig_dec.approved,
            risk_ok=risk_dec.approved,
            approved=tradable and sig_dec.approved and risk_dec.approved,
            signal_decision=sig_dec.to_dict(),
            risk_decision=risk_dec.to_dict(),
        )
