"""Chart-context validation — pre-flight checks before calling the LLM.

Ensures the 1-minute bar data is fresh, monotonic, complete, and not stale.
If any check fails the system blocks new entries and degrades LLM guidance.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.enums import RejectCode
from app.core.logging import get_logger
from app.core.timezone import is_market_open

logger = get_logger("chart_validator")


def validate_chart_context(
    enriched_bars: list[dict],
    now: datetime | None = None,
    stale_threshold_sec: float = 90.0,
) -> tuple[bool, list[str], RejectCode | None]:
    """Validate chart data before sending to LLM.

    Returns ``(valid, issues, reject_code)``.  If valid is True the reject_code
    is None.
    """
    now = now or datetime.now(timezone.utc)
    issues: list[str] = []

    # 1. Must have bars.
    if not enriched_bars:
        issues.append("no chart bars available")
        return False, issues, RejectCode.BLOCKED_CHART_CONTEXT_INCOMPLETE

    # 2. Latest bar freshness.
    last_ts_str = enriched_bars[-1].get("timestamp_et")
    if last_ts_str is None:
        issues.append("latest bar missing timestamp_et")
        return False, issues, RejectCode.BLOCKED_CHART_CONTEXT_INCOMPLETE

    try:
        from app.core.timezone import ET
        from datetime import datetime as _dt
        last_ts = _dt.fromisoformat(last_ts_str)
        if last_ts.tzinfo is None:
            last_ts = last_ts.replace(tzinfo=ET)
        from app.core.timezone import to_utc
        age_sec = (now - to_utc(last_ts)).total_seconds()
        if age_sec > stale_threshold_sec:
            issues.append(f"latest bar is {age_sec:.0f}s old (threshold {stale_threshold_sec}s)")
            return False, issues, RejectCode.BLOCKED_CHART_CONTEXT_STALE
    except (ValueError, TypeError) as exc:
        issues.append(f"cannot parse latest bar timestamp: {exc}")
        return False, issues, RejectCode.BLOCKED_CHART_CONTEXT_INCOMPLETE

    # 3. Monotonic timestamps.
    prev_ts_str = None
    for i, bar in enumerate(enriched_bars):
        ts_str = bar.get("timestamp_et")
        if ts_str is None:
            issues.append(f"bar {i} missing timestamp")
            continue
        if prev_ts_str is not None and ts_str <= prev_ts_str:
            issues.append(f"non-monotonic timestamp at bar {i}: {ts_str} <= {prev_ts_str}")
            return False, issues, RejectCode.BLOCKED_CHART_CONTEXT_TIME_MISMATCH
        prev_ts_str = ts_str

    # 4. Critical fields not null in recent bars (check last 5).
    critical_fields = ["open", "high", "low", "close", "volume"]
    for bar in enriched_bars[-5:]:
        for field in critical_fields:
            if bar.get(field) is None:
                issues.append(f"null {field} in recent bar {bar.get('timestamp_et')}")
                return False, issues, RejectCode.BLOCKED_CHART_CONTEXT_INCOMPLETE

    # 5. Market session check (warning only — pre/post market bars are valid
    #    but the system should note it).
    if not is_market_open(now):
        issues.append("market is not in regular session")
        # This is informational, not a blocker — pre-market analysis is valid.

    if issues:
        logger.warning("chart context issues (non-blocking): %s", issues)

    return True, issues, None
