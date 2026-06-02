"""Market-regime view.

Summarizes the confirmation tickers (SPX/SPY/QQQ/SMH/SOXX + VIX) into a single
directional picture the scanner uses for sector/market confirmation scoring and
the dashboard renders in its "Market regime" panel.

The regime is purely descriptive — it never decides a trade by itself. It feeds
the confirmation component of the per-candidate score.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from app.config.schema import UniverseConfig
from app.features.engine import FeatureSet


@dataclass
class SymbolView:
    symbol: str
    bias: str                       # UP / DOWN / FLAT
    momentum_score: float           # 0..100 magnitude
    price: float | None
    vwap: float | None
    dist_from_vwap_pct: float | None
    above_vwap: bool | None


def _view(fs: FeatureSet) -> SymbolView:
    return SymbolView(
        symbol=fs.symbol,
        bias=fs.bias,
        momentum_score=fs.momentum_score,
        price=fs.price,
        vwap=fs.vwap,
        dist_from_vwap_pct=fs.dist_from_vwap_pct,
        above_vwap=fs.above_vwap,
    )


@dataclass
class MarketRegime:
    """Cross-asset confirmation snapshot."""

    market: dict[str, SymbolView] = field(default_factory=dict)   # SPX/SPY
    tech: dict[str, SymbolView] = field(default_factory=dict)     # QQQ
    sector: dict[str, SymbolView] = field(default_factory=dict)   # SMH/SOXX
    volatility: SymbolView | None = None                          # VIX
    overall: str = "MIXED"                                         # RISK_ON/RISK_OFF/MIXED
    vix_elevated: bool = False

    def _bias_sum(self, views: dict[str, SymbolView]) -> int:
        s = 0
        for v in views.values():
            if v.bias == "UP":
                s += 1
            elif v.bias == "DOWN":
                s -= 1
        return s

    def alignment(self, group: str, direction_up: bool) -> float:
        """Signed alignment in [-1, 1] of a group with a CALL (up) / PUT (down) bias.

        +1 = every ticker in the group agrees with the direction, -1 = all oppose.
        """
        views = getattr(self, group, {}) or {}
        if not isinstance(views, dict) or not views:
            return 0.0
        agree = 0
        oppose = 0
        for v in views.values():
            if v.bias == "FLAT":
                continue
            up = v.bias == "UP"
            if up == direction_up:
                agree += 1
            else:
                oppose += 1
        total = agree + oppose
        if total == 0:
            return 0.0
        return (agree - oppose) / total

    def to_dict(self) -> dict:
        def _grp(g: dict[str, SymbolView]) -> dict:
            return {k: asdict(v) for k, v in g.items()}

        return {
            "market": _grp(self.market),
            "tech": _grp(self.tech),
            "sector": _grp(self.sector),
            "volatility": asdict(self.volatility) if self.volatility else None,
            "overall": self.overall,
            "vix_elevated": self.vix_elevated,
        }


def build_regime(features: dict[str, FeatureSet], universe: UniverseConfig) -> MarketRegime:
    regime = MarketRegime()
    for sym in universe.index_symbols + universe.market_confirmation:
        fs = features.get(sym)
        if fs:
            regime.market[sym] = _view(fs)
    for sym in universe.tech_confirmation:
        fs = features.get(sym)
        if fs:
            regime.tech[sym] = _view(fs)
    for sym in universe.sector_etfs:
        fs = features.get(sym)
        if fs:
            regime.sector[sym] = _view(fs)

    vix = features.get(universe.volatility_proxy)
    if vix:
        regime.volatility = _view(vix)
        # VIX rising (UP bias) with momentum is a risk-off tell.
        regime.vix_elevated = vix.bias == "UP" and vix.momentum_score >= 60.0

    market_bias = regime._bias_sum(regime.market) + regime._bias_sum(regime.tech)
    if market_bias > 0 and not regime.vix_elevated:
        regime.overall = "RISK_ON"
    elif market_bias < 0 or regime.vix_elevated:
        regime.overall = "RISK_OFF"
    else:
        regime.overall = "MIXED"
    return regime
