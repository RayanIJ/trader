"""Typed configuration schema.

Every operational threshold lives here and is validated on load. Defaults encode
the user's hard constraints: $100 max daily loss, $200 max premium per contract,
long calls/puts only, Shadow mode by default. The risk section is treated as
safety-critical: it cannot be *loosened* while a live session is active (enforced
by the config manager, not here).
"""
from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field, field_validator

from app.core.enums import TradingMode


class UniverseConfig(BaseModel):
    """Approved trading universe. The scanner only ever looks at these symbols."""

    index_symbols: List[str] = Field(default_factory=lambda: ["SPX"])
    semiconductor_symbols: List[str] = Field(
        default_factory=lambda: [
            "NVDA", "AVGO", "AMD", "TSM", "ASML", "INTC", "MU", "ARM",
            "MRVL", "QCOM", "TXN", "AMAT", "LRCX", "KLAC", "MCHP", "ON",
            "NXPI", "ADI",
        ]
    )
    sector_etfs: List[str] = Field(default_factory=lambda: ["SMH", "SOXX"])
    market_confirmation: List[str] = Field(default_factory=lambda: ["SPY"])
    tech_confirmation: List[str] = Field(default_factory=lambda: ["QQQ"])
    volatility_proxy: str = "VIX"

    @property
    def all_tradable(self) -> List[str]:
        """Symbols we may actually trade (not pure confirmation tickers)."""
        return list(dict.fromkeys(self.index_symbols + self.semiconductor_symbols))

    @property
    def all_scanned(self) -> List[str]:
        seen = (
            self.index_symbols
            + self.semiconductor_symbols
            + self.sector_etfs
            + self.market_confirmation
            + self.tech_confirmation
        )
        return list(dict.fromkeys(seen))


class RiskConfig(BaseModel):
    """Safety-critical hard limits. Loosening these mid-live-session is blocked."""

    max_daily_loss_usd: float = Field(default=100.0, gt=0)
    max_premium_per_contract_usd: float = Field(default=200.0, gt=0)
    max_open_positions: int = Field(default=1, ge=1)
    max_position_per_underlying: int = Field(default=1, ge=1)
    max_total_premium_exposure_usd: float = Field(default=200.0, gt=0)

    # Anti-overtrading cooldowns (seconds).
    cooldown_after_trade_sec: int = Field(default=120, ge=0)
    cooldown_after_loss_sec: int = Field(default=600, ge=0)
    cooldown_same_underlying_sec: int = Field(default=300, ge=0)

    # Behavior governor thresholds.
    caution_trades_per_hour: int = Field(default=3, ge=1)
    block_setup_after_losses: int = Field(default=2, ge=1)
    block_symbol_after_same_dir_losses: int = Field(default=2, ge=1)


class OptionFilterConfig(BaseModel):
    max_spread_pct: float = Field(default=12.0, gt=0, le=100)
    preferred_spread_pct: float = Field(default=8.0, gt=0, le=100)
    min_option_bid: float = Field(default=0.05, ge=0)
    min_option_volume: int = Field(default=50, ge=0)
    min_open_interest: int = Field(default=100, ge=0)
    delta_min: float = Field(default=0.30, ge=0, le=1)
    delta_max: float = Field(default=0.70, ge=0, le=1)
    gamma_warning: float = Field(default=0.10, ge=0)
    theta_warning: float = Field(default=-0.50, le=0)
    max_abnormal_quote_jump_pct: float = Field(default=30.0, gt=0)

    @field_validator("preferred_spread_pct")
    @classmethod
    def preferred_le_max(cls, v: float, info):
        max_spread = info.data.get("max_spread_pct")
        if max_spread is not None and v > max_spread:
            raise ValueError("preferred_spread_pct must be <= max_spread_pct")
        return v

    @field_validator("delta_max")
    @classmethod
    def delta_range_valid(cls, v: float, info):
        dmin = info.data.get("delta_min")
        if dmin is not None and v < dmin:
            raise ValueError("delta_max must be >= delta_min")
        return v


