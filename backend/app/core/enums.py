"""Shared enumerations.

Centralizing these prevents stringly-typed drift between the signal, risk,
execution, and journaling layers. Reject codes mirror the scanner reason codes
required by the spec so the UI can render them verbatim.
"""
from __future__ import annotations

from enum import Enum


class TradingMode(str, Enum):
    """Operating mode. Default is SHADOW (no orders ever leave the app)."""

    SHADOW = "SHADOW"   # signals only, never sends orders
    PAPER = "PAPER"     # orders routed to IBKR paper account only
    LIVE = "LIVE"       # orders routed to the live account (must be explicitly enabled)


class Direction(str, Enum):
    """The only two directions allowed in v1: long calls, long puts."""

    CALL = "CALL"
    PUT = "PUT"


class OptionRight(str, Enum):
    CALL = "C"
    PUT = "P"


class SignalType(str, Enum):
    OPENING_RANGE_BREAKOUT = "OPENING_RANGE_BREAKOUT"
    VWAP_RECLAIM_CONTINUATION = "VWAP_RECLAIM_CONTINUATION"
    VWAP_REJECTION_CONTINUATION = "VWAP_REJECTION_CONTINUATION"
    MOMENTUM_BREAKOUT = "MOMENTUM_BREAKOUT"
    MOMENTUM_BREAKDOWN = "MOMENTUM_BREAKDOWN"
    PULLBACK_CONTINUATION = "PULLBACK_CONTINUATION"
    FAILED_BREAKOUT_REVERSAL = "FAILED_BREAKOUT_REVERSAL"
    FAILED_BREAKDOWN_REVERSAL = "FAILED_BREAKDOWN_REVERSAL"
    NO_SETUP = "NO_SETUP"


class ScoreBand(str, Enum):
    """Score-to-action bands. Values mirror the spec thresholds."""

    NO_TRADE = "NO_TRADE"          # < 70
    WATCH = "WATCH"                # 70-79
    REDUCED_RISK = "REDUCED_RISK"  # 80-89
    NORMAL = "NORMAL"              # >= 90

    @classmethod
    def from_score(cls, score: float) -> "ScoreBand":
        if score >= 90:
            return cls.NORMAL
        if score >= 80:
            return cls.REDUCED_RISK
        if score >= 70:
            return cls.WATCH
        return cls.NO_TRADE


class BehaviorState(str, Enum):
    """Behavior governor state. RED blocks all new trades."""

    CONTROLLED = "CONTROLLED"
    CAUTION = "CAUTION"
    RED = "RED"


