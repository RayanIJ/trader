"""Backtest / replay engine — deterministic scanner replay over simulated data."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.config.schema import AppConfig
from app.macro.calendar import MacroGuard
from app.market_data.simulated import SimulatedMarketDataSource
from app.risk.day_state import TradingDayState
from app.risk.engine import RiskEngine
from app.scanner.engine import ScannerEngine
from app.signals.engine import SignalEngine


@dataclass
class BacktestResult:
    seed: int
    steps: int
    total_candidates: int
    approved_count: int
    rejected_count: int
    top_symbols: list[tuple[str, float]] = field(default_factory=list)
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "seed": self.seed,
            "steps": self.steps,
            "total_candidates": self.total_candidates,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "approval_rate": round(self.approved_count / max(self.total_candidates, 1) * 100, 1),
            "top_symbols": [{"symbol": s, "max_score": sc} for s, sc in self.top_symbols[:10]],
            "rejection_reasons": self.rejection_reasons,
        }


class BacktestEngine:
    """Replay the scanner over a simulated session at fixed intervals."""

    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    async def run(
        self,
        *,
        seed: int = 1337,
        steps: int = 12,
        interval_minutes: int = 5,
        session_start: datetime | None = None,
    ) -> BacktestResult:
        session_start = session_start or datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc)
        source = SimulatedMarketDataSource(seed=seed)
        day = TradingDayState.for_today(session_start)
        scanner = ScannerEngine(
            self._cfg,
            source,
            signal_engine=SignalEngine(self._cfg),
            risk_engine=RiskEngine(self._cfg),
            macro_guard=MacroGuard(self._cfg.macro),
            day_state=day,
        )

        total = approved = rejected = 0
        symbol_best: dict[str, float] = {}
        rejections: dict[str, int] = {}

        for i in range(steps):
            now = session_start + timedelta(minutes=i * interval_minutes)
            result = await scanner.scan(now=now, health_ok=True, broker_tradable=True)
            for c in result.candidates:
                total += 1
                if c.approved:
                    approved += 1
                else:
                    rejected += 1
                    for code in c.reject_codes:
                        rejections[code] = rejections.get(code, 0) + 1
                prev = symbol_best.get(c.symbol, 0.0)
                symbol_best[c.symbol] = max(prev, c.score)

        top = sorted(symbol_best.items(), key=lambda x: x[1], reverse=True)
        await source.close()
        return BacktestResult(
            seed=seed,
            steps=steps,
            total_candidates=total,
            approved_count=approved,
            rejected_count=rejected,
            top_symbols=top,
            rejection_reasons=rejections,
        )