class SignalConfig(BaseModel):
    min_score_to_trade: float = Field(default=70.0, ge=0, le=100)
    watch_band_floor: float = Field(default=70.0, ge=0, le=100)
    reduced_risk_band_floor: float = Field(default=80.0, ge=0, le=100)
    normal_band_floor: float = Field(default=90.0, ge=0, le=100)
    min_relative_volume: float = Field(default=1.5, gt=0)
    vwap_chop_cross_limit: int = Field(default=3, ge=1)
    vwap_chop_window_min: int = Field(default=20, ge=1)
    opening_range_minutes: int = Field(default=15, ge=1)


class MacroConfig(BaseModel):
    enabled: bool = True
    block_minutes_before: int = Field(default=10, ge=0)
    block_minutes_after: int = Field(default=5, ge=0)
    # Default scalping behavior: flatten open positions before a high-impact
    # event rather than holding through it.
    exit_before_event: bool = True
    exit_before_event_minutes: int = Field(default=10, ge=0)
    high_impact_events: List[str] = Field(
        default_factory=lambda: [
            "CPI", "PPI", "FOMC_RATE_DECISION", "FOMC_PRESS_CONFERENCE",
            "NONFARM_PAYROLLS", "UNEMPLOYMENT_RATE", "AVG_HOURLY_EARNINGS",
            "ISM_MANUFACTURING", "ISM_SERVICES", "PMI", "GDP", "PCE",
            "RETAIL_SALES", "JOBLESS_CLAIMS", "TREASURY_AUCTION",
            "FED_CHAIR_SPEECH", "FED_SPEAKER",
        ]
    )


class EntryTimingConfig(BaseModel):
    """No-late-entry guards. Scalps must enter on *fresh* momentum, never chase.

    These bind the signal engine (Phase 3): a candidate is rejected if the move
    is already extended, the option premium already expanded, the triggering
    candle is oversized vs recent 1-minute candles, or entry would require
    chasing past the trigger level.
    """

    # Reject if price has already traveled this fraction of the expected scalp
    # distance (key level -> measured/target move) before we would enter.
    max_scalp_distance_traveled_pct: float = Field(default=0.70, gt=0, le=1.0)
    # Reject if the option premium already expanded by more than this % over a
    # short pre-entry window (premium chasing).
    max_premium_preexpansion_pct: float = Field(default=25.0, gt=0)
    # Reject if the trigger candle's body is larger than this multiple of the
    # recent 1-minute average candle body (over-extended single candle).
    max_candle_extension_mult: float = Field(default=2.0, gt=0)
    # Max distance (as % of underlying) price may be beyond the breakout/breakdown
    # level and still be a valid (non-chasing) entry.
    max_distance_beyond_level_pct: float = Field(default=0.15, gt=0)
    reject_if_chasing: bool = True


