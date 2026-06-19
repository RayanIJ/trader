"""LLM context builder — assembles the full guidance request payload.

Pulls chart data, macro context, and risk state from the runtime and
serialises everything into a single JSON-ready dict matching the spec.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from app.core.enums import ChartCompressionMethod
from app.core.logging import get_logger
from app.core.timezone import dual_timestamp, to_et, to_riyadh
from app.llm.chart_serializer import serialize_chart, serialize_session_summary
from app.llm.chart_validator import validate_chart_context
from app.llm.models import (
    LLMGuidanceRequest,
    MacroContextPayload,
    MacroEventPayload,
    ReleaseReactionSummary,
    RequestMetadata,
    RiskContextPayload,
    SessionSummary,
)
from app.market_data.intraday_bars import enrich_bars, get_session_bars

if TYPE_CHECKING:
    from app.runtime import Runtime

logger = get_logger("context_builder")


async def build_guidance_request(
    runtime: "Runtime",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the full LLM guidance request payload.

    Returns a JSON-serialisable dict matching ``LLMGuidanceRequest``.
    """
    now = now or datetime.now(timezone.utc)
    cfg = runtime.config

    # -- 1. Chart context (SPX) --
    symbol = "SPX"
    candles = await get_session_bars(runtime.market_data, symbol, now)
    enriched = enrich_bars(candles)

    # Validate before sending.
    stale_sec = getattr(cfg, "llm", None)
    stale_threshold = stale_sec.chart_stale_sec if stale_sec else 90.0
    chart_valid, chart_issues, chart_reject = validate_chart_context(
        enriched, now, stale_threshold_sec=stale_threshold,
    )

    # Compress if needed.
    max_bars = stale_sec.max_full_bars if stale_sec else 390
    chart_bars, compression = serialize_chart(enriched, max_full_bars=max_bars)

    # Session summary.
    quote = await runtime.market_data.get_quote(symbol)
    refs = await runtime.market_data.get_reference_levels(symbol)
    # Build FeatureSet for state hint (reuse existing engine).
    from app.features.engine import FeatureEngine
    feat_engine = FeatureEngine(cfg.market_data, cfg.signal)
    fs = None
    if candles:
        avg_vol = await runtime.market_data.get_historical_avg_volume(symbol)
        fs = feat_engine.build(symbol, candles, quote, refs, historical_avg_volume=avg_vol, now=now)

    session_summary = serialize_session_summary(candles, refs, quote, fs, now)

    # -- 2. Request metadata --
    ts = dual_timestamp(now)
    mode = runtime.mode_manager.mode.value.lower()
    metadata = {
        "request_time_et": ts["timestamp_et"],
        "request_time_gmt3": ts["timestamp_gmt3"],
        "guidance_valid_for_seconds": 300,
        "market": symbol,
        "trading_mode": mode,
    }

    # -- 3. Macro context --
    macro_ctx = _build_macro_context(runtime, now)

    # -- 4. Risk context --
    risk_ctx = _build_risk_context(runtime)

    # -- 5. Assemble --
    payload = {
        "request_metadata": metadata,
        "session_summary": session_summary,
        "one_minute_chart": chart_bars,
        "macro_context": macro_ctx,
        "risk_context": risk_ctx,
        "chart_valid": chart_valid,
        "chart_issues": chart_issues,
        "compression_method": compression.value,
        "bar_count": len(enriched),
    }

    logger.info(
        "guidance context built: bars=%d compression=%s chart_valid=%s macro_events=%d",
        len(enriched), compression.value, chart_valid,
        len(macro_ctx.get("todays_events", [])),
    )
    return payload


def _build_macro_context(runtime: "Runtime", now: datetime) -> dict[str, Any]:
    """Build the macro_context section."""
    macro_status = runtime.macro_guard.status(now)
    events = runtime.macro_guard.events

    todays_events: list[dict] = []
    for e in events:
        ts = dual_timestamp(e.event_time)
        todays_events.append({
            "event_id": f"{e.name}_{e.event_time.strftime('%H%M')}",
            "name": e.name,
            "country": "US",
            "importance": e.impact.lower() if e.impact else "high",
            "release_time_et": ts["timestamp_et"],
            "release_time_gmt3": ts["timestamp_gmt3"],
            "source": "configured_provider",
            "consensus": None,
            "prior": None,
            "actual": None,
            "status": "scheduled",
            "trading_block_before_minutes": e.block_minutes_before or 3,
            "trading_block_after_minutes": e.block_minutes_after or 3,
            "requires_release_update": True,
        })

    # Identify next event.
    upcoming = [e for e in events if e.event_time >= now]
    next_event = None
    if upcoming:
        ne = upcoming[0]
        ts = dual_timestamp(ne.event_time)
        next_event = {
            "event_id": f"{ne.name}_{ne.event_time.strftime('%H%M')}",
            "name": ne.name,
            "country": "US",
            "importance": ne.impact.lower() if ne.impact else "high",
            "release_time_et": ts["timestamp_et"],
            "release_time_gmt3": ts["timestamp_gmt3"],
            "source": "configured_provider",
            "status": "scheduled",
        }

    # Latest released event + reaction (populated by release monitor).
    latest_released = getattr(runtime, "_latest_release_event", None)
    reaction_summary = getattr(runtime, "_latest_release_reaction", None)

    return {
        "todays_events": todays_events,
        "next_event": next_event,
        "active_macro_block": macro_status.blocked,
        "latest_released_event": latest_released,
        "release_reaction_summary": reaction_summary,
    }


def _build_risk_context(runtime: "Runtime") -> dict[str, Any]:
    """Build the risk_context section."""
    day = runtime.day_state
    cfg = runtime.config

    peak = max(day.realized_pnl, 0.0)
    giveback = max(peak - day.realized_pnl, 0.0) if peak > 0 else 0.0

    # Count losing trades.
    losing = len(day.recent_losses)

    # Determine system mode.
    if day.lockout:
        sys_mode = "blocked"
    elif day.realized_pnl < -(cfg.risk.max_daily_loss_usd * 0.7):
        sys_mode = "protect_day"
    elif runtime.mode_manager.mode.value == "SHADOW":
        sys_mode = "normal"
    else:
        sys_mode = "normal"

    # Current open position.
    pos = runtime.position_manager.position
    open_pos = None
    if pos:
        open_pos = {
            "underlying": pos.underlying,
            "direction": pos.direction.value if hasattr(pos.direction, "value") else str(pos.direction),
            "entry_price": pos.entry_price,
            "quantity": pos.quantity,
            "is_shadow": pos.is_shadow,
        }

    return {
        "daily_realized_pnl": round(day.realized_pnl, 2),
        "peak_daily_pnl": round(peak, 2),
        "giveback_from_peak": round(giveback, 2),
        "round_trips_used": day.trades_today,
        "max_round_trips": 5,
        "losing_trades_used": losing,
        "max_losing_trades": cfg.risk.block_setup_after_losses,
        "current_open_position": open_pos,
        "current_system_mode": sys_mode,
    }
