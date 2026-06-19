"""Tests for signal + risk engines."""
from datetime import datetime, timedelta, timezone

import pytest

from app.config.manager import ConfigManager
from app.core.enums import BehaviorState, Direction, RejectCode
from app.features.chop import ChopResult
from app.features.engine import FeatureSet
from app.macro.calendar import MacroEventDTO, MacroGuard
from app.risk.behavior import BehaviorGovernor
from app.risk.day_state import RecentSignal, TradingDayState
from app.risk.engine import RiskEngine
from app.risk.premium import size_position
from app.scanner.regime import MarketRegime
from app.signals.engine import SignalEngine


def _fs(**kw) -> FeatureSet:
    base = dict(
        symbol="NVDA", ts=datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc),
        price=100.0, vwap=99.0, ema_fast=100.0, ema_slow=99.0,
        opening_range_high=98.0, opening_range_low=96.0,
        prev_close=95.0, day_high=101.0, day_low=96.0,
        relative_volume=2.0, volume_impulse=1.5,
        candle_body_pct=50.0, upper_wick_pct=10.0, lower_wick_pct=10.0,
        trend_slope=0.1, dist_from_vwap_pct=1.0,
        dist_from_or_high_pct=0.5, dist_from_or_low_pct=-2.0,
        spread_pct=0.1, above_vwap=True, higher_highs=True, lower_lows=False,
        momentum_score=80.0, bias="UP",
        chop=ChopResult(
            score=20.0, band="LOW", vwap_crosses=1,
            small_body_ratio=0.2, alternation_ratio=0.3, components={},
        ),
    )
    base.update(kw)
    return FeatureSet(**base)


def _regime() -> MarketRegime:
    return MarketRegime(overall="RISK_ON")


def test_premium_cap_blocks_above_200():
    sizing = size_position(
        ask=2.50, multiplier=100.0, stop_loss_pct=25.0,
        max_premium_per_contract_usd=200.0, remaining_daily_loss_usd=100.0,
    )
    assert sizing.rejected


def test_stop_exceeds_remaining_daily_loss():
    sizing = size_position(
        ask=2.00, multiplier=100.0, stop_loss_pct=25.0,
        max_premium_per_contract_usd=200.0, remaining_daily_loss_usd=40.0,
    )
    assert sizing.rejected
    assert "stop risk" in (sizing.reason or "")


def test_daily_loss_lockout():
    cfg = ConfigManager().config
    day = TradingDayState.for_today()
    day.realized_pnl = -100.0
    assert day.check_daily_loss(cfg.risk.max_daily_loss_usd) == RejectCode.BLOCKED_DAILY_LOSS


def test_behavior_red_on_lockout():
    cfg = ConfigManager().config
    day = TradingDayState.for_today()
    day.apply_lockout("test")
    gov = BehaviorGovernor(cfg.risk)
    st = gov.evaluate(day)
    assert st.state == BehaviorState.RED


def test_signal_rejects_low_score():
    cfg = ConfigManager().config
    eng = SignalEngine(cfg)
    dec = eng.evaluate(
        _fs(), Direction.CALL, _regime(), score=65.0, is_index=False,
        quote=None, candles=[], macro_blocked=False,
    )
    assert not dec.approved
    assert RejectCode.BLOCKED_LOW_SCORE in dec.reject_codes


def test_risk_rejects_macro_block():
    cfg = ConfigManager().config
    macro = MacroGuard(cfg.macro)
    t = datetime(2026, 6, 2, 14, 30, tzinfo=timezone.utc)
    macro.set_events([MacroEventDTO(name="CPI", event_time=t)])
    risk = RiskEngine(cfg)
    from app.signals.engine import SignalDecision
    from app.core.enums import ScoreBand

    sig = SignalDecision(approved=True, band=ScoreBand.NORMAL, score=92.0)
    behavior = BehaviorGovernor(cfg.risk).evaluate(TradingDayState.for_today())
    dec = risk.evaluate(
        symbol="NVDA", direction=Direction.CALL, signal_type="MOMENTUM_BREAKOUT",
        signal=sig, day=TradingDayState.for_today(), macro=macro, behavior=behavior,
        option_ask=1.5, multiplier=100.0, now=t,
    )
    assert not dec.approved
    macro_reject_codes = {
        RejectCode.BLOCKED_MACRO_EVENT,
        RejectCode.BLOCKED_MACRO_PRE_RELEASE,
        RejectCode.BLOCKED_MACRO_POST_RELEASE,
    }
    assert any(rc in macro_reject_codes for rc in dec.reject_codes)


def test_cooldown_blocks_rapid_reentry():
    cfg = ConfigManager().config
    day = TradingDayState.for_today()
    now = datetime(2026, 6, 2, 14, 0, tzinfo=timezone.utc)
    day.recent_signals.append(
        RecentSignal("NVDA", Direction.CALL, "MOMENTUM_BREAKOUT", now - timedelta(seconds=30))
    )
    rc = day.cooldown_reject("NVDA", Direction.CALL, cfg.risk, now)
    assert rc == RejectCode.BLOCKED_COOLDOWN