class ExecutionConfig(BaseModel):
    """Order handling + scalp exit plan. Every trade gets an exit plan BEFORE entry.

    Bias is explicitly toward fast exits: take a smaller fast profit over a larger
    uncertain one. The app must never use market close as a normal exit, never
    convert a scalp into a swing, and never hold through chop.
    """

    # --- Entry order handling (marketable limit only; never naked market). ---
    order_timeout_sec: float = Field(default=3.0, gt=0)
    reprice_attempts: int = Field(default=1, ge=0)
    max_slippage_pct: float = Field(default=5.0, gt=0)
    use_marketable_limit: bool = True
    allow_naked_market_orders: bool = False  # must stay False — spec forbids it

    # --- Holding-time controls (1-5 min target). ---
    hard_time_stop_sec: int = Field(default=300, gt=0)         # absolute max hold (5 min)
    no_movement_exit_sec: int = Field(default=75, gt=0)        # fast-failure window (60-90s)
    fast_failure_min_sec: int = Field(default=30, ge=0)        # earliest fast-failure check
    fast_failure_max_sec: int = Field(default=90, gt=0)        # latest fast-failure check

    # --- Premium-based profit targets / stops (% of entry premium). ---
    first_profit_target_pct: float = Field(default=20.0, gt=0)   # band 15-25
    strong_profit_target_pct: float = Field(default=40.0, gt=0)  # band 30-50
    stop_loss_pct: float = Field(default=25.0, gt=0)             # band 20-30
    # If profit reaches a target then gives back this much of peak, sell-to-close.
    profit_giveback_pct: float = Field(default=10.0, gt=0)

    # --- Hard scalp invariants (must remain True). ---
    exit_before_macro: bool = True            # default: flatten before high-impact events
    forbid_hold_to_close: bool = True         # market close is never a normal exit
    forbid_scalp_to_swing: bool = True        # never let a scalp become a swing

    @field_validator("strong_profit_target_pct")
    @classmethod
    def strong_ge_first(cls, v: float, info):
        first = info.data.get("first_profit_target_pct")
        if first is not None and v < first:
            raise ValueError("strong_profit_target_pct must be >= first_profit_target_pct")
        return v

    @field_validator("fast_failure_max_sec")
    @classmethod
    def fast_failure_within_time_stop(cls, v: float, info):
        hard = info.data.get("hard_time_stop_sec")
        if hard is not None and v > hard:
            raise ValueError("fast_failure_max_sec must be <= hard_time_stop_sec")
        return v


class DataQualityConfig(BaseModel):
    underlying_stale_sec: float = Field(default=3.0, gt=0)
    option_stale_sec: float = Field(default=5.0, gt=0)
    max_clock_drift_sec: float = Field(default=2.0, gt=0)
    require_live_data: bool = True   # block trading on delayed data
    require_position_sync: bool = True


class BrokerConfig(BaseModel):
    """TWS socket API connection. Defaults match the existing src/ib setup."""

    host: str = "127.0.0.1"
    paper_port: int = 7497
    live_port: int = 7496
    client_id: int = 1
    market_data_type: int = 1  # 1=live, 2=frozen, 3=delayed, 4=delayed-frozen


class MarketDataConfig(BaseModel):
    """Market-data source + scanner cadence.

    ``source`` defaults to ``simulated`` so the full pipeline runs offline and is
    deterministically testable; switch to ``tws`` to ingest live candles/quotes
    and option chains from TWS/IB Gateway.
    """

    source: str = Field(default="simulated", pattern="^(simulated|tws)$")
    scan_interval_sec: float = Field(default=5.0, gt=0)
    candle_lookback_1m: int = Field(default=120, ge=20)   # minutes of 1-min bars
    candle_lookback_5m: int = Field(default=78, ge=10)    # 5-min bars (~1 session)
    relative_volume_lookback_days: int = Field(default=14, ge=1)
    ema_fast: int = Field(default=9, ge=2)
    ema_slow: int = Field(default=21, ge=3)
    simulated_seed: int = Field(default=1337)


class AppConfig(BaseModel):
    """Root configuration object."""

    default_mode: TradingMode = TradingMode.SHADOW
    timezone: str = "America/New_York"
    universe: UniverseConfig = Field(default_factory=UniverseConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    options: OptionFilterConfig = Field(default_factory=OptionFilterConfig)
    signal: SignalConfig = Field(default_factory=SignalConfig)
    entry: EntryTimingConfig = Field(default_factory=EntryTimingConfig)
    macro: MacroConfig = Field(default_factory=MacroConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    data_quality: DataQualityConfig = Field(default_factory=DataQualityConfig)
    broker: BrokerConfig = Field(default_factory=BrokerConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)

    @field_validator("default_mode")
    @classmethod
    def default_mode_not_live(cls, v: TradingMode) -> TradingMode:
        # The app must never *default* to live trading.
        if v == TradingMode.LIVE:
            raise ValueError("default_mode cannot be LIVE; Live must be enabled explicitly")
        return v