class HealthStatus(str, Enum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    DOWN = "DOWN"
    UNKNOWN = "UNKNOWN"


class DataFeedStatus(str, Enum):
    LIVE = "LIVE"
    DELAYED = "DELAYED"
    FROZEN = "FROZEN"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


class OrderState(str, Enum):
    """Execution order state machine."""

    CANDIDATE = "CANDIDATE"
    RISK_APPROVED = "RISK_APPROVED"
    PREPARED = "PREPARED"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ExitReason(str, Enum):
    PROFIT_TARGET = "PROFIT_TARGET"
    STOP_LOSS = "STOP_LOSS"
    TIME_STOP = "TIME_STOP"
    MOMENTUM_FADE = "MOMENTUM_FADE"
    VWAP_FAIL = "VWAP_FAIL"
    OPPOSITE_SIGNAL = "OPPOSITE_SIGNAL"
    SPREAD_WIDENED = "SPREAD_WIDENED"
    MACRO_GUARD = "MACRO_GUARD"
    BROKER_UNSTABLE = "BROKER_UNSTABLE"
    DAILY_LOSS_LOCKOUT = "DAILY_LOSS_LOCKOUT"
    MANUAL_EMERGENCY = "MANUAL_EMERGENCY"


class RejectCode(str, Enum):
    """Verbatim scanner/risk rejection reason codes (rendered in the UI)."""

    BLOCKED_MACRO_EVENT = "BLOCKED_MACRO_EVENT"
    BLOCKED_LOW_SCORE = "BLOCKED_LOW_SCORE"
    BLOCKED_WIDE_SPREAD = "BLOCKED_WIDE_SPREAD"
    BLOCKED_LOW_VOLUME = "BLOCKED_LOW_VOLUME"
    BLOCKED_VWAP_CHOP = "BLOCKED_VWAP_CHOP"
    BLOCKED_OVEREXTENDED = "BLOCKED_OVEREXTENDED"
    BLOCKED_STALE_QUOTE = "BLOCKED_STALE_QUOTE"
    BLOCKED_DAILY_LOSS = "BLOCKED_DAILY_LOSS"
    BLOCKED_POSITION_MISMATCH = "BLOCKED_POSITION_MISMATCH"
    BLOCKED_DUPLICATE_SIGNAL = "BLOCKED_DUPLICATE_SIGNAL"
    BLOCKED_COOLDOWN = "BLOCKED_COOLDOWN"
    BLOCKED_CONTRACT_ABOVE_MAX_PRICE = "BLOCKED_CONTRACT_ABOVE_MAX_PRICE"
    BLOCKED_NO_0DTE_EXPIRY = "BLOCKED_NO_0DTE_EXPIRY"
    BLOCKED_BROKER_SESSION_INVALID = "BLOCKED_BROKER_SESSION_INVALID"
    BLOCKED_MISSING_MULTIPLIER = "BLOCKED_MISSING_MULTIPLIER"
    BLOCKED_DELAYED_DATA = "BLOCKED_DELAYED_DATA"
    BLOCKED_MARKET_CLOSED = "BLOCKED_MARKET_CLOSED"
    BLOCKED_MAX_OPEN_POSITIONS = "BLOCKED_MAX_OPEN_POSITIONS"
    BLOCKED_EXISTING_POSITION = "BLOCKED_EXISTING_POSITION"
    BLOCKED_BEHAVIOR_RED = "BLOCKED_BEHAVIOR_RED"
    BLOCKED_STOP_EXCEEDS_RISK = "BLOCKED_STOP_EXCEEDS_RISK"
    BLOCKED_SYSTEM_HEALTH = "BLOCKED_SYSTEM_HEALTH"
    BLOCKED_DIRECTION_FLIP = "BLOCKED_DIRECTION_FLIP"
    # Chart-context vetoes.
    BLOCKED_CHART_CONTEXT_STALE = "BLOCKED_CHART_CONTEXT_STALE"
    BLOCKED_CHART_CONTEXT_INCOMPLETE = "BLOCKED_CHART_CONTEXT_INCOMPLETE"
    BLOCKED_CHART_CONTEXT_TIME_MISMATCH = "BLOCKED_CHART_CONTEXT_TIME_MISMATCH"
    # Macro-release vetoes.
    BLOCKED_MACRO_PRE_RELEASE = "BLOCKED_MACRO_PRE_RELEASE"
    BLOCKED_MACRO_POST_RELEASE = "BLOCKED_MACRO_POST_RELEASE"
    BLOCKED_MACRO_RESULT_PENDING = "BLOCKED_MACRO_RESULT_PENDING"
    BLOCKED_MACRO_VOLATILITY_EXPANSION = "BLOCKED_MACRO_VOLATILITY_EXPANSION"
    BLOCKED_MACRO_TIMEZONE_VALIDATION_FAILED = "BLOCKED_MACRO_TIMEZONE_VALIDATION_FAILED"


class HealthComponent(str, Enum):
    IB_GATEWAY = "IB_GATEWAY"
    IB_SESSION = "IB_SESSION"
    MARKET_DATA = "MARKET_DATA"
    ACCOUNT = "ACCOUNT"
    POSITION_SYNC = "POSITION_SYNC"
    DATABASE = "DATABASE"
    CLOCK = "CLOCK"
    MACRO_CALENDAR = "MACRO_CALENDAR"
    BACKEND = "BACKEND"


class MacroEventStatus(str, Enum):
    SCHEDULED = "scheduled"
    RELEASE_WINDOW = "release_window"
    RELEASED = "released"
    DELAYED = "delayed"
    CANCELLED = "cancelled"
    UNAVAILABLE = "unavailable"


class MacroImportance(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ChartCompressionMethod(str, Enum):
    FULL = "full"
    TIERED_90M = "tiered_90m"
    PIVOTS_ONLY = "pivots_only"


class MarketStateHint(str, Enum):
    TREND_UP = "trend_up"
    TREND_DOWN = "trend_down"
    CHOP = "chop"
    RANGE = "range"
    REVERSAL_ATTEMPT = "reversal_attempt"
    BREAKDOWN_ATTEMPT = "breakdown_attempt"
    BREAKOUT_ATTEMPT = "breakout_attempt"


class RangePosition(str, Enum):
    NEAR_HIGH = "near_high"
    UPPER_RANGE = "upper_range"
    MID_RANGE = "mid_range"
    LOWER_RANGE = "lower_range"
    NEAR_LOW = "near_low"


class SurpriseDirection(str, Enum):
    HOTTER = "hotter"
    COOLER = "cooler"
    STRONGER = "stronger"
    WEAKER = "weaker"
    INLINE = "inline"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class RiskAssetInterpretation(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    MIXED = "mixed"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class RatesInterpretation(str, Enum):
    YIELDS_UP = "yields_up"
    YIELDS_DOWN = "yields_down"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class VolatilityInterpretation(str, Enum):
    VOL_EXPANSION = "vol_expansion"
    VOL_CRUSH = "vol_crush"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class TradePermission(str, Enum):
    """LLM guidance output — what the model recommends."""
    ALLOWED = "allowed"
    NO_TRADE = "no_trade"
    EXIT_ONLY = "exit_only"
    BLOCKED = "blocked"
