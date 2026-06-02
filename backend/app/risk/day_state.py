"""In-memory trading-day state.

Tracks daily P/L, open exposure, recent signals/trades, and cooldown timers.
v1 keeps this in memory (reset on restart); the schema supports persisting to
the journal tables in Phase 5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.config.schema import RiskConfig
from app.core.enums import Direction, RejectCode


@dataclass
class RecentSignal:
    symbol: str
    direction: Direction
    signal_type: str
    ts: datetime
    was_loss: bool = False


@dataclass
class OpenPositionStub:
    symbol: str
    direction: Direction
    premium_exposure: float
    entry_ts: datetime


@dataclass
class TradingDayState:
    """Mutable session state for one trading day."""

    session_date: str
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    trades_today: int = 0
    lockout: bool = False
    lockout_reason: str | None = None
    open_positions: list[OpenPositionStub] = field(default_factory=list)
    recent_signals: list[RecentSignal] = field(default_factory=list)
    recent_losses: list[RecentSignal] = field(default_factory=list)

    @property
    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl

    def remaining_loss_allowance(self, max_daily_loss: float) -> float:
        """Dollar room left before the hard daily-loss cap."""
        return max(max_daily_loss + self.total_pnl, 0.0)

    def open_premium_exposure(self) -> float:
        return sum(p.premium_exposure for p in self.open_positions)

    def has_position(self, symbol: str) -> bool:
        return any(p.symbol == symbol for p in self.open_positions)

    def record_trade_exit(
        self, symbol: str, direction: Direction, pnl: float, signal_type: str, ts: datetime
    ) -> None:
        self.trades_today += 1
        self.realized_pnl += pnl
        self.open_positions = [p for p in self.open_positions if p.symbol != symbol]
        sig = RecentSignal(symbol, direction, signal_type, ts, was_loss=pnl < 0)
        self.recent_signals.append(sig)
        if pnl < 0:
            self.recent_losses.append(sig)

    def record_signal(self, symbol: str, direction: Direction, signal_type: str, ts: datetime) -> None:
        self.recent_signals.append(RecentSignal(symbol, direction, signal_type, ts))

    def apply_lockout(self, reason: str) -> None:
        self.lockout = True
        self.lockout_reason = reason

    def clear_lockout(self) -> None:
        self.lockout = False
        self.lockout_reason = None

    def check_daily_loss(self, max_daily_loss: float) -> RejectCode | None:
        if self.total_pnl <= -max_daily_loss:
            self.apply_lockout(f"daily loss limit reached (${self.total_pnl:.2f})")
            return RejectCode.BLOCKED_DAILY_LOSS
        if self.lockout:
            return RejectCode.BLOCKED_DAILY_LOSS
        return None

    def cooldown_reject(
        self, symbol: str, direction: Direction, cfg: RiskConfig, now: datetime
    ) -> RejectCode | None:
        if not self.recent_signals:
            return None
        last_any = self.recent_signals[-1]
        since_any = (now - last_any.ts).total_seconds()
        if since_any < cfg.cooldown_after_trade_sec:
            return RejectCode.BLOCKED_COOLDOWN

        for sig in reversed(self.recent_losses):
            if (now - sig.ts).total_seconds() < cfg.cooldown_after_loss_sec:
                return RejectCode.BLOCKED_COOLDOWN
            break

        for sig in reversed(self.recent_signals):
            if sig.symbol == symbol and (now - sig.ts).total_seconds() < cfg.cooldown_same_underlying_sec:
                return RejectCode.BLOCKED_COOLDOWN

        # Block repeated same-direction failures on a symbol.
        same_dir_losses = [
            s for s in self.recent_losses
            if s.symbol == symbol and s.direction == direction
        ][-cfg.block_symbol_after_same_dir_losses:]
        if len(same_dir_losses) >= cfg.block_symbol_after_same_dir_losses:
            return RejectCode.BLOCKED_COOLDOWN

        return None

    def duplicate_signal_reject(
        self, symbol: str, direction: Direction, signal_type: str, now: datetime, window_sec: int = 300
    ) -> RejectCode | None:
        cutoff = now - timedelta(seconds=window_sec)
        for sig in reversed(self.recent_signals):
            if sig.ts < cutoff:
                break
            if sig.symbol == symbol and sig.direction == direction and sig.signal_type == signal_type:
                return RejectCode.BLOCKED_DUPLICATE_SIGNAL
        return None

    def direction_flip_reject(
        self, symbol: str, direction: Direction, now: datetime, window_sec: int = 600
    ) -> RejectCode | None:
        cutoff = now - timedelta(seconds=window_sec)
        for sig in reversed(self.recent_signals):
            if sig.ts < cutoff:
                break
            if sig.symbol == symbol and sig.direction != direction:
                return RejectCode.BLOCKED_DIRECTION_FLIP
        return None

    def to_dict(self, max_daily_loss: float) -> dict:
        return {
            "session_date": self.session_date,
            "realized_pnl": round(self.realized_pnl, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "remaining_loss_allowance": round(self.remaining_loss_allowance(max_daily_loss), 2),
            "open_premium_exposure": round(self.open_premium_exposure(), 2),
            "trades_today": self.trades_today,
            "lockout": self.lockout,
            "lockout_reason": self.lockout_reason,
            "open_positions": len(self.open_positions),
        }

    @classmethod
    def for_today(cls, now: datetime | None = None) -> "TradingDayState":
        now = now or datetime.now(timezone.utc)
        return cls(session_date=now.strftime("%Y-%m-%d"))
